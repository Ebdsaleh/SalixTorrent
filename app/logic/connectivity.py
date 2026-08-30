# app/logic/connectivity.py

from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple


SSDP_ADDRESS = ("239.255.255.250", 1900)
NATPMP_PORT = 5351
MAPPING_LIFETIME_SECONDS = 3600
MAPPING_REFRESH_SECONDS = int(MAPPING_LIFETIME_SECONDS * 0.80)
MAPPING_RETRY_SECONDS = 300


NATPMP_RESULT_MESSAGES = {
    1: "unsupported NAT-PMP version",
    2: "mapping was refused or not authorized",
    3: "gateway reported a network failure",
    4: "gateway has no mapping resources available",
    5: "gateway does not support this NAT-PMP operation",
}

UPNP_FAULT_ADVICE = {
    "401": "The gateway does not support the requested UPnP action.",
    "402": "The gateway rejected one or more UPnP arguments.",
    "606": "The gateway is not authorized to create this mapping.",
    "714": "The requested mapping does not exist.",
    "715": "The gateway does not permit wildcard values for this mapping.",
    "716": "The gateway does not permit wildcard external ports.",
    "718": "That external port is already mapped to another device or application.",
    "724": "The gateway requires the internal and external ports to match.",
    "725": "The gateway only supports permanent UPnP mappings.",
    "726": "The gateway requires the remote-host field to be empty.",
    "727": "The gateway requires a wildcard external port for this operation.",
}


class PortMappingFailure(RuntimeError):
    """Structured, user-presentable failure from an automatic mapping method."""

    def __init__(
        self,
        stage: str,
        summary: str,
        *,
        code: str = "",
        advice: str = "",
        technical: str = "",
    ):
        self.stage = str(stage or "Unknown stage")
        self.summary = str(summary or "Port mapping failed.")
        self.code = str(code or "")
        self.advice = str(advice or "")
        self.technical = str(technical or "")
        super().__init__(self.summary)


class ConnectivityManager:
    """Best-effort incoming-connectivity helper.

    This module deliberately has no third-party dependency. It can create a
    TCP (and optionally UDP) mapping using either UPnP IGD or NAT-PMP and keeps
    a small thread-safe telemetry snapshot for the Preferences/General views.

    A successful router mapping is reported as ``Mapped``. SalixTorrent only
    reports ``Incoming Confirmed`` after a real remote peer has connected to
    the application's BitTorrent listener; a port mapping alone is not treated
    as proof that every upstream firewall permits inbound traffic.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending_maps: Dict[int, dict] = {}
        self._pending_removals = set()
        self._worker: Optional[threading.Thread] = None
        self._mappings: Dict[int, dict] = {}
        self._snapshots: Dict[int, Dict[str, object]] = {}
        self._active_ports = set()
        self._port_requests: Dict[int, dict] = {}
        self._refresh_deadlines: Dict[int, float] = {}
        self._renew_timer: Optional[threading.Timer] = None
        self._renew_generation: int = 0
        self._probe_port: Optional[int] = None
        self._closed = False
        self._snapshot: Dict[str, object] = self._empty_snapshot()

    @staticmethod
    def _empty_snapshot(port: int = 0) -> Dict[str, object]:
        return {
            "status": "Waiting",
            "method": "None",
            "local_ip": "",
            "external_ip": "",
            "internal_port": int(port or 0),
            "external_port": 0,
            "mapped_tcp": False,
            "mapped_udp": False,
            "upnp_status": "Not tried",
            "upnp_stage": "",
            "upnp_code": "",
            "upnp_error": "",
            "upnp_advice": "",
            "natpmp_status": "Not tried",
            "natpmp_stage": "",
            "natpmp_code": "",
            "natpmp_error": "",
            "natpmp_advice": "",
            "external_scope": "Unknown",
            "diagnosis": "",
            "action_hint": "",
            "last_error": "",
            "last_refresh_at": 0.0,
            "last_incoming_at": 0.0,
            "last_incoming_peer": "",
            "mapping_count": 0,
            "listener_count": 0,
            "mapped_ports": [],
            "active_listener_ports": [],
            "mapping_lease_seconds": None,
            "mapping_permanent": False,
            "next_mapping_refresh_seconds": None,
        }

    @staticmethod
    def _normalise_port(value: object, fallback: int = 6881) -> int:
        try:
            port = int(value or fallback)
        except (TypeError, ValueError):
            port = fallback
        return max(1, min(65535, port))

    @staticmethod
    def _request_for_port(settings: dict, port: int) -> dict:
        bind_address = str(settings.get("network_bind_address") or "").strip()
        ipv6_only = False
        if bind_address:
            try:
                ipv6_only = ipaddress.ip_address(bind_address).version == 6
            except ValueError:
                bind_address = ""
        return {
            "port": int(port),
            "enable_upnp": bool(settings.get("enable_upnp", True)),
            "enable_natpmp": bool(settings.get("enable_natpmp", True)),
            "map_udp": bool(settings.get("enable_dht", True)),
            "network_bind_address": bind_address,
            "ipv6_only": ipv6_only,
        }

    @staticmethod
    def _failure_payload(exc: Exception) -> dict:
        if isinstance(exc, PortMappingFailure):
            return {
                "stage": exc.stage,
                "code": exc.code,
                "error": exc.summary,
                "advice": exc.advice,
                "technical": exc.technical,
            }
        return {
            "stage": "Unexpected failure",
            "code": exc.__class__.__name__,
            "error": str(exc) or exc.__class__.__name__,
            "advice": "Retry the mapping. If it continues to fail, use manual port forwarding or check the router's automatic port-mapping settings.",
            "technical": repr(exc),
        }

    @staticmethod
    def _external_scope(address: object) -> str:
        text = str(address or "").strip()
        if not text:
            return "Unknown"
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            return "Unknown"
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return "Shared/CGNAT"
        if ip.is_global:
            return "Public"
        if ip.is_private:
            return "Private"
        if ip.is_loopback:
            return "Loopback"
        if ip.is_link_local:
            return "Link-local"
        return "Non-global"

    @staticmethod
    def _mapping_method_summary(label: str, result: dict) -> str:
        prefix = str(label or "Mapping")
        key = "upnp" if prefix.upper() == "UPNP" else "natpmp"
        status = str(result.get(f"{key}_status") or "Not tried")
        stage = str(result.get(f"{key}_stage") or "").strip()
        code = str(result.get(f"{key}_code") or "").strip()
        error = str(result.get(f"{key}_error") or "").strip()
        if status == "Failed":
            where = f" at {stage}" if stage else ""
            code_text = f" [{code}]" if code else ""
            detail = f": {error}" if error else ""
            return f"{prefix} Failed{where}{code_text}{detail}"
        if stage and status not in {"Disabled", "Not tried", "Not needed"}:
            return f"{prefix} {status} ({stage})"
        return f"{prefix} {status}"

    @classmethod
    def _decorate_guidance(cls, result: dict) -> dict:
        result = dict(result)
        status = str(result.get("status") or "Waiting")
        port = int(result.get("internal_port") or 0)
        external_scope = cls._external_scope(result.get("external_ip"))
        result["external_scope"] = external_scope
        result["upnp_summary"] = cls._mapping_method_summary("UPnP", result)
        result["natpmp_summary"] = cls._mapping_method_summary("NAT-PMP", result)

        if status == "Incoming Confirmed":
            diagnosis = "Inbound BitTorrent connectivity is confirmed by a real remote peer."
            action = "No action is required for incoming reachability."
        elif status == "IPv6 Direct":
            diagnosis = (
                "This torrent is bound to IPv6. UPnP and NAT-PMP are IPv4 NAT mapping mechanisms, "
                "so no router mapping is required or attempted for this listener."
            )
            action = (
                "IPv6 inbound reachability depends on the host/router firewall and globally routable IPv6. "
                "Incoming Confirmed appears after a real remote IPv6 peer connects."
            )
        elif status == "Mapped (refresh failed)":
            diagnosis = "The previous router mapping is being retained, but its latest lease refresh failed."
            action = "SalixTorrent will retry automatically before discarding the still-usable mapping; use Refresh / Remap Now only if you want an immediate retry."
        elif status == "Partially Mapped":
            diagnosis = "Some active torrent listener ports are mapped and others are not."
            action = "Inspect the selected torrent's General view or Diagnostics to see which listener port needs attention."
        elif status.startswith("Mapped"):
            if external_scope in {"Private", "Shared/CGNAT", "Non-global"}:
                diagnosis = (
                    "The local router accepted the mapping, but it reports a non-public "
                    f"external address ({external_scope}). An upstream NAT may still block "
                    "unsolicited Internet connections."
                )
                action = (
                    "If Incoming Confirmed never appears, check for double NAT/CGNAT or use "
                    "an ISP/VPN service that provides an inbound forwarded port."
                )
            else:
                diagnosis = (
                    "The router accepted a TCP mapping. SalixTorrent is waiting for a real "
                    "remote peer to confirm that the complete inbound path is reachable."
                )
                action = "No immediate action is needed; confirmation occurs only when an Internet peer connects inbound."
        elif status == "Disabled":
            diagnosis = "Automatic router port mapping is disabled."
            action = (
                f"Outbound peer connections can still seed. For inbound reachability, enable UPnP/NAT-PMP "
                f"or manually forward TCP port {port}." if port else
                "Outbound peer connections can still seed. Enable UPnP/NAT-PMP or configure a manual port forward for inbound reachability."
            )
        elif status == "Unmapped":
            upnp_code = str(result.get("upnp_code") or "")
            natpmp_code = str(result.get("natpmp_code") or "")
            upnp_stage = str(result.get("upnp_stage") or "")
            natpmp_stage = str(result.get("natpmp_stage") or "")
            if upnp_code == "718":
                diagnosis = "UPnP reached the router, but the requested external port is already mapped elsewhere."
                action = "Choose another listen port or remove the conflicting router mapping, then use Refresh / Remap Now."
            elif natpmp_code == "2" or upnp_code in {"606", "401"}:
                diagnosis = "The gateway was reachable but refused or did not authorize automatic port mapping."
                action = "Enable automatic port mapping on the router, or configure a manual TCP port forward to this computer."
            elif (upnp_code == "NO_IGD" and natpmp_code == "NO_RESPONSE") or (
                "Discovery" in upnp_stage and "Gateway" in natpmp_stage
            ):
                diagnosis = "No supported automatic port-mapping service answered on the local network."
                action = (
                    f"Outbound seeding still works. To accept more inbound peers, enable UPnP/NAT-PMP on the router "
                    f"or manually forward TCP port {port}" + (
                        f" (and UDP {port} for DHT reachability)." if port else "."
                    )
                )
            elif natpmp_code == "NO_GATEWAY":
                diagnosis = "SalixTorrent could not determine a default IPv4 gateway for NAT-PMP."
                action = "Check the active network/VPN route. Outbound torrent traffic can still work even when automatic inbound mapping is unavailable."
            else:
                diagnosis = "Automatic incoming port mapping did not succeed. This does not stop outbound downloading or seeding."
                advice = [
                    str(result.get("upnp_advice") or "").strip(),
                    str(result.get("natpmp_advice") or "").strip(),
                ]
                action = next((item for item in advice if item), "Enable router port mapping or use a manual TCP port forward; check for double NAT/CGNAT if the local router is configured correctly.")
        elif status == "Mapping":
            diagnosis = "SalixTorrent is currently checking automatic incoming port mapping."
            action = "No action is needed while this check is in progress."
        else:
            diagnosis = "Incoming connectivity has not been determined yet."
            action = "SalixTorrent will update this state after the listener and mapping checks run."

        result["diagnosis"] = diagnosis
        result["action_hint"] = action
        return result

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def request_refresh(self, settings: dict, actual_port: Optional[int] = None):
        """Refresh mappings without replacing unrelated torrent listeners.

        ``actual_port`` is retained for compatibility with the original API.
        Passing a real bound port registers that listener. A refresh without an
        actual port refreshes every active listener; when no torrent is
        listening it performs a single configured-port probe for Preferences.
        """
        if actual_port is not None:
            try:
                numeric = int(actual_port)
            except (TypeError, ValueError):
                numeric = 0
            if numeric > 0:
                self.register_port(settings, numeric)
            return

        configured = self._normalise_port(settings.get("listen_port", 6881))
        with self._lock:
            if self._closed:
                return

            active_ports = sorted(self._active_ports)
            if active_ports:
                if self._probe_port and self._probe_port not in self._active_ports:
                    self._pending_maps.pop(self._probe_port, None)
                    self._pending_removals.add(self._probe_port)
                self._probe_port = None
                targets = active_ports
            else:
                if self._probe_port and self._probe_port != configured:
                    self._pending_maps.pop(self._probe_port, None)
                    self._pending_removals.add(self._probe_port)
                self._probe_port = configured
                targets = [configured]

            for port in targets:
                self._pending_removals.discard(port)
                request = self._request_for_port(settings, port)
                self._pending_maps[port] = request
                if port in self._active_ports:
                    self._port_requests[port] = dict(request)
            self._ensure_worker_locked()

    def register_port(self, settings: dict, port: int):
        port = self._normalise_port(port)
        with self._lock:
            if self._closed:
                return

            # A configured-port probe is only for the no-listener state. Once
            # a real TorrentSession owns a listener, keep mappings only for
            # actual active ports.
            if self._probe_port and self._probe_port != port:
                self._pending_maps.pop(self._probe_port, None)
                self._pending_removals.add(self._probe_port)
            self._probe_port = None

            self._active_ports.add(port)
            self._pending_removals.discard(port)
            request = self._request_for_port(settings, port)
            self._port_requests[port] = dict(request)
            self._pending_maps[port] = request
            self._ensure_worker_locked()

    def release_port(self, port: int):
        try:
            port = int(port or 0)
        except (TypeError, ValueError):
            return
        if port <= 0:
            return

        with self._lock:
            if self._closed:
                return
            self._active_ports.discard(port)
            self._port_requests.pop(port, None)
            self._refresh_deadlines.pop(port, None)
            self._pending_maps.pop(port, None)
            self._pending_removals.add(port)
            if self._probe_port == port:
                self._probe_port = None
            self._schedule_renewal_locked()
            self._ensure_worker_locked()

    def mark_incoming(self, port: int, remote_ip: str = ""):
        now = time.time()
        try:
            port = int(port or 0)
        except (TypeError, ValueError):
            port = 0

        with self._lock:
            if port <= 0:
                return
            snap = dict(self._snapshots.get(port) or self._empty_snapshot(port))
            snap["last_incoming_at"] = now
            snap["last_incoming_peer"] = str(remote_ip or "")
            snap["internal_port"] = port
            snap["status"] = "Incoming Confirmed"
            self._snapshots[port] = snap
            self._rebuild_aggregate_locked()

    @classmethod
    def _with_ages(cls, result: dict) -> dict:
        result = cls._decorate_guidance(result)
        last = float(result.get("last_refresh_at") or 0.0)
        result["last_refresh_seconds"] = max(0.0, time.time() - last) if last else None
        incoming = float(result.get("last_incoming_at") or 0.0)
        result["last_incoming_seconds"] = (
            max(0.0, time.time() - incoming) if incoming else None
        )
        return result

    def snapshot(self, port: Optional[int] = None) -> dict:
        with self._lock:
            if port is None:
                result = dict(self._snapshot)
            else:
                try:
                    numeric_port = int(port or 0)
                except (TypeError, ValueError):
                    numeric_port = 0
                result = dict(
                    self._snapshots.get(numeric_port)
                    or self._empty_snapshot(numeric_port)
                )
                result["listener_count"] = 1 if numeric_port in self._active_ports else 0
                result["active_listener_ports"] = (
                    [numeric_port] if numeric_port in self._active_ports else []
                )
                result["mapping_count"] = 1 if numeric_port in self._mappings else 0
                result["mapped_ports"] = (
                    [numeric_port] if numeric_port in self._mappings else []
                )
                deadline = self._refresh_deadlines.get(numeric_port)
                result["next_mapping_refresh_seconds"] = (
                    max(0.0, deadline - time.monotonic()) if deadline else None
                )
            if port is None:
                deadlines = [
                    deadline for mapped_port, deadline in self._refresh_deadlines.items()
                    if mapped_port in self._active_ports
                ]
                result["next_mapping_refresh_seconds"] = (
                    max(0.0, min(deadlines) - time.monotonic()) if deadlines else None
                )
        return self._with_ages(result)

    def close(self):
        with self._lock:
            self._closed = True
            self._renew_generation += 1
            renew_timer = self._renew_timer
            self._renew_timer = None
            self._pending_maps.clear()
            self._pending_removals.clear()
            mappings = list(self._mappings.values())
            self._mappings.clear()
            self._snapshots.clear()
            self._active_ports.clear()
            self._port_requests.clear()
            self._refresh_deadlines.clear()
            self._probe_port = None
            self._snapshot = self._empty_snapshot()

        if renew_timer is not None:
            renew_timer.cancel()

        for mapping in mappings:
            try:
                self._remove_mapping(mapping)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Worker / refresh
    # ------------------------------------------------------------------

    def _ensure_worker_locked(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="SalixConnectivity",
            daemon=True,
        )
        self._worker.start()

    def _schedule_renewal_locked(self):
        """Keep at most one sleeping timer for all active mapping leases."""
        self._renew_generation += 1
        generation = self._renew_generation
        if self._renew_timer is not None:
            self._renew_timer.cancel()
            self._renew_timer = None
        if self._closed:
            return

        deadlines = [
            deadline for port, deadline in self._refresh_deadlines.items()
            if port in self._active_ports and port in self._port_requests
        ]
        if not deadlines:
            return

        delay = max(0.05, min(deadlines) - time.monotonic())
        timer = threading.Timer(delay, self._renew_due_mappings, args=(generation,))
        timer.name = "SalixConnectivityRenew"
        timer.daemon = True
        self._renew_timer = timer
        timer.start()

    def _renew_due_mappings(self, generation: int):
        with self._lock:
            if self._closed or generation != self._renew_generation:
                return
            self._renew_timer = None
            now = time.monotonic()
            due_ports = [
                port for port, deadline in self._refresh_deadlines.items()
                if deadline <= now and port in self._active_ports
            ]
            for port in due_ports:
                self._refresh_deadlines.pop(port, None)
                request = self._port_requests.get(port)
                if request is not None:
                    renewed = dict(request)
                    renewed["renewal"] = True
                    self._pending_maps[port] = renewed
            if due_ports:
                self._ensure_worker_locked()
            self._schedule_renewal_locked()

    def _worker_loop(self):
        while True:
            old_mapping = None
            remove_mapping = None
            request = None
            port = 0

            with self._lock:
                if self._closed:
                    self._worker = None
                    return

                if self._pending_removals:
                    port = self._pending_removals.pop()
                    self._pending_maps.pop(port, None)
                    remove_mapping = self._mappings.pop(port, None)
                    self._refresh_deadlines.pop(port, None)
                    self._snapshots.pop(port, None)
                    self._schedule_renewal_locked()
                    self._rebuild_aggregate_locked()
                elif self._pending_maps:
                    port = next(iter(self._pending_maps))
                    request = self._pending_maps.pop(port)
                    old_mapping = self._mappings.get(port)
                    snap = dict(self._snapshots.get(port) or self._empty_snapshot(port))
                    snap.update(
                        {
                            "status": "Mapping",
                            "internal_port": port,
                            "external_port": 0,
                            "last_error": "",
                        }
                    )
                    self._snapshots[port] = snap
                    self._rebuild_aggregate_locked()
                else:
                    self._worker = None
                    return

            if remove_mapping is not None:
                try:
                    self._remove_mapping(remove_mapping)
                except Exception:
                    pass
                continue

            if request is None:
                continue

            result, mapping = self._perform_refresh(request)
            remove_stale_mapping = None
            with self._lock:
                desired = port in self._active_ports or port == self._probe_port
                if not desired:
                    remove_stale_mapping = mapping or self._mappings.pop(port, None)
                    self._refresh_deadlines.pop(port, None)
                    self._snapshots.pop(port, None)
                    self._schedule_renewal_locked()
                    self._rebuild_aggregate_locked()
                else:
                    current = self._snapshots.get(port) or self._empty_snapshot(port)
                    incoming_at = float(current.get("last_incoming_at") or 0.0)
                    incoming_peer = current.get("last_incoming_peer", "")
                    updated = dict(result)
                    updated["last_incoming_at"] = incoming_at
                    updated["last_incoming_peer"] = incoming_peer
                    if incoming_at:
                        updated["status"] = "Incoming Confirmed"
                    if mapping:
                        self._mappings[port] = mapping
                        lease_seconds = int(mapping.get("lease_seconds", MAPPING_LIFETIME_SECONDS) or 0)
                        if port in self._active_ports and lease_seconds > 0:
                            refresh_after = max(60, int(lease_seconds * 0.80))
                            self._refresh_deadlines[port] = time.monotonic() + refresh_after
                        else:
                            # A UPnP lease duration of zero is permanent until explicitly removed.
                            self._refresh_deadlines.pop(port, None)
                    elif str(result.get("status") or "") == "Disabled":
                        self._mappings.pop(port, None)
                        self._refresh_deadlines.pop(port, None)
                        remove_stale_mapping = old_mapping
                    elif old_mapping is not None:
                        # A lease refresh failure should not destroy a mapping
                        # that may still be valid. Keep it and retry later.
                        self._mappings[port] = old_mapping
                        updated["status"] = "Mapped (refresh failed)"
                        updated["method"] = old_mapping.get("method", "Unknown")
                        updated["external_ip"] = old_mapping.get("external_ip", "")
                        updated["external_port"] = int(old_mapping.get("external_port", 0) or 0)
                        updated["mapped_tcp"] = bool(old_mapping.get("mapped_tcp"))
                        updated["mapped_udp"] = bool(old_mapping.get("mapped_udp"))
                        notice = str(updated.get("last_error") or "").strip()
                        updated["last_error"] = (
                            f"Mapping lease refresh failed; previous mapping retained. {notice}"
                            if notice else "Mapping lease refresh failed; previous mapping retained."
                        )
                        if port in self._active_ports:
                            self._refresh_deadlines[port] = (
                                time.monotonic() + MAPPING_RETRY_SECONDS
                            )
                    else:
                        self._refresh_deadlines.pop(port, None)
                    self._snapshots[port] = updated
                    self._schedule_renewal_locked()
                    self._rebuild_aggregate_locked()

            if remove_stale_mapping is not None:
                try:
                    self._remove_mapping(remove_stale_mapping)
                except Exception:
                    pass

    def _rebuild_aggregate_locked(self):
        target_ports = sorted(self._active_ports)
        if not target_ports and self._probe_port:
            target_ports = [self._probe_port]

        if not target_ports:
            self._snapshot = self._empty_snapshot()
            return

        snapshots = [
            dict(self._snapshots.get(port) or self._empty_snapshot(port))
            for port in target_ports
        ]
        mapped_ports = [port for port in target_ports if port in self._mappings]
        incoming = [s for s in snapshots if float(s.get("last_incoming_at") or 0.0) > 0]

        if incoming:
            status = "Incoming Confirmed"
        elif any(s.get("status") == "Mapping" for s in snapshots):
            status = "Mapping"
        elif mapped_ports and len(mapped_ports) == len(target_ports):
            status = "Mapped"
        elif mapped_ports:
            status = "Partially Mapped"
        elif snapshots and all(s.get("status") == "IPv6 Direct" for s in snapshots):
            status = "IPv6 Direct"
        elif snapshots and all(s.get("status") == "Disabled" for s in snapshots):
            status = "Disabled"
        elif any(s.get("status") == "Unmapped" for s in snapshots):
            status = "Unmapped"
        else:
            status = "Waiting"

        methods = []
        for snap in snapshots:
            method = str(snap.get("method") or "None")
            if method not in {"", "None", "--"} and method not in methods:
                methods.append(method)

        base = max(
            snapshots,
            key=lambda s: max(
                float(s.get("last_incoming_at") or 0.0),
                float(s.get("last_refresh_at") or 0.0),
            ),
        )
        errors = []
        for port, snap in zip(target_ports, snapshots):
            error = str(snap.get("last_error") or "").strip()
            if error:
                labelled = f"{port}: {error}" if len(target_ports) > 1 else error
                if labelled not in errors:
                    errors.append(labelled)

        def aggregate_method_status(field: str) -> str:
            values = []
            for snap in snapshots:
                value = str(snap.get(field) or "Not tried")
                if value not in values:
                    values.append(value)
            return values[0] if len(values) == 1 else "Mixed"

        def aggregate_method_error(field: str) -> str:
            values = []
            for port, snap in zip(target_ports, snapshots):
                value = str(snap.get(field) or "").strip()
                if not value:
                    continue
                labelled = f"{port}: {value}" if len(target_ports) > 1 else value
                if labelled not in values:
                    values.append(labelled)
            return " | ".join(values)

        aggregate = dict(base)
        aggregate.update(
            {
                "status": status,
                "method": " + ".join(methods) if methods else "None",
                "internal_port": target_ports[0] if len(target_ports) == 1 else 0,
                "external_port": int(base.get("external_port") or 0) if len(target_ports) == 1 else 0,
                "mapped_tcp": bool(target_ports) and all(bool(s.get("mapped_tcp")) for s in snapshots),
                "mapped_udp": bool(target_ports) and all(bool(s.get("mapped_udp")) for s in snapshots),
                "last_error": " | ".join(errors),
                "upnp_status": aggregate_method_status("upnp_status"),
                "upnp_stage": aggregate_method_error("upnp_stage"),
                "upnp_code": aggregate_method_error("upnp_code"),
                "upnp_error": aggregate_method_error("upnp_error"),
                "upnp_advice": aggregate_method_error("upnp_advice"),
                "natpmp_status": aggregate_method_status("natpmp_status"),
                "natpmp_stage": aggregate_method_error("natpmp_stage"),
                "natpmp_code": aggregate_method_error("natpmp_code"),
                "natpmp_error": aggregate_method_error("natpmp_error"),
                "natpmp_advice": aggregate_method_error("natpmp_advice"),
                "mapping_count": len(mapped_ports),
                "listener_count": len(self._active_ports),
                "mapped_ports": mapped_ports,
                "active_listener_ports": sorted(self._active_ports),
                "last_refresh_at": max(float(s.get("last_refresh_at") or 0.0) for s in snapshots),
                "mapping_lease_seconds": (
                    snapshots[0].get("mapping_lease_seconds") if len(snapshots) == 1 else None
                ),
                "mapping_permanent": (
                    bool(snapshots) and all(bool(s.get("mapping_permanent")) for s in snapshots)
                ),
            }
        )
        if incoming:
            latest_incoming = max(incoming, key=lambda s: float(s.get("last_incoming_at") or 0.0))
            aggregate["last_incoming_at"] = float(latest_incoming.get("last_incoming_at") or 0.0)
            aggregate["last_incoming_peer"] = latest_incoming.get("last_incoming_peer", "")
        self._snapshot = aggregate

    def _perform_refresh(self, request: dict):
        port = int(request["port"])
        enable_upnp = bool(request["enable_upnp"])
        enable_natpmp = bool(request["enable_natpmp"])
        map_udp = bool(request["map_udp"])
        bind_address = str(request.get("network_bind_address") or "").strip()

        if bool(request.get("ipv6_only")):
            # UPnP IGD and NAT-PMP configure IPv4 NAT. A specifically bound
            # IPv6 listener must not trigger an unrelated IPv4 mapping that
            # would violate Network Interface / VPN binding semantics.
            return ({
                "status": "IPv6 Direct",
                "method": "IPv6",
                "local_ip": bind_address,
                "external_ip": bind_address,
                "internal_port": port,
                "external_port": port,
                "mapped_tcp": False,
                "mapped_udp": False,
                "upnp_status": "Not applicable",
                "upnp_stage": "IPv6 has no IPv4 NAT mapping",
                "upnp_code": "IPV6_DIRECT",
                "upnp_error": "",
                "upnp_advice": "Use firewall rules rather than IPv4 port mapping for IPv6 inbound reachability.",
                "natpmp_status": "Not applicable",
                "natpmp_stage": "IPv6 has no IPv4 NAT mapping",
                "natpmp_code": "IPV6_DIRECT",
                "natpmp_error": "",
                "natpmp_advice": "Use firewall rules rather than IPv4 port mapping for IPv6 inbound reachability.",
                "last_error": "",
                "last_refresh_at": time.time(),
            }, None)

        local_ip = self._local_ip()

        upnp_status = "Disabled" if not enable_upnp else "Not tried"
        natpmp_status = "Disabled" if not enable_natpmp else "Not tried"
        upnp_failure = {"stage": "", "code": "", "error": "", "advice": ""}
        natpmp_failure = {"stage": "", "code": "", "error": "", "advice": ""}

        if not enable_upnp and not enable_natpmp:
            return ({
                "status": "Disabled",
                "method": "None",
                "local_ip": local_ip,
                "external_ip": "",
                "internal_port": port,
                "external_port": 0,
                "mapped_tcp": False,
                "mapped_udp": False,
                "upnp_status": upnp_status,
                "upnp_stage": "Disabled in Preferences",
                "upnp_code": "",
                "upnp_error": "",
                "upnp_advice": "",
                "natpmp_status": natpmp_status,
                "natpmp_stage": "Disabled in Preferences",
                "natpmp_code": "",
                "natpmp_error": "",
                "natpmp_advice": "",
                "last_error": "Automatic port mapping is disabled in Preferences.",
                "last_refresh_at": time.time(),
            }, None)

        if enable_upnp:
            try:
                mapping = self._map_upnp(port, local_ip, map_udp=map_udp)
                if mapping:
                    upnp_status = "Mapped"
                    if enable_natpmp:
                        natpmp_status = "Not needed"
                    result = self._mapping_result(mapping, local_ip)
                    result.update({
                        "upnp_status": upnp_status,
                        "upnp_stage": "Complete",
                        "upnp_code": "",
                        "upnp_error": "",
                        "upnp_advice": "",
                        "natpmp_status": natpmp_status,
                        "natpmp_stage": "Fallback not required" if enable_natpmp else "Disabled in Preferences",
                        "natpmp_code": "",
                        "natpmp_error": "",
                        "natpmp_advice": "",
                    })
                    return result, mapping
                raise PortMappingFailure(
                    "Mapping",
                    "No compatible UPnP mapping was returned.",
                    code="NO_MAPPING",
                    advice="Enable UPnP on the router or use a manual port forward.",
                )
            except Exception as exc:
                upnp_status = "Failed"
                upnp_failure = self._failure_payload(exc)

        if enable_natpmp:
            try:
                mapping = self._map_natpmp(port, map_udp=map_udp)
                if mapping:
                    natpmp_status = "Mapped"
                    result = self._mapping_result(mapping, local_ip)
                    result.update({
                        "upnp_status": upnp_status,
                        "upnp_stage": upnp_failure["stage"],
                        "upnp_code": upnp_failure["code"],
                        "upnp_error": upnp_failure["error"],
                        "upnp_advice": upnp_failure["advice"],
                        "natpmp_status": natpmp_status,
                        "natpmp_stage": "Complete",
                        "natpmp_code": "",
                        "natpmp_error": "",
                        "natpmp_advice": "",
                    })
                    return result, mapping
                raise PortMappingFailure(
                    "Mapping",
                    "No NAT-PMP mapping was returned.",
                    code="NO_MAPPING",
                    advice="Enable NAT-PMP on the router or use a manual port forward.",
                )
            except Exception as exc:
                natpmp_status = "Failed"
                natpmp_failure = self._failure_payload(exc)

        errors = []
        if upnp_failure["error"]:
            errors.append(f"UPnP: {upnp_failure['error']}")
        if natpmp_failure["error"]:
            errors.append(f"NAT-PMP: {natpmp_failure['error']}")

        return ({
            "status": "Unmapped",
            "method": "None",
            "local_ip": local_ip,
            "external_ip": "",
            "internal_port": port,
            "external_port": 0,
            "mapped_tcp": False,
            "mapped_udp": False,
            "upnp_status": upnp_status,
            "upnp_stage": upnp_failure["stage"],
            "upnp_code": upnp_failure["code"],
            "upnp_error": upnp_failure["error"],
            "upnp_advice": upnp_failure["advice"],
            "natpmp_status": natpmp_status,
            "natpmp_stage": natpmp_failure["stage"],
            "natpmp_code": natpmp_failure["code"],
            "natpmp_error": natpmp_failure["error"],
            "natpmp_advice": natpmp_failure["advice"],
            "last_error": " | ".join(errors) or "No compatible router mapping service responded.",
            "last_refresh_at": time.time(),
        }, None)

    @staticmethod
    def _mapping_result(mapping: dict, local_ip: str) -> dict:
        udp_error = str(mapping.get("udp_mapping_error") or "").strip()
        try:
            lease_seconds = int(mapping.get("lease_seconds", MAPPING_LIFETIME_SECONDS))
        except (TypeError, ValueError):
            lease_seconds = MAPPING_LIFETIME_SECONDS
        lease_seconds = max(0, lease_seconds)
        return {
            "status": "Mapped",
            "method": mapping.get("method", "Unknown"),
            "local_ip": local_ip,
            "external_ip": mapping.get("external_ip", ""),
            "internal_port": int(mapping.get("internal_port", 0) or 0),
            "external_port": int(mapping.get("external_port", 0) or 0),
            "mapped_tcp": bool(mapping.get("mapped_tcp")),
            "mapped_udp": bool(mapping.get("mapped_udp")),
            "upnp_status": "Not tried",
            "upnp_stage": "",
            "upnp_code": "",
            "upnp_error": "",
            "upnp_advice": "",
            "natpmp_status": "Not tried",
            "natpmp_stage": "",
            "natpmp_code": "",
            "natpmp_error": "",
            "natpmp_advice": "",
            "udp_mapping_error": udp_error,
            "mapping_lease_seconds": lease_seconds,
            "mapping_permanent": lease_seconds == 0,
            "last_error": (
                f"TCP mapping succeeded, but the optional UDP mapping failed: {udp_error}"
                if udp_error else ""
            ),
            "last_refresh_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _local_ip() -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 53))
            return str(sock.getsockname()[0])
        except OSError:
            try:
                return socket.gethostbyname(socket.gethostname())
            except OSError:
                return "127.0.0.1"
        finally:
            sock.close()

    @staticmethod
    def _default_gateway() -> str:
        if os.name == "nt":
            try:
                output = subprocess.check_output(
                    ["route", "print", "-4", "0.0.0.0"],
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=3,
                )
                for line in output.splitlines():
                    match = re.match(
                        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+",
                        line,
                    )
                    if match and not match.group(1).startswith("0."):
                        return match.group(1)
            except Exception:
                pass

        if os.path.exists("/proc/net/route"):
            try:
                with open("/proc/net/route", "r", encoding="ascii", errors="ignore") as handle:
                    next(handle, None)
                    for line in handle:
                        parts = line.split()
                        if len(parts) >= 3 and parts[1] == "00000000":
                            packed = struct.pack("<L", int(parts[2], 16))
                            return socket.inet_ntoa(packed)
            except Exception:
                pass

        try:
            output = subprocess.check_output(
                ["route", "-n", "get", "default"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=3,
            )
            match = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", output)
            if match:
                return match.group(1)
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # UPnP IGD
    # ------------------------------------------------------------------

    @staticmethod
    def _discover_upnp_locations(timeout: float = 1.4):
        message = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 1\r\n"
            "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
            "\r\n"
        ).encode("ascii")
        locations = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(0.35)
        try:
            sock.sendto(message, SSDP_ADDRESS)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, _addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                text = data.decode("iso-8859-1", errors="ignore")
                for line in text.splitlines():
                    if line.lower().startswith("location:"):
                        location = line.split(":", 1)[1].strip()
                        if location and location not in locations:
                            locations.append(location)
        finally:
            sock.close()
        return locations

    @staticmethod
    def _upnp_control_from_description(location: str) -> Optional[Tuple[str, str]]:
        with urllib.request.urlopen(location, timeout=3.0) as response:
            xml_data = response.read(1024 * 1024)
        root = ET.fromstring(xml_data)
        for service in root.iter():
            if not str(service.tag).endswith("service"):
                continue
            service_type = ""
            control_url = ""
            for child in list(service):
                tag = str(child.tag)
                if tag.endswith("serviceType"):
                    service_type = str(child.text or "").strip()
                elif tag.endswith("controlURL"):
                    control_url = str(child.text or "").strip()
            if (
                ("WANIPConnection" in service_type or "WANPPPConnection" in service_type)
                and control_url
            ):
                return service_type, urllib.parse.urljoin(location, control_url)
        return None

    @staticmethod
    def _soap(control_url: str, service_type: str, action: str, args: dict) -> bytes:
        body_args = "".join(
            f"<New{key}>{value}</New{key}>" for key, value in args.items()
        )
        body = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{service_type}">{body_args}'
            f'</u:{action}></s:Body></s:Envelope>'
        ).encode("utf-8")
        request = urllib.request.Request(
            control_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{service_type}#{action}"',
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=4.0) as response:
                return response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read(256 * 1024).decode("utf-8", errors="ignore")
            except Exception:
                payload = ""
            code_match = re.search(r"<errorCode>\s*([^<]+)\s*</errorCode>", payload)
            description_match = re.search(
                r"<errorDescription>\s*([^<]+)\s*</errorDescription>", payload
            )
            code = code_match.group(1).strip() if code_match else f"HTTP {exc.code}"
            description = (
                description_match.group(1).strip()
                if description_match
                else f"router returned HTTP {exc.code}"
            )
            advice = UPNP_FAULT_ADVICE.get(
                code,
                "Check the router's UPnP settings or use a manual port forward if the failure persists.",
            )
            raise PortMappingFailure(
                f"SOAP {action}",
                description,
                code=code,
                advice=advice,
                technical=f"HTTP {exc.code}: {exc.reason}",
            ) from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc) or exc)
            raise PortMappingFailure(
                f"SOAP {action}",
                f"UPnP gateway request failed: {reason}",
                code="NO_RESPONSE",
                advice="Check that UPnP is enabled on the router and that the selected network/VPN can reach the local gateway.",
                technical=repr(exc),
            ) from exc
        except TimeoutError as exc:
            raise PortMappingFailure(
                f"SOAP {action}",
                "UPnP gateway did not answer before the timeout.",
                code="NO_RESPONSE",
                advice="Check that UPnP is enabled on the router; a manual port forward is an alternative.",
                technical=repr(exc),
            ) from exc

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool) -> Optional[dict]:
        locations = self._discover_upnp_locations()
        if not locations:
            raise PortMappingFailure(
                "Discovery",
                "No UPnP Internet Gateway Device replied to SSDP discovery.",
                code="NO_IGD",
                advice="Enable UPnP on the router, or use NAT-PMP/manual port forwarding instead.",
            )

        last_error = None
        for location in locations:
            try:
                try:
                    control = self._upnp_control_from_description(location)
                except Exception as exc:
                    raise PortMappingFailure(
                        "Device description",
                        f"A UPnP device replied, but its service description could not be read: {exc}",
                        code="DESCRIPTION_FAILED",
                        advice="The router's UPnP service may be incomplete or inaccessible. Try a remap, router UPnP settings, or manual forwarding.",
                        technical=repr(exc),
                    ) from exc
                if not control:
                    last_error = PortMappingFailure(
                        "Device description",
                        "A UPnP device replied but exposed no compatible WANIPConnection/WANPPPConnection service.",
                        code="NO_WAN_SERVICE",
                        advice="The device advertises UPnP but not an Internet-gateway mapping service. NAT-PMP or manual forwarding may still work.",
                    )
                    continue
                service_type, control_url = control

                common = {
                    "RemoteHost": "",
                    "ExternalPort": port,
                    "InternalPort": port,
                    "InternalClient": local_ip,
                    "Enabled": 1,
                    "PortMappingDescription": "SalixTorrent",
                    "LeaseDuration": MAPPING_LIFETIME_SECONDS,
                }
                tcp_args = dict(common)
                tcp_args["Protocol"] = "TCP"
                lease_seconds = MAPPING_LIFETIME_SECONDS
                try:
                    self._soap(control_url, service_type, "AddPortMapping", tcp_args)
                except PortMappingFailure as exc:
                    if exc.code != "725":
                        raise
                    # Some IGD implementations only permit permanent leases. A zero
                    # lease is explicitly allowed by that behaviour and removes the need
                    # for periodic renewal while the process is alive.
                    tcp_args["LeaseDuration"] = 0
                    self._soap(control_url, service_type, "AddPortMapping", tcp_args)
                    common["LeaseDuration"] = 0
                    lease_seconds = 0

                mapped_udp = False
                udp_mapping_error = ""
                if map_udp:
                    try:
                        udp_args = dict(common)
                        udp_args["Protocol"] = "UDP"
                        self._soap(control_url, service_type, "AddPortMapping", udp_args)
                        mapped_udp = True
                    except Exception as exc:
                        udp_mapping_error = str(exc)

                external_ip = ""
                try:
                    payload = self._soap(
                        control_url,
                        service_type,
                        "GetExternalIPAddress",
                        {},
                    )
                    text = payload.decode("utf-8", errors="ignore")
                    match = re.search(
                        r"<NewExternalIPAddress>([^<]+)</NewExternalIPAddress>",
                        text,
                    )
                    if match:
                        candidate = match.group(1).strip()
                        ipaddress.ip_address(candidate)
                        external_ip = candidate
                except Exception:
                    pass

                return {
                    "method": "UPnP",
                    "service_type": service_type,
                    "control_url": control_url,
                    "internal_port": port,
                    "external_port": port,
                    "external_ip": external_ip,
                    "mapped_tcp": True,
                    "mapped_udp": mapped_udp,
                    "udp_mapping_error": udp_mapping_error,
                    "lease_seconds": lease_seconds,
                }
            except Exception as exc:
                last_error = exc

        if last_error:
            raise last_error
        raise PortMappingFailure(
            "Discovery",
            "UPnP devices replied, but none exposed a usable Internet-gateway mapping service.",
            code="NO_WAN_SERVICE",
            advice="Try NAT-PMP or configure a manual port forward on the Internet-facing router.",
        )

    def _remove_mapping(self, mapping: Optional[dict]):
        if not mapping:
            return
        method = mapping.get("method")
        if method == "UPnP":
            control_url = str(mapping.get("control_url") or "")
            service_type = str(mapping.get("service_type") or "")
            port = int(mapping.get("external_port") or 0)
            for protocol, enabled in (
                ("TCP", mapping.get("mapped_tcp")),
                ("UDP", mapping.get("mapped_udp")),
            ):
                if not enabled:
                    continue
                try:
                    self._soap(
                        control_url,
                        service_type,
                        "DeletePortMapping",
                        {"RemoteHost": "", "ExternalPort": port, "Protocol": protocol},
                    )
                except Exception:
                    pass
            return

        if method == "NAT-PMP":
            gateway = str(mapping.get("gateway") or "")
            port = int(mapping.get("internal_port") or 0)
            if gateway and port:
                for opcode, enabled in (
                    (2, mapping.get("mapped_tcp")),
                    (1, mapping.get("mapped_udp")),
                ):
                    if enabled:
                        try:
                            self._natpmp_map_request(gateway, opcode, port, port, 0)
                        except Exception:
                            pass

    # ------------------------------------------------------------------
    # NAT-PMP
    # ------------------------------------------------------------------

    @staticmethod
    def _natpmp_exchange(gateway: str, payload: bytes, timeout: float = 1.2) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(payload, (gateway, NATPMP_PORT))
            response, _ = sock.recvfrom(64)
            return bytes(response)
        finally:
            sock.close()

    @staticmethod
    def _natpmp_result_failure(stage: str, result: int) -> PortMappingFailure:
        description = NATPMP_RESULT_MESSAGES.get(
            int(result), f"gateway returned unknown NAT-PMP result {int(result)}"
        )
        if int(result) == 2:
            advice = "Enable NAT-PMP/port mapping on the gateway or use a manual TCP port forward."
        elif int(result) == 4:
            advice = "The gateway has no mapping resources available; remove stale mappings, try another listen port, or use manual forwarding."
        else:
            advice = "Try UPnP or manual port forwarding if NAT-PMP continues to fail."
        return PortMappingFailure(
            stage,
            f"NAT-PMP {description}.",
            code=str(int(result)),
            advice=advice,
        )

    def _natpmp_public_ip(self, gateway: str) -> str:
        try:
            response = self._natpmp_exchange(gateway, b"\x00\x00")
        except (socket.timeout, TimeoutError) as exc:
            raise PortMappingFailure(
                "Gateway public-address query",
                f"NAT-PMP gateway {gateway} did not respond.",
                code="NO_RESPONSE",
                advice="The router may not support NAT-PMP or the feature may be disabled. UPnP/manual forwarding are alternatives.",
                technical=repr(exc),
            ) from exc
        except OSError as exc:
            raise PortMappingFailure(
                "Gateway public-address query",
                f"NAT-PMP request to gateway {gateway} failed: {exc}",
                code="NETWORK_ERROR",
                advice="Check the active local route/VPN and whether the gateway permits NAT-PMP.",
                technical=repr(exc),
            ) from exc
        if len(response) < 12:
            raise PortMappingFailure(
                "Gateway public-address query",
                "NAT-PMP gateway returned a truncated public-address response.",
                code="SHORT_RESPONSE",
                advice="The gateway's NAT-PMP implementation may be incompatible; try UPnP or manual forwarding.",
            )
        version, opcode, result, _epoch = struct.unpack("!BBHI", response[:8])
        if version != 0 or opcode != 128:
            raise PortMappingFailure(
                "Gateway public-address query",
                "NAT-PMP gateway returned an unexpected protocol response.",
                code="BAD_RESPONSE",
                advice="Try UPnP or manual forwarding; the gateway may not implement NAT-PMP correctly.",
            )
        if result != 0:
            raise self._natpmp_result_failure("Gateway public-address query", result)
        return socket.inet_ntoa(response[8:12])

    def _natpmp_map_request(
        self,
        gateway: str,
        opcode: int,
        internal_port: int,
        external_port: int,
        lifetime: int,
    ) -> Tuple[int, int]:
        payload = struct.pack(
            "!BBHHHI",
            0,
            int(opcode),
            0,
            int(internal_port),
            int(external_port),
            int(lifetime),
        )
        try:
            response = self._natpmp_exchange(gateway, payload)
        except (socket.timeout, TimeoutError) as exc:
            raise PortMappingFailure(
                "Port mapping request",
                f"NAT-PMP gateway {gateway} did not respond to the mapping request.",
                code="NO_RESPONSE",
                advice="The router may not support NAT-PMP or the feature may be disabled. UPnP/manual forwarding are alternatives.",
                technical=repr(exc),
            ) from exc
        except OSError as exc:
            raise PortMappingFailure(
                "Port mapping request",
                f"NAT-PMP mapping request to gateway {gateway} failed: {exc}",
                code="NETWORK_ERROR",
                advice="Check the active route/VPN and gateway settings, or use UPnP/manual forwarding.",
                technical=repr(exc),
            ) from exc
        if len(response) < 16:
            raise PortMappingFailure(
                "Port mapping request",
                "NAT-PMP gateway returned a truncated mapping response.",
                code="SHORT_RESPONSE",
                advice="The gateway's NAT-PMP implementation may be incompatible; try UPnP or manual forwarding.",
            )
        version, response_opcode, result, _epoch, _internal, assigned, actual_life = struct.unpack(
            "!BBHIHHI", response[:16]
        )
        if version != 0 or response_opcode != opcode + 128:
            raise PortMappingFailure(
                "Port mapping request",
                "NAT-PMP gateway returned an unexpected mapping response.",
                code="BAD_RESPONSE",
                advice="Try UPnP or manual forwarding; the gateway may not implement NAT-PMP correctly.",
            )
        if result != 0:
            raise self._natpmp_result_failure("Port mapping request", result)
        return int(assigned), int(actual_life)

    def _map_natpmp(self, port: int, *, map_udp: bool) -> Optional[dict]:
        gateway = self._default_gateway()
        if not gateway:
            raise PortMappingFailure(
                "Gateway detection",
                "No default IPv4 gateway could be determined for NAT-PMP.",
                code="NO_GATEWAY",
                advice="Check the active network/VPN route or use UPnP/manual forwarding.",
            )
        external_ip = self._natpmp_public_ip(gateway)
        external_port, lease_seconds = self._natpmp_map_request(
            gateway,
            2,
            port,
            port,
            MAPPING_LIFETIME_SECONDS,
        )
        mapped_udp = False
        udp_mapping_error = ""
        if map_udp:
            try:
                self._natpmp_map_request(
                    gateway,
                    1,
                    port,
                    external_port,
                    MAPPING_LIFETIME_SECONDS,
                )
                mapped_udp = True
            except Exception as exc:
                udp_mapping_error = str(exc)
        return {
            "method": "NAT-PMP",
            "gateway": gateway,
            "internal_port": port,
            "external_port": external_port,
            "external_ip": external_ip,
            "mapped_tcp": True,
            "mapped_udp": mapped_udp,
            "udp_mapping_error": udp_mapping_error,
            "lease_seconds": lease_seconds or MAPPING_LIFETIME_SECONDS,
        }






