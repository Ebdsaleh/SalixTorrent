"""Generic runtime-network helper regressions."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from app.runtime import network
from app.runtime.network import NetworkInterface


class RuntimeNetworkTests(unittest.TestCase):
    def test_network_interface_exposes_family_and_backend_neutral_label(self):
        v4 = NetworkInterface("Ethernet", "192.0.2.10")
        v6 = NetworkInterface("VPN", "2001:db8::10")
        self.assertEqual(v4.family, socket.AF_INET)
        self.assertEqual(v6.family, socket.AF_INET6)
        self.assertIn("IPv4", v4.label)
        self.assertIn("IPv6", v6.label)

    def test_bind_normalization_treats_wildcards_as_any_interface(self):
        for value in ("", "0.0.0.0", "::", "Any", "Any interface"):
            self.assertEqual(network.normalise_bind_address(value), "")
        self.assertEqual(network.normalise_bind_address("2001:0db8::0001"), "2001:db8::1")

    def test_family_and_wildcard_helpers_are_dual_stack(self):
        self.assertEqual(network.ip_family("192.0.2.1"), socket.AF_INET)
        self.assertEqual(network.ip_family("2001:db8::1"), socket.AF_INET6)
        self.assertEqual(network.ip_family("not-an-ip"), socket.AF_UNSPEC)
        self.assertEqual(network.wildcard_for_family(socket.AF_INET), "0.0.0.0")
        self.assertEqual(network.wildcard_for_family(socket.AF_INET6), "::")

    def test_endpoint_formatting_disambiguates_ipv6(self):
        self.assertEqual(network.format_endpoint("192.0.2.1", 80), "192.0.2.1:80")
        self.assertEqual(network.format_endpoint("2001:db8::1", 443), "[2001:db8::1]:443")
        self.assertEqual(network.format_endpoint("2001:db8::1", 0), "2001:db8::1")

    def test_display_masking_preserves_only_partial_address(self):
        self.assertEqual(network.mask_ip_for_display("192.0.2.10"), "192.0.x.x")
        masked = network.mask_ip_for_display("2001:db8:abcd:1234::5")
        self.assertTrue(masked.startswith("2001:0db8:"))
        self.assertNotIn("1234", masked)
        self.assertEqual(network.mask_ip_for_display("not-an-ip"), "masked")

    def test_dedupe_rejects_unspecified_multicast_and_link_local(self):
        items = [
            NetworkInterface("eth0", "192.0.2.10"),
            NetworkInterface("eth0", "192.0.2.10"),
            NetworkInterface("bad", "0.0.0.0"),
            NetworkInterface("bad", "224.0.0.1"),
            NetworkInterface("bad", "fe80::1"),
            NetworkInterface("lo", "127.0.0.1"),
        ]
        result = network._dedupe(items)
        self.assertEqual(
            [(item.name, item.address) for item in result],
            [("eth0", "192.0.2.10"), ("lo", "127.0.0.1")],
        )

    def test_list_network_interfaces_selects_platform_probe_and_socket_fallback(self):
        windows = [NetworkInterface("win", "192.0.2.2")]
        fallback = [NetworkInterface("fallback", "198.51.100.3")]
        with patch.object(network.os, "name", "nt"), patch.object(
            network, "_windows_interfaces", return_value=windows
        ) as win_probe, patch.object(
            network, "_socket_fallback", return_value=fallback
        ), patch.object(network, "_linux_interfaces") as linux_probe:
            result = network.list_network_interfaces()
        win_probe.assert_called_once_with()
        linux_probe.assert_not_called()
        self.assertEqual({item.address for item in result}, {"192.0.2.2", "198.51.100.3"})

    def test_ipv4_and_ipv6_filtered_views_share_generic_inventory(self):
        values = [
            NetworkInterface("a", "192.0.2.1"),
            NetworkInterface("b", "2001:db8::1"),
        ]
        with patch.object(network, "list_network_interfaces", return_value=values):
            self.assertEqual([i.address for i in network.list_ipv4_interfaces()], ["192.0.2.1"])
            self.assertEqual([i.address for i in network.list_ipv6_interfaces()], ["2001:db8::1"])
            self.assertEqual(network.local_ip_addresses(), {"192.0.2.1", "2001:db8::1"})

    def test_bind_availability_uses_direct_local_socket_bind(self):
        class SocketProbe:
            def __init__(self):
                self.bound = None
                self.closed = False
            def bind(self, endpoint):
                self.bound = endpoint
            def close(self):
                self.closed = True

        probe = SocketProbe()
        with patch.object(network.socket, "socket", return_value=probe):
            self.assertTrue(network.is_bind_address_available("192.0.2.10"))
        self.assertEqual(probe.bound, ("192.0.2.10", 0))
        self.assertTrue(probe.closed)

    def test_any_interface_is_always_available_without_socket_probe(self):
        with patch.object(network.socket, "socket") as socket_factory:
            self.assertTrue(network.is_bind_address_available(""))
        socket_factory.assert_not_called()

    def test_default_route_rejects_loopback_and_accepts_usable_source(self):
        class SocketProbe:
            def __init__(self, address):
                self.address = address
            def connect(self, _endpoint):
                return None
            def getsockname(self):
                return (self.address, 12345)
            def close(self):
                return None

        probes = [SocketProbe("127.0.0.1"), SocketProbe("192.0.2.55")]
        with patch.object(network.socket, "socket", side_effect=probes):
            self.assertEqual(network.default_route_address(socket.AF_INET), "192.0.2.55")

    def test_legacy_network_binding_facade_preserves_identity(self):
        from app.logic import network_binding as legacy

        self.assertIs(legacy.NetworkInterface, network.NetworkInterface)
        self.assertIs(legacy.normalise_bind_address, network.normalise_bind_address)
        self.assertIs(legacy.list_network_interfaces, network.list_network_interfaces)


if __name__ == "__main__":
    unittest.main(verbosity=2)
