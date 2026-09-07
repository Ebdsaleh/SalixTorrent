"""Compatibility facade for the generic runtime networking helpers.

New application/runtime code should import :mod:`app.runtime.network`.  This
module remains temporarily so older SalixTorrent call sites and downstream
imports do not break while the engine boundary is still being extracted.
"""

from app.runtime.network import (
    NetworkInterface,
    default_route_address,
    format_endpoint,
    ip_family,
    is_bind_address_available,
    is_ipv4_address,
    is_ipv6_address,
    list_ipv4_interfaces,
    list_ipv6_interfaces,
    list_network_interfaces,
    local_ip_addresses,
    local_ipv4_addresses,
    local_ipv6_addresses,
    mask_ip_for_display,
    normalise_bind_address,
    wildcard_for_family,
)

__all__ = [
    "NetworkInterface",
    "default_route_address",
    "format_endpoint",
    "ip_family",
    "is_bind_address_available",
    "is_ipv4_address",
    "is_ipv6_address",
    "list_ipv4_interfaces",
    "list_ipv6_interfaces",
    "list_network_interfaces",
    "local_ip_addresses",
    "local_ipv4_addresses",
    "local_ipv6_addresses",
    "mask_ip_for_display",
    "normalise_bind_address",
    "wildcard_for_family",
]
