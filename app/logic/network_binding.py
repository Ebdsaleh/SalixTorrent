"""Network-interface discovery and dual-stack source-binding helpers."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    address: str

    @property
    def family(self) -> int:
        return ip_family(self.address)

    @property
    def family_label(self) -> str:
        return "IPv6" if self.family == socket.AF_INET6 else "IPv4"

    @property
    def label(self) -> str:
        name = self.name.strip() or "Interface"
        return f"{name} — {self.address} ({self.family_label})"


def _parse_ip(value: object) -> Optional[ipaddress._BaseAddress]:
    text = str(value or "").strip()
    if not text:
        return None
    # Scoped/link-local addresses are deliberately not offered by interface
    # discovery because a zone index is part of the socket endpoint rather than
    # merely the IP address. Global/ULA IPv6 addresses need no such suffix.
    if "%" in text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def normalise_bind_address(value: object) -> str:
    """Return one canonical local IPv4/IPv6 address, or ``""`` for Any.

    ``0.0.0.0`` and ``::`` are wildcard listener addresses, not interface
    identities, so both intentionally normalize to the application's
    "Any interface" setting.
    """
    text = str(value or "").strip()
    if text.lower() in {
        "",
        "0.0.0.0",
        "::",
        "any",
        "any interface",
        "any interface (system routing)",
    }:
        return ""
    address = _parse_ip(text)
    if address is None or address.is_unspecified:
        return ""
    return address.compressed


def ip_family(value: object) -> int:
    address = _parse_ip(value)
    if address is None:
        return socket.AF_UNSPEC
    return socket.AF_INET6 if address.version == 6 else socket.AF_INET


def is_ipv4_address(value: object) -> bool:
    return ip_family(value) == socket.AF_INET


def is_ipv6_address(value: object) -> bool:
    return ip_family(value) == socket.AF_INET6


def wildcard_for_family(family: int) -> str:
    return "::" if family == socket.AF_INET6 else "0.0.0.0"


def format_endpoint(address: object, port: object) -> str:
    """Format an endpoint without making IPv6 ``address:port`` ambiguous."""
    host = str(address or "?").strip() or "?"
    try:
        port_value = int(port or 0)
    except (TypeError, ValueError):
        port_value = 0
    if port_value <= 0:
        return host
    if is_ipv6_address(host):
        return f"[{host}]:{port_value}"
    return f"{host}:{port_value}"


def _usable_interface_address(value: object) -> str:
    address = _parse_ip(value)
    if address is None:
        return ""
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return ""
    return address.compressed


def _dedupe(items: Iterable[NetworkInterface]) -> List[NetworkInterface]:
    seen = set()
    out: List[NetworkInterface] = []
    for item in items:
        address = _usable_interface_address(item.address)
        if not address:
            continue
        key = (item.name, address)
        if key in seen:
            continue
        seen.add(key)
        out.append(NetworkInterface(item.name or "Interface", address))

    def sort_key(item: NetworkInterface):
        parsed = _parse_ip(item.address)
        loopback = bool(parsed and parsed.is_loopback)
        family_order = 0 if item.family == socket.AF_INET else 1
        return (loopback, item.name.lower(), family_order, item.address)

    out.sort(key=sort_key)
    return out


def _windows_interfaces() -> List[NetworkInterface]:
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return []

    out: List[NetworkInterface] = []
    current = "Windows adapter"
    ipv4_re = re.compile(r"IPv4[^:]*:\s*([0-9]+(?:\.[0-9]+){3})")
    ipv6_re = re.compile(r"(?:Temporary\s+)?IPv6[^:]*:\s*([0-9A-Fa-f:]+(?:%\d+)?)")
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped and not line[:1].isspace() and stripped.endswith(":"):
            current = stripped[:-1].strip()
            for prefix in (
                "Ethernet adapter ",
                "Wireless LAN adapter ",
                "Unknown adapter ",
            ):
                if current.startswith(prefix):
                    current = current[len(prefix):]
                    break
            continue
        match = ipv4_re.search(stripped)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
            continue
        match = ipv6_re.search(stripped)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
    return out


def _linux_interfaces() -> List[NetworkInterface]:
    try:
        result = subprocess.run(
            ["ip", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except Exception:
        return []

    out: List[NetworkInterface] = []
    pattern = re.compile(r"^\d+:\s+([^\s]+).*?\s(inet6?)\s+([^\s/]+)/")
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            out.append(NetworkInterface(match.group(1), match.group(3)))
    return out


def _ifconfig_interfaces() -> List[NetworkInterface]:
    try:
        result = subprocess.run(
            ["ifconfig"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except Exception:
        return []

    out: List[NetworkInterface] = []
    current = "Interface"
    inet4_re = re.compile(r"\binet\s+(?:addr:)?([0-9]+(?:\.[0-9]+){3})")
    inet6_re = re.compile(r"\binet6\s+(?:addr:\s*)?([0-9A-Fa-f:]+(?:%[^\s]+)?)")
    for raw in result.stdout.splitlines():
        if raw and not raw[0].isspace():
            current = raw.split(":", 1)[0].strip() or current
        match = inet4_re.search(raw)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
            continue
        match = inet6_re.search(raw)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
    return out


def _socket_fallback() -> List[NetworkInterface]:
    out: List[NetworkInterface] = [
        NetworkInterface("Loopback", "127.0.0.1"),
        NetworkInterface("Loopback", "::1"),
    ]
    names = {socket.gethostname(), socket.getfqdn()}
    for name in names:
        try:
            for record in socket.getaddrinfo(
                name,
                None,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            ):
                out.append(NetworkInterface("Host", str(record[4][0])))
        except OSError:
            pass

    # The source address chosen for a route is useful when hostname DNS does
    # not expose every adapter. UDP connect() sends no application payload.
    route_probes = (
        (socket.AF_INET, ("8.8.8.8", 53)),
        (socket.AF_INET, ("1.1.1.1", 53)),
        (socket.AF_INET6, ("2001:4860:4860::8888", 53, 0, 0)),
        (socket.AF_INET6, ("2606:4700:4700::1111", 53, 0, 0)),
    )
    for family, endpoint in route_probes:
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
        except OSError:
            continue
        try:
            sock.connect(endpoint)
            addr = sock.getsockname()[0]
            if addr:
                out.append(NetworkInterface("Default route", str(addr)))
        except OSError:
            pass
        finally:
            sock.close()
    return out



def default_route_address(family: int) -> str:
    """Return the source address selected for a representative Internet route.

    UDP ``connect`` performs route selection without sending application data.
    This is especially useful for BEP-32 DHT: the specification recommends a
    stable concrete IPv6 source address rather than ``::`` on multi-homed hosts.
    """
    probes = {
        socket.AF_INET: (("8.8.8.8", 53), ("1.1.1.1", 53)),
        socket.AF_INET6: (
            ("2001:4860:4860::8888", 53, 0, 0),
            ("2606:4700:4700::1111", 53, 0, 0),
        ),
    }.get(family, ())
    for endpoint in probes:
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
        except OSError:
            return ""
        try:
            sock.connect(endpoint)
            candidate = _parse_ip(sock.getsockname()[0])
            if candidate is None or candidate.is_unspecified or candidate.is_loopback:
                continue
            if candidate.is_link_local or candidate.is_multicast:
                continue
            # BEP-32 specifically recommends avoiding Teredo when another
            # native/global route is available. Try the next probe first.
            if family == socket.AF_INET6 and candidate in ipaddress.ip_network("2001::/32"):
                continue
            return candidate.compressed
        except OSError:
            continue
        finally:
            sock.close()
    return ""

def list_network_interfaces() -> List[NetworkInterface]:
    """Return usable local IPv4 and IPv6 interface addresses."""
    items: List[NetworkInterface] = []
    if os.name == "nt":
        items.extend(_windows_interfaces())
    elif sys.platform.startswith("linux"):
        items.extend(_linux_interfaces())
    else:
        items.extend(_ifconfig_interfaces())
    items.extend(_socket_fallback())
    return _dedupe(items)


def list_ipv4_interfaces() -> List[NetworkInterface]:
    """Backward-compatible IPv4-only view used by older callers/tests."""
    return [item for item in list_network_interfaces() if item.family == socket.AF_INET]


def list_ipv6_interfaces() -> List[NetworkInterface]:
    return [item for item in list_network_interfaces() if item.family == socket.AF_INET6]


def local_ip_addresses() -> set[str]:
    return {item.address for item in list_network_interfaces()}


def local_ipv4_addresses() -> set[str]:
    return {item.address for item in list_ipv4_interfaces()}


def local_ipv6_addresses() -> set[str]:
    return {item.address for item in list_ipv6_interfaces()}


def mask_ip_for_display(value: object) -> str:
    """Return a stable partially masked IP string for UI-only presentation."""
    text = str(value or "?").strip()
    if text in {"", "?"}:
        return text or "?"
    address = _parse_ip(text)
    if address is None:
        return "masked"
    if address.version == 4:
        parts = address.exploded.split(".")
        return f"{parts[0]}.{parts[1]}.x.x"
    groups = address.exploded.split(":")
    return f"{groups[0]}:{groups[1]}:…"


def is_bind_address_available(address: object) -> bool:
    """Return whether an IPv4/IPv6 source address is currently bindable.

    A direct local bind is both cheaper and more authoritative for Interface
    Lock than repeatedly shelling out to platform interface commands.
    """
    bind = normalise_bind_address(address)
    if not bind:
        return True
    family = ip_family(bind)
    if family not in {socket.AF_INET, socket.AF_INET6}:
        return False

    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
    except OSError:
        return False
    try:
        if family == socket.AF_INET6:
            sock.bind((bind, 0, 0, 0))
        else:
            sock.bind((bind, 0))
        return True
    except OSError:
        return False
    finally:
        sock.close()
