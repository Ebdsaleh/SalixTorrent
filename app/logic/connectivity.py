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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple


SSDP_ADDRESS = ("239.255.255.250", 1900)
NATPMP_PORT = 5351
MAPPING_LIFETIME_SECONDS = 3600


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
        self._pending: Optional[dict] = None
        self._worker: Optional[threading.Thread] = None
        self._mapping: Optional[dict] = None
        self._closed = False
        self._snapshot: Dict[str, object] = {
            "status": "Waiting",
            "method": "None",
            "local_ip": "",
            "external_ip": "",
            "internal_port": 0,
            "external_port": 0,
            "mapped_tcp": False,
            "mapped_udp": False,
            "last_error": "",
            "last_refresh_at": 0.0,
            "last_incoming_at": 0.0,
            "last_incoming_peer": "",
        }

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def request_refresh(self, settings: dict, actual_port: Optional[int] = None):
        try:
            configured = int(actual_port or settings.get("listen_port", 6881) or 6881)
        except (TypeError, ValueError):
            configured = 6881
        configured = max(1, min(65535, configured))

        request = {
            "port": configured,
            "enable_upnp": bool(settings.get("enable_upnp", True)),
            "enable_natpmp": bool(settings.get("enable_natpmp", True)),
            "map_udp": bool(settings.get("enable_dht", True)),
        }

        with self._lock:
            if self._closed:
                return
            self._pending = request
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="SalixConnectivity",
                daemon=True,
            )
            self._worker.start()

    def mark_incoming(self, port: int, remote_ip: str = ""):
        now = time.time()
        try:
            port = int(port or 0)
        except (TypeError, ValueError):
            port = 0
        with self._lock:
            self._snapshot["last_incoming_at"] = now
            self._snapshot["last_incoming_peer"] = str(remote_ip or "")
            if port:
                self._snapshot["internal_port"] = port
                if not self._snapshot.get("external_port"):
                    self._snapshot["external_port"] = port
            self._snapshot["status"] = "Incoming Confirmed"

    def snapshot(self) -> dict:
        with self._lock:
            result = dict(self._snapshot)
        last = float(result.get("last_refresh_at") or 0.0)
        result["last_refresh_seconds"] = max(0.0, time.time() - last) if last else None
        incoming = float(result.get("last_incoming_at") or 0.0)
        result["last_incoming_seconds"] = (
            max(0.0, time.time() - incoming) if incoming else None
        )
        return result

    def close(self):
        with self._lock:
            self._closed = True
            self._pending = None
        try:
            self._remove_mapping(self._mapping)
        except Exception:
            pass
        self._mapping = None

    # ------------------------------------------------------------------
    # Worker / refresh
    # ------------------------------------------------------------------

    def _worker_loop(self):
        while True:
            with self._lock:
                request = self._pending
                self._pending = None
                if request is None or self._closed:
                    self._worker = None
                    return
                self._snapshot.update(
                    {
                        "status": "Mapping",
                        "internal_port": request["port"],
                        "external_port": 0,
                        "last_error": "",
                    }
                )

            result = self._perform_refresh(request)
            with self._lock:
                # A real inbound connection is stronger evidence than a later
                # mapping refresh, so preserve that state while still updating
                # the mapping metadata.
                incoming_at = float(self._snapshot.get("last_incoming_at") or 0.0)
                incoming_peer = self._snapshot.get("last_incoming_peer", "")
                self._snapshot.update(result)
                self._snapshot["last_incoming_at"] = incoming_at
                self._snapshot["last_incoming_peer"] = incoming_peer
                if incoming_at:
                    self._snapshot["status"] = "Incoming Confirmed"

    def _perform_refresh(self, request: dict) -> dict:
        port = int(request["port"])
        enable_upnp = bool(request["enable_upnp"])
        enable_natpmp = bool(request["enable_natpmp"])
        map_udp = bool(request["map_udp"])
        local_ip = self._local_ip()

        old_mapping = self._mapping
        self._mapping = None
        if old_mapping:
            try:
                self._remove_mapping(old_mapping)
            except Exception:
                pass

        if not enable_upnp and not enable_natpmp:
            return {
                "status": "Disabled",
                "method": "None",
                "local_ip": local_ip,
                "external_ip": "",
                "internal_port": port,
                "external_port": 0,
                "mapped_tcp": False,
                "mapped_udp": False,
                "last_error": "Automatic port mapping is disabled in Preferences.",
                "last_refresh_at": time.time(),
            }

        errors = []
        if enable_upnp:
            try:
                mapping = self._map_upnp(port, local_ip, map_udp=map_udp)
                if mapping:
                    self._mapping = mapping
                    return self._mapping_result(mapping, local_ip)
            except Exception as exc:
                errors.append(f"UPnP: {exc}")

        if enable_natpmp:
            try:
                mapping = self._map_natpmp(port, map_udp=map_udp)
                if mapping:
                    self._mapping = mapping
                    return self._mapping_result(mapping, local_ip)
            except Exception as exc:
                errors.append(f"NAT-PMP: {exc}")

        return {
            "status": "Unmapped",
            "method": "None",
            "local_ip": local_ip,
            "external_ip": "",
            "internal_port": port,
            "external_port": 0,
            "mapped_tcp": False,
            "mapped_udp": False,
            "last_error": " | ".join(errors) or "No compatible router mapping service responded.",
            "last_refresh_at": time.time(),
        }

    @staticmethod
    def _mapping_result(mapping: dict, local_ip: str) -> dict:
        return {
            "status": "Mapped",
            "method": mapping.get("method", "Unknown"),
            "local_ip": local_ip,
            "external_ip": mapping.get("external_ip", ""),
            "internal_port": int(mapping.get("internal_port", 0) or 0),
            "external_port": int(mapping.get("external_port", 0) or 0),
            "mapped_tcp": bool(mapping.get("mapped_tcp")),
            "mapped_udp": bool(mapping.get("mapped_udp")),
            "last_error": "",
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
        with urllib.request.urlopen(request, timeout=4.0) as response:
            return response.read(1024 * 1024)

    def _map_upnp(self, port: int, local_ip: str, *, map_udp: bool) -> Optional[dict]:
        locations = self._discover_upnp_locations()
        if not locations:
            raise RuntimeError("no Internet Gateway Device discovered")

        last_error = None
        for location in locations:
            try:
                control = self._upnp_control_from_description(location)
                if not control:
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
                self._soap(control_url, service_type, "AddPortMapping", tcp_args)

                mapped_udp = False
                if map_udp:
                    try:
                        udp_args = dict(common)
                        udp_args["Protocol"] = "UDP"
                        self._soap(control_url, service_type, "AddPortMapping", udp_args)
                        mapped_udp = True
                    except Exception:
                        mapped_udp = False

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
                }
            except Exception as exc:
                last_error = exc

        if last_error:
            raise last_error
        return None

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

    def _natpmp_public_ip(self, gateway: str) -> str:
        response = self._natpmp_exchange(gateway, b"\x00\x00")
        if len(response) < 12:
            raise RuntimeError("short public-address response")
        version, opcode, result, _epoch = struct.unpack("!BBHI", response[:8])
        if version != 0 or opcode != 128 or result != 0:
            raise RuntimeError(f"public-address request failed ({result})")
        return socket.inet_ntoa(response[8:12])

    def _natpmp_map_request(
        self,
        gateway: str,
        opcode: int,
        internal_port: int,
        external_port: int,
        lifetime: int,
    ) -> int:
        payload = struct.pack(
            "!BBHHHI",
            0,
            int(opcode),
            0,
            int(internal_port),
            int(external_port),
            int(lifetime),
        )
        response = self._natpmp_exchange(gateway, payload)
        if len(response) < 16:
            raise RuntimeError("short mapping response")
        version, response_opcode, result, _epoch, _internal, assigned, _life = struct.unpack(
            "!BBHIHHI", response[:16]
        )
        if version != 0 or response_opcode != opcode + 128 or result != 0:
            raise RuntimeError(f"mapping request failed ({result})")
        return int(assigned)

    def _map_natpmp(self, port: int, *, map_udp: bool) -> Optional[dict]:
        gateway = self._default_gateway()
        if not gateway:
            raise RuntimeError("default gateway could not be determined")
        external_ip = self._natpmp_public_ip(gateway)
        external_port = self._natpmp_map_request(
            gateway,
            2,
            port,
            port,
            MAPPING_LIFETIME_SECONDS,
        )
        mapped_udp = False
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
            except Exception:
                mapped_udp = False
        return {
            "method": "NAT-PMP",
            "gateway": gateway,
            "internal_port": port,
            "external_port": external_port,
            "external_ip": external_ip,
            "mapped_tcp": True,
            "mapped_udp": mapped_udp,
        }
