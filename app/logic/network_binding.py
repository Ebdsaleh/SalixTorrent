"""Network-interface discovery and source-binding helpers for SalixTorrent."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    address: str

    @property
    def label(self) -> str:
        name = self.name.strip() or "Interface"
        return f"{name} — {self.address}"


def normalise_bind_address(value: object) -> str:
    text = str(value or "").strip()
    if text in {"", "0.0.0.0", "Any", "Any interface"}:
        return ""
    try:
        packed = socket.inet_aton(text)
        return socket.inet_ntoa(packed)
    except OSError:
        return ""


def _dedupe(items: Iterable[NetworkInterface]) -> List[NetworkInterface]:
    seen = set()
    out: List[NetworkInterface] = []
    for item in items:
        try:
            address = socket.inet_ntoa(socket.inet_aton(item.address))
        except OSError:
            continue
        key = (item.name, address)
        if key in seen:
            continue
        seen.add(key)
        out.append(NetworkInterface(item.name or "Interface", address))
    out.sort(key=lambda item: (item.address.startswith("127."), item.name.lower(), item.address))
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
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped and not line[:1].isspace() and stripped.endswith(":"):
            current = stripped[:-1].strip()
            for prefix in ("Ethernet adapter ", "Wireless LAN adapter ", "Unknown adapter "):
                if current.startswith(prefix):
                    current = current[len(prefix):]
                    break
            continue
        match = ipv4_re.search(stripped)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
    return out


def _linux_interfaces() -> List[NetworkInterface]:
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show"],
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
    pattern = re.compile(r"^\d+:\s+([^\s]+).*?\sinet\s+([0-9]+(?:\.[0-9]+){3})/")
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            out.append(NetworkInterface(match.group(1), match.group(2)))
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
    inet_re = re.compile(r"\binet\s+(?:addr:)?([0-9]+(?:\.[0-9]+){3})")
    for raw in result.stdout.splitlines():
        if raw and not raw[0].isspace():
            current = raw.split(":", 1)[0].strip() or current
        match = inet_re.search(raw)
        if match:
            out.append(NetworkInterface(current, match.group(1)))
    return out


def _socket_fallback() -> List[NetworkInterface]:
    out: List[NetworkInterface] = [NetworkInterface("Loopback", "127.0.0.1")]
    names = {socket.gethostname(), socket.getfqdn()}
    for name in names:
        try:
            for record in socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM):
                out.append(NetworkInterface("Host", str(record[4][0])))
        except OSError:
            pass

    # The address chosen for a route is useful when hostname DNS does not expose
    # every adapter. connect() on UDP does not send application data here.
    for endpoint in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(endpoint)
            addr = sock.getsockname()[0]
            if addr:
                out.append(NetworkInterface("Default route", addr))
        except OSError:
            pass
        finally:
            sock.close()
    return out


def list_ipv4_interfaces() -> List[NetworkInterface]:
    items: List[NetworkInterface] = []
    if os.name == "nt":
        items.extend(_windows_interfaces())
    elif sys.platform.startswith("linux"):
        items.extend(_linux_interfaces())
    else:
        items.extend(_ifconfig_interfaces())
    items.extend(_socket_fallback())
    return _dedupe(items)


def local_ipv4_addresses() -> set[str]:
    return {item.address for item in list_ipv4_interfaces()}


def mask_ip_for_display(value: object) -> str:
    """Return a stable partially masked IP string for UI-only presentation."""
    text = str(value or "?").strip()
    if text in {"", "?"}:
        return text or "?"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return "masked"
    if address.version == 4:
        parts = address.exploded.split(".")
        return f"{parts[0]}.{parts[1]}.x.x"
    groups = address.exploded.split(":")
    return f"{groups[0]}:{groups[1]}:…"


def is_bind_address_available(address: object) -> bool:
    """Return whether IPv4 ``address`` is currently assignable on this host.

    A direct local bind is both cheaper and more authoritative for the kill-switch
    path than repeatedly shelling out to ``ipconfig``/``ip``/``ifconfig``.
    """
    bind = normalise_bind_address(address)
    if not bind:
        return True

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((bind, 0))
        return True
    except OSError:
        return False
    finally:
        sock.close()
