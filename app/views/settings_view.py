# app/views/settings_view.py

import os
import time
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.engine.desktop_integration import DesktopIntegration
from app.engine.documentation import (
    DOCUMENTATION_SCALE_LABELS,
    DOCUMENTATION_SCALES,
    documentation_scale_from_label,
    documentation_scale_label,
)
from app.engine.responsive_layout import ResponsiveLayout, clamp, split_widths
from app.engine.ui_typography import (
    UI_FONT_LABELS,
    UI_FONT_SIZES,
    UiTypography,
    ui_font_label,
    ui_font_size_from_label,
)
from app.logic.network_binding import (
    format_endpoint,
    list_network_interfaces,
    mask_ip_for_display,
    normalise_bind_address,
)
from app.logic.peer import PEER_ENCRYPTION_POLICIES
from app.logic.torrent_manager import TorrentManager
from app.logic.transfer_add import (
    TORRENT_PROTOCOL_AUTO,
    TORRENT_PROTOCOL_POLICIES,
)
from app.views.help_terms import add_help_tooltip, add_text_tooltip
from app.views.transfer_rate import TRANSFER_RATE_UNITS


RATE_UNITS = ["KB/s", "MB/s", "kbps", "Mbps"]


class SettingsView:
    """Persistent application preferences and connectivity controls."""

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.desktop = DesktopIntegration.get_instance()
        self.typography = UiTypography.get_instance()
        self.settings = self.manager.get_app_settings()
        self._last_connectivity_refresh = 0.0
        self._bind_option_to_address = {}
        self._bind_address_to_option = {}
        self.layout = ResponsiveLayout.get_instance()
        self._layout_root = None

    def build_view(self, parent_tag):
        with dpg.group(parent=parent_tag):
            preferences_heading = dpg.add_text("PREFERENCES", color=(0, 255, 128))
            add_help_tooltip(preferences_heading, "PREFERENCES_VIEW")
            self.preferences_intro = dpg.add_text(
                "Network toggles and global limits apply to active sessions immediately. "
                "New-torrent defaults only affect torrents added later.",
                color=(155, 155, 160),
                wrap=1000,
            )
            add_help_tooltip(self.preferences_intro, "PREFERENCES_VIEW")
            dpg.add_spacer(height=6)

            with dpg.child_window(height=112, width=-1, border=True) as self.downloads_panel:
                dpg.add_text("DOWNLOADS", color=(100, 180, 255))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    download_dir_label = dpg.add_text("Default download directory")
                    add_help_tooltip(download_dir_label, "DEFAULT_DOWNLOAD_DIR")
                    self.download_dir_input = dpg.add_input_text(
                        default_value=self.settings["download_dir"], width=700
                    )
                    add_help_tooltip(self.download_dir_input, "DEFAULT_DOWNLOAD_DIR")
                    choose_download_dir_button = dpg.add_button(label=" Choose Folder ", callback=self._choose_download_dir)
                    add_help_tooltip(choose_download_dir_button, "DEFAULT_DOWNLOAD_DIR")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=290, border=True) as self.networking_panel:
                    dpg.add_text("NETWORKING", color=(255, 200, 100))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        listen_port_label = dpg.add_text("BitTorrent listen port")
                        add_help_tooltip(listen_port_label, "LISTEN_PORT")
                        self.listen_port_input = dpg.add_input_int(
                            default_value=int(self.settings["listen_port"]),
                            min_value=1,
                            max_value=65535,
                            min_clamped=True,
                            max_clamped=True,
                            width=100,
                        )
                        add_help_tooltip(self.listen_port_input, "LISTEN_PORT")
                        fallback_ports = dpg.add_text("Fallback: next 10 ports", color=(140, 140, 145))
                        add_text_tooltip(fallback_ports, "Listen-port fallback\n\nIf the preferred TCP port is already occupied, SalixTorrent tries the next ten port numbers rather than failing the entire torrent subsystem.")

                    with dpg.group(horizontal=True):
                        protocol_label = dpg.add_text("Torrent protocol")
                        add_help_tooltip(protocol_label, "TORRENT_PROTOCOL_POLICY")
                        self.torrent_protocol_combo = dpg.add_combo(
                            items=list(TORRENT_PROTOCOL_POLICIES),
                            default_value=self.settings.get(
                                "torrent_protocol_policy", TORRENT_PROTOCOL_AUTO
                            ),
                            width=220,
                        )
                        add_help_tooltip(self.torrent_protocol_combo, "TORRENT_PROTOCOL_POLICY")

                    with dpg.group(horizontal=True):
                        max_peers_label = dpg.add_text("Default max peers")
                        add_help_tooltip(max_peers_label, "MAX_PEERS")
                        self.max_peers_input = dpg.add_input_int(
                            default_value=int(self.settings["default_max_peers"]),
                            min_value=1,
                            max_value=500,
                            min_clamped=True,
                            max_clamped=True,
                            width=90,
                        )
                        add_help_tooltip(self.max_peers_input, "MAX_PEERS")

                    self.enable_dht_checkbox = dpg.add_checkbox(
                        label="Enable DHT (BEP-5 / BEP-32)",
                        default_value=bool(self.settings["enable_dht"]),
                    )
                    add_help_tooltip(self.enable_dht_checkbox, "DHT")
                    self.enable_pex_checkbox = dpg.add_checkbox(
                        label="Enable Peer Exchange / PEX (BEP-10/11)",
                        default_value=bool(self.settings["enable_pex"]),
                    )
                    add_help_tooltip(self.enable_pex_checkbox, "PEX")
                    self.enable_lan_checkbox = dpg.add_checkbox(
                        label="Enable Local Peer Discovery / LAN (BEP-14)",
                        default_value=bool(self.settings["enable_lan_discovery"]),
                    )
                    add_help_tooltip(self.enable_lan_checkbox, "LPD")
                    with dpg.group(horizontal=True):
                        self.enable_upnp_checkbox = dpg.add_checkbox(
                            label="UPnP port mapping",
                            default_value=bool(self.settings["enable_upnp"]),
                        )
                        add_help_tooltip(self.enable_upnp_checkbox, "UPNP")
                        self.enable_natpmp_checkbox = dpg.add_checkbox(
                            label="NAT-PMP fallback",
                            default_value=bool(self.settings["enable_natpmp"]),
                        )
                        add_help_tooltip(self.enable_natpmp_checkbox, "NATPMP")

                with dpg.child_window(width=-1, height=360, border=True) as self.connectivity_panel:
                    dpg.add_text("INCOMING CONNECTIVITY", color=(0, 255, 128))
                    dpg.add_separator()
                    self.connectivity_status = dpg.add_text("Status: Waiting")
                    add_help_tooltip(self.connectivity_status, "PORT_MAPPING")
                    self.connectivity_method = dpg.add_text("Mapping: --")
                    add_help_tooltip(self.connectivity_method, "PORT_MAPPING")
                    self.connectivity_methods = dpg.add_text("Methods: UPnP -- | NAT-PMP --")
                    add_help_tooltip(self.connectivity_methods, "MAPPING_METHOD_STATUS")
                    self.connectivity_local = dpg.add_text("Local: --")
                    add_help_tooltip(self.connectivity_local, "LOCAL_ENDPOINT")
                    self.connectivity_external = dpg.add_text("External: --")
                    add_help_tooltip(self.connectivity_external, "EXTERNAL_ENDPOINT")
                    self.connectivity_protocols = dpg.add_text("Mapped protocols: --")
                    add_help_tooltip(self.connectivity_protocols, "MAPPED_PROTOCOLS")
                    self.connectivity_incoming = dpg.add_text("Last incoming peer: --")
                    add_help_tooltip(self.connectivity_incoming, "LAST_INCOMING")
                    self.connectivity_refresh_age = dpg.add_text("Last mapping check: --")
                    add_help_tooltip(self.connectivity_refresh_age, "MAPPING_METHOD_STATUS")
                    self.connectivity_next_refresh = dpg.add_text("Next lease refresh: --")
                    add_help_tooltip(self.connectivity_next_refresh, "MAPPING_LEASE")
                    self.connectivity_error = dpg.add_text(
                        "", color=(220, 180, 100), wrap=480
                    )
                    add_help_tooltip(self.connectivity_error, "PORT_MAPPING")
                    dpg.add_spacer(height=6)
                    refresh_connectivity_button = dpg.add_button(
                        label=" Refresh / Remap Now ",
                        callback=self._refresh_connectivity,
                    )
                    add_help_tooltip(refresh_connectivity_button, "PORT_MAPPING")
                    self.connectivity_note = dpg.add_text(
                        "'Mapped' means the router accepted a mapping. 'Incoming Confirmed' "
                        "means a real remote peer has reached SalixTorrent.",
                        color=(145, 145, 150),
                        wrap=480,
                    )
                    add_help_tooltip(self.connectivity_note, "PORT_MAPPING")

            dpg.add_spacer(height=7)
            with dpg.child_window(height=238, width=-1, border=True) as self.privacy_panel:
                dpg.add_text("PRIVACY / TRANSPORT", color=(100, 220, 200))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    encryption_label = dpg.add_text("Peer transport encryption")
                    add_help_tooltip(encryption_label, "MSE")
                    self.peer_encryption_combo = dpg.add_combo(
                        items=list(PEER_ENCRYPTION_POLICIES),
                        default_value=self.settings.get("peer_encryption", "Prefer Encryption"),
                        width=190,
                    )
                    add_help_tooltip(self.peer_encryption_combo, "PEER_ENCRYPTION_POLICY")

                bind_options, selected_bind_option = self._build_network_interface_options(
                    self.settings.get("network_bind_address", "")
                )
                with dpg.group(horizontal=True):
                    bind_label = dpg.add_text("Network interface / VPN")
                    add_help_tooltip(bind_label, "NETWORK_BINDING")
                    self.network_bind_combo = dpg.add_combo(
                        items=bind_options,
                        default_value=selected_bind_option,
                        width=430,
                    )
                    add_help_tooltip(self.network_bind_combo, "NETWORK_BINDING")
                    refresh_interfaces_button = dpg.add_button(
                        label=" Refresh Interfaces ",
                        callback=self._refresh_network_interfaces,
                    )
                    add_help_tooltip(refresh_interfaces_button, "NETWORK_BINDING")

                self.interface_lock_checkbox = dpg.add_checkbox(
                    label="Interface Lock / kill switch (fail closed if the selected address disappears)",
                    default_value=bool(self.settings.get("interface_lock", False)),
                )
                add_help_tooltip(self.interface_lock_checkbox, "INTERFACE_LOCK")
                self.mask_peer_ips_checkbox = dpg.add_checkbox(
                    label="Mask peer IP addresses in the interface",
                    default_value=bool(self.settings.get("mask_peer_ips", False)),
                )
                add_help_tooltip(self.mask_peer_ips_checkbox, "IP_MASKING")
                self.transport_note = dpg.add_text(
                    "Binding chooses one local IPv4 or IPv6 source address for torrent traffic. "
                    "Any interface uses both families when the operating system provides them. Interface Lock "
                    "additionally monitors the selected address and stops torrent networking immediately if it disappears.",
                    color=(145, 145, 150),
                    wrap=1000,
                )
                add_help_tooltip(self.transport_note, "INTERFACE_LOCK")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=225, border=True) as self.queue_preferences_panel:
                    dpg.add_text("QUEUE", color=(180, 160, 255))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        active_slots_label = dpg.add_text("Active download slots")
                        add_help_tooltip(active_slots_label, "ACTIVE_DL_SLOTS")
                        self.active_slots_input = dpg.add_input_int(
                            default_value=int(self.settings["max_active_downloads"]),
                            min_value=0,
                            min_clamped=True,
                            width=90,
                        )
                        add_help_tooltip(self.active_slots_input, "ACTIVE_DL_SLOTS")
                        active_slots_unlimited = dpg.add_text("0 = Unlimited", color=(150, 150, 150))
                        add_help_tooltip(active_slots_unlimited, "ACTIVE_DL_SLOTS")
                    with dpg.group(horizontal=True):
                        default_priority_label = dpg.add_text("Default queue priority")
                        add_help_tooltip(default_priority_label, "QUEUE_PRIORITY")
                        self.default_priority_combo = dpg.add_combo(
                            items=["High", "Normal", "Low"],
                            default_value=self.settings["default_queue_priority"],
                            width=130,
                        )
                        add_help_tooltip(self.default_priority_combo, "QUEUE_PRIORITY")
                    self.auto_resume_checkbox = dpg.add_checkbox(
                        label="Resume torrents that were active when SalixTorrent closed",
                        default_value=bool(self.settings["auto_resume_active"]),
                    )
                    add_help_tooltip(self.auto_resume_checkbox, "AUTO_RESUME")

                with dpg.child_window(width=-1, height=225, border=True) as self.global_bandwidth_panel:
                    dpg.add_text("GLOBAL BANDWIDTH", color=(255, 170, 100))
                    dpg.add_separator()
                    global_bandwidth_note = dpg.add_text(
                        "Aggregate limit shared by every active torrent. 0 = Unlimited.",
                        color=(150, 150, 150),
                    )
                    add_help_tooltip(global_bandwidth_note, "GLOBAL_BANDWIDTH")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Download")
                        self.global_download_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["global_download_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.global_download_limit_unit = dpg.add_combo(
                            items=RATE_UNITS,
                            default_value=self.settings["global_download_limit_unit"],
                            width=90,
                        )
                        add_help_tooltip(self.global_download_limit_input, "GLOBAL_BANDWIDTH")
                        add_help_tooltip(self.global_download_limit_unit, "GLOBAL_BANDWIDTH")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Upload   ")
                        self.global_upload_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["global_upload_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.global_upload_limit_unit = dpg.add_combo(
                            items=RATE_UNITS,
                            default_value=self.settings["global_upload_limit_unit"],
                            width=90,
                        )
                        add_help_tooltip(self.global_upload_limit_input, "GLOBAL_BANDWIDTH")
                        add_help_tooltip(self.global_upload_limit_unit, "GLOBAL_BANDWIDTH")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=205, border=True) as self.new_defaults_panel:
                    dpg.add_text("NEW TORRENT DEFAULTS", color=(100, 180, 255))
                    dpg.add_separator()
                    new_torrent_defaults_note = dpg.add_text("Per-torrent limits assigned when a torrent is added.")
                    add_help_tooltip(new_torrent_defaults_note, "NEW_TORRENT_LIMITS")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Download")
                        self.download_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["default_download_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.download_limit_unit = dpg.add_combo(
                            items=RATE_UNITS,
                            default_value=self.settings["default_download_limit_unit"],
                            width=90,
                        )
                        add_help_tooltip(self.download_limit_input, "NEW_TORRENT_LIMITS")
                        add_help_tooltip(self.download_limit_unit, "NEW_TORRENT_LIMITS")
                    with dpg.group(horizontal=True):
                        dpg.add_text("Upload   ")
                        self.upload_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["default_upload_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.upload_limit_unit = dpg.add_combo(
                            items=RATE_UNITS,
                            default_value=self.settings["default_upload_limit_unit"],
                            width=90,
                        )
                        add_help_tooltip(self.upload_limit_input, "NEW_TORRENT_LIMITS")
                        add_help_tooltip(self.upload_limit_unit, "NEW_TORRENT_LIMITS")

                with dpg.child_window(width=-1, height=292, border=True) as self.desktop_panel:
                    dpg.add_text("DESKTOP", color=(0, 255, 128))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        text_size_label = dpg.add_text("Interface text size")
                        self.ui_font_size_combo = dpg.add_combo(
                            items=[UI_FONT_LABELS[size] for size in UI_FONT_SIZES],
                            default_value=ui_font_label(self.settings.get("ui_font_size", 15)),
                            width=180,
                        )
                        add_help_tooltip(text_size_label, "UI_TEXT_SIZE")
                        add_help_tooltip(self.ui_font_size_combo, "UI_TEXT_SIZE")
                    with dpg.group(horizontal=True):
                        documentation_scale_label_item = dpg.add_text("Documentation scale")
                        self.documentation_scale_combo = dpg.add_combo(
                            items=[DOCUMENTATION_SCALE_LABELS[scale] for scale in DOCUMENTATION_SCALES],
                            default_value=documentation_scale_label(
                                self.settings.get("documentation_scale", 100)
                            ),
                            width=190,
                        )
                        add_help_tooltip(documentation_scale_label_item, "DOCUMENTATION_SCALE")
                        add_help_tooltip(self.documentation_scale_combo, "DOCUMENTATION_SCALE")
                    with dpg.group(horizontal=True):
                        rate_display_label = dpg.add_text("Transfer rate display")
                        self.transfer_rate_display_combo = dpg.add_combo(
                            items=list(TRANSFER_RATE_UNITS),
                            default_value=self.settings.get("transfer_rate_display_unit", "Auto"),
                            width=105,
                        )
                        add_help_tooltip(rate_display_label, "TRANSFER_RATE")
                        add_help_tooltip(self.transfer_rate_display_combo, "TRANSFER_RATE")
                    self.completion_notifications_checkbox = dpg.add_checkbox(
                        label="Show in-app completion notices",
                        default_value=bool(self.settings["completion_notifications"]),
                    )
                    add_help_tooltip(self.completion_notifications_checkbox, "COMPLETION_NOTICE")
                    self.native_notifications_checkbox = dpg.add_checkbox(
                        label="Show native Windows completion notifications (uses tray API)",
                        default_value=bool(self.settings["native_notifications"]),
                    )
                    add_help_tooltip(self.native_notifications_checkbox, "NATIVE_NOTIFICATION")
                    self.system_tray_checkbox = dpg.add_checkbox(
                        label="Enable system tray icon / controls",
                        default_value=bool(self.settings["system_tray_enabled"]),
                    )
                    add_help_tooltip(self.system_tray_checkbox, "SYSTEM_TRAY")
                    self.minimize_to_tray_checkbox = dpg.add_checkbox(
                        label="Minimize to system tray",
                        default_value=bool(self.settings["minimize_to_tray"]),
                    )
                    add_help_tooltip(self.minimize_to_tray_checkbox, "MINIMIZE_TRAY")
                    if not self.desktop.supported:
                        dpg.add_text(
                            "Native tray/notification backend is currently available on Windows.",
                            color=(155, 155, 160),
                        )

            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                save_preferences_button = dpg.add_button(label=" Save Preferences ", callback=self._save)
                add_text_tooltip(save_preferences_button, "Save Preferences\n\nValidates, persists and applies the values shown on this page. Networking toggles and global limits can affect active sessions immediately.")
                restore_defaults_button = dpg.add_button(label=" Restore Defaults ", callback=self._restore_defaults)
                add_text_tooltip(restore_defaults_button, "Restore Defaults\n\nReplaces the current application preferences with SalixTorrent's built-in defaults and applies them. This does not delete torrents or payload data.")
                self.status_text = dpg.add_text("", color=(0, 255, 128))

            dpg.add_spacer(height=7)
            settings_path_text = dpg.add_text(
                f"Settings file: {self.manager.settings_path}",
                color=(130, 130, 135),
            )
            add_help_tooltip(settings_path_text, "SETTINGS_FILE")

        self._layout_root = parent_tag
        self.layout.watch_item(
            parent_tag,
            ("settings_view", "root"),
            self._layout_settings_view,
        )

    def _layout_settings_view(self):
        width, _height = self.layout.item_size(self._layout_root)
        if width <= 1:
            return

        inner_width = max(640, width - 18)
        left_width, right_width = split_widths(
            inner_width,
            (0.48, 0.52),
            minimums=(430, 430),
            gap=8,
        )
        for left, right in (
            (self.networking_panel, self.connectivity_panel),
            (self.queue_preferences_panel, self.global_bandwidth_panel),
            (self.new_defaults_panel, self.desktop_panel),
        ):
            self.layout.width(left, left_width)
            self.layout.width(right, right_width)

        self.layout.width(
            self.download_dir_input,
            clamp(width - 300, 320, 1200),
        )
        self.layout.width(
            self.network_bind_combo,
            clamp(width - 430, 280, 650),
        )

        full_wrap = clamp(width - 42, 560, 1400)
        connectivity_wrap = max(280, right_width - 34)
        self.layout.wrap(self.preferences_intro, full_wrap)
        self.layout.wrap(self.transport_note, full_wrap)
        self.layout.wrap(self.connectivity_error, connectivity_wrap)
        self.layout.wrap(self.connectivity_note, connectivity_wrap)

    def _build_network_interface_options(self, selected_address=""):
        selected_address = normalise_bind_address(selected_address)
        option_to_address = {"Any interface (system routing)": ""}

        for interface in list_network_interfaces():
            address = normalise_bind_address(interface.address)
            if not address:
                continue
            label = interface.label
            if label in option_to_address and option_to_address[label] != address:
                label = f"{label} [{address}]"
            option_to_address[label] = address

        if selected_address and selected_address not in option_to_address.values():
            option_to_address[f"Unavailable — {selected_address}"] = selected_address

        self._bind_option_to_address = option_to_address
        self._bind_address_to_option = {address: label for label, address in option_to_address.items()}
        selected_label = self._bind_address_to_option.get(
            selected_address, "Any interface (system routing)"
        )
        return list(option_to_address), selected_label

    def _refresh_network_interfaces(self):
        selected_label = str(dpg.get_value(self.network_bind_combo) or "")
        selected_address = self._bind_option_to_address.get(selected_label, "")
        options, selected = self._build_network_interface_options(selected_address)
        dpg.configure_item(self.network_bind_combo, items=options)
        dpg.set_value(self.network_bind_combo, selected)
        dpg.set_value(self.status_text, "Network interface list refreshed")

    def _choose_download_dir(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = str(dpg.get_value(self.download_dir_input) or os.getcwd())
        folder = filedialog.askdirectory(
            title="Choose Default Download Directory",
            initialdir=initial if os.path.isdir(initial) else os.getcwd(),
        )
        root.destroy()
        if folder:
            dpg.set_value(self.download_dir_input, os.path.abspath(folder))

    def _collect(self) -> dict:
        return {
            "download_dir": str(dpg.get_value(self.download_dir_input) or "downloads"),
            "default_max_peers": int(dpg.get_value(self.max_peers_input) or 25),
            "max_active_downloads": int(dpg.get_value(self.active_slots_input) or 0),
            "auto_resume_active": bool(dpg.get_value(self.auto_resume_checkbox)),
            "completion_notifications": bool(dpg.get_value(self.completion_notifications_checkbox)),
            "native_notifications": bool(dpg.get_value(self.native_notifications_checkbox)),
            "system_tray_enabled": bool(dpg.get_value(self.system_tray_checkbox)),
            "minimize_to_tray": bool(dpg.get_value(self.minimize_to_tray_checkbox)),
            "transfer_rate_display_unit": str(
                dpg.get_value(self.transfer_rate_display_combo) or "Auto"
            ),
            "ui_font_size": ui_font_size_from_label(
                dpg.get_value(self.ui_font_size_combo)
            ),
            "documentation_scale": documentation_scale_from_label(
                dpg.get_value(self.documentation_scale_combo)
            ),
            "listen_port": int(dpg.get_value(self.listen_port_input) or 6881),
            "peer_encryption": str(
                dpg.get_value(self.peer_encryption_combo) or "Prefer Encryption"
            ),
            "torrent_protocol_policy": str(
                dpg.get_value(self.torrent_protocol_combo) or TORRENT_PROTOCOL_AUTO
            ),
            "network_bind_address": self._bind_option_to_address.get(
                str(dpg.get_value(self.network_bind_combo) or ""), ""
            ),
            "interface_lock": bool(dpg.get_value(self.interface_lock_checkbox)),
            "mask_peer_ips": bool(dpg.get_value(self.mask_peer_ips_checkbox)),
            "enable_dht": bool(dpg.get_value(self.enable_dht_checkbox)),
            "enable_pex": bool(dpg.get_value(self.enable_pex_checkbox)),
            "enable_lan_discovery": bool(dpg.get_value(self.enable_lan_checkbox)),
            "enable_upnp": bool(dpg.get_value(self.enable_upnp_checkbox)),
            "enable_natpmp": bool(dpg.get_value(self.enable_natpmp_checkbox)),
            "global_download_limit_value": float(dpg.get_value(self.global_download_limit_input) or 0.0),
            "global_download_limit_unit": str(dpg.get_value(self.global_download_limit_unit) or "KB/s"),
            "global_upload_limit_value": float(dpg.get_value(self.global_upload_limit_input) or 0.0),
            "global_upload_limit_unit": str(dpg.get_value(self.global_upload_limit_unit) or "KB/s"),
            "default_download_limit_value": float(dpg.get_value(self.download_limit_input) or 0.0),
            "default_download_limit_unit": str(dpg.get_value(self.download_limit_unit) or "KB/s"),
            "default_upload_limit_value": float(dpg.get_value(self.upload_limit_input) or 0.0),
            "default_upload_limit_unit": str(dpg.get_value(self.upload_limit_unit) or "KB/s"),
            "default_queue_priority": str(dpg.get_value(self.default_priority_combo) or "Normal"),
        }

    def _sync_controls(self, settings: dict):
        self.settings = dict(settings)
        bind_options, bind_selected = self._build_network_interface_options(
            settings.get("network_bind_address", "")
        )
        if hasattr(self, "network_bind_combo") and dpg.does_item_exist(self.network_bind_combo):
            dpg.configure_item(self.network_bind_combo, items=bind_options)

        values = {
            self.download_dir_input: settings["download_dir"],
            self.max_peers_input: settings["default_max_peers"],
            self.active_slots_input: settings["max_active_downloads"],
            self.auto_resume_checkbox: settings["auto_resume_active"],
            self.completion_notifications_checkbox: settings["completion_notifications"],
            self.native_notifications_checkbox: settings["native_notifications"],
            self.system_tray_checkbox: settings["system_tray_enabled"],
            self.minimize_to_tray_checkbox: settings["minimize_to_tray"],
            self.transfer_rate_display_combo: settings.get("transfer_rate_display_unit", "Auto"),
            self.ui_font_size_combo: ui_font_label(settings.get("ui_font_size", 15)),
            self.documentation_scale_combo: documentation_scale_label(
                settings.get("documentation_scale", 100)
            ),
            self.listen_port_input: settings["listen_port"],
            self.peer_encryption_combo: settings.get("peer_encryption", "Prefer Encryption"),
            self.torrent_protocol_combo: settings.get(
                "torrent_protocol_policy", TORRENT_PROTOCOL_AUTO
            ),
            self.network_bind_combo: bind_selected,
            self.interface_lock_checkbox: settings.get("interface_lock", False),
            self.mask_peer_ips_checkbox: settings.get("mask_peer_ips", False),
            self.enable_dht_checkbox: settings["enable_dht"],
            self.enable_pex_checkbox: settings["enable_pex"],
            self.enable_lan_checkbox: settings["enable_lan_discovery"],
            self.enable_upnp_checkbox: settings["enable_upnp"],
            self.enable_natpmp_checkbox: settings["enable_natpmp"],
            self.global_download_limit_input: settings["global_download_limit_value"],
            self.global_download_limit_unit: settings["global_download_limit_unit"],
            self.global_upload_limit_input: settings["global_upload_limit_value"],
            self.global_upload_limit_unit: settings["global_upload_limit_unit"],
            self.download_limit_input: settings["default_download_limit_value"],
            self.download_limit_unit: settings["default_download_limit_unit"],
            self.upload_limit_input: settings["default_upload_limit_value"],
            self.upload_limit_unit: settings["default_upload_limit_unit"],
            self.default_priority_combo: settings["default_queue_priority"],
        }
        for item, value in values.items():
            dpg.set_value(item, value)

    @staticmethod
    def _format_duration(seconds):
        if seconds is None:
            return "--"
        try:
            total = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "--"
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    @staticmethod
    def _format_age(seconds):
        if seconds is None:
            return "--"
        try:
            seconds = max(0, int(seconds))
        except (TypeError, ValueError):
            return "--"
        if seconds < 60:
            return f"{seconds}s ago"
        return f"{seconds // 60}m {seconds % 60}s ago"

    def _render_connectivity(self):
        snap = self.manager.get_connectivity_snapshot()
        status = str(snap.get("status") or "Waiting")
        method = str(snap.get("method") or "None")
        local_ip = str(snap.get("local_ip") or "--")
        external_ip = str(snap.get("external_ip") or "--")
        internal_port = int(snap.get("internal_port") or 0)
        external_port = int(snap.get("external_port") or 0)
        protocols = []
        if snap.get("mapped_tcp"):
            protocols.append("TCP")
        if snap.get("mapped_udp"):
            protocols.append("UDP")
        listener_ports = [int(p) for p in snap.get("active_listener_ports", []) if p]
        mapped_ports = [int(p) for p in snap.get("mapped_ports", []) if p]
        mapping_count = int(snap.get("mapping_count") or 0)
        listener_count = int(snap.get("listener_count") or 0)

        ipv6_direct = status == "IPv6 Direct"
        if listener_count > 1:
            if ipv6_direct:
                status = f"IPv6 Direct ({listener_count} active listener ports; IPv4 NAT mapping not applicable)"
            else:
                status = f"{status} ({mapping_count}/{listener_count} listener ports mapped)"
            local_value = f"Local: {local_ip} | ports {', '.join(str(p) for p in listener_ports)}"
            if external_ip not in {"", "--"}:
                external_scope = str(snap.get("external_scope") or "Unknown")
                scope_suffix = f" ({external_scope})" if external_scope != "Unknown" else ""
                external_value = f"External: {external_ip}{scope_suffix} | mapped ports {', '.join(str(p) for p in mapped_ports) or '--'}"
            else:
                external_value = (
                    "External: IPv6 route/firewall dependent; no IPv4 NAT mapping"
                    if ipv6_direct
                    else f"External mapped ports: {', '.join(str(p) for p in mapped_ports) or '--'}"
                )
        else:
            local_value = f"Local: {format_endpoint(local_ip, internal_port) if internal_port else local_ip}"
            external_scope = str(snap.get("external_scope") or "Unknown")
            scope_suffix = f" ({external_scope})" if external_ip not in {"", "--"} and external_scope != "Unknown" else ""
            if external_ip not in {"", "--"}:
                external_value = f"External: {format_endpoint(external_ip, external_port)}{scope_suffix}"
            elif ipv6_direct:
                external_value = "External: IPv6 route/firewall dependent; no IPv4 NAT mapping"
            else:
                external_value = "External: --"

        dpg.set_value(self.connectivity_status, f"Status: {status}")
        dpg.set_value(self.connectivity_method, f"Mapping: {method}")
        dpg.set_value(
            self.connectivity_methods,
            f"Methods: UPnP {snap.get('upnp_status', '--')} | "
            f"NAT-PMP {snap.get('natpmp_status', '--')}",
        )
        dpg.set_value(self.connectivity_local, local_value)
        dpg.set_value(self.connectivity_external, external_value)
        dpg.set_value(
            self.connectivity_protocols,
            f"Mapped protocols: {' + '.join(protocols) if protocols else ('not applicable to IPv6 direct' if ipv6_direct else '--')}",
        )
        incoming_peer = str(snap.get("last_incoming_peer") or "--")
        if self.settings.get("mask_peer_ips") and incoming_peer not in {"", "--"}:
            incoming_peer = mask_ip_for_display(incoming_peer)
        incoming_age = self._format_age(snap.get("last_incoming_seconds"))
        dpg.set_value(
            self.connectivity_incoming,
            f"Last incoming peer: {incoming_peer} ({incoming_age})",
        )
        dpg.set_value(
            self.connectivity_refresh_age,
            f"Last mapping check: {self._format_age(snap.get('last_refresh_seconds'))}",
        )
        next_refresh = snap.get("next_mapping_refresh_seconds")
        if snap.get("mapping_permanent") and int(snap.get("mapping_count") or 0) > 0:
            next_refresh_text = "not required (permanent lease)"
        else:
            next_refresh_text = (
                f"in {self._format_duration(next_refresh)}"
                if next_refresh is not None else "--"
            )
        dpg.set_value(
            self.connectivity_next_refresh,
            f"Next lease refresh: {next_refresh_text}",
        )
        details = []
        upnp_summary = str(snap.get("upnp_summary") or "").strip()
        natpmp_summary = str(snap.get("natpmp_summary") or "").strip()
        if upnp_summary:
            details.append(upnp_summary)
        if natpmp_summary:
            details.append(natpmp_summary)
        diagnosis = str(snap.get("diagnosis") or "").strip()
        if diagnosis:
            details.append(f"Diagnosis: {diagnosis}")
        action_hint = str(snap.get("action_hint") or "").strip()
        if action_hint:
            details.append(f"Suggested action: {action_hint}")
        mapping_notice = "\n".join(details)
        dpg.set_value(self.connectivity_error, mapping_notice)
        if status == "Incoming Confirmed":
            notice_color = (0, 220, 128)
        elif status.startswith("Mapped"):
            notice_color = (100, 180, 255)
        elif status == "Unmapped":
            notice_color = (255, 200, 100)
        else:
            notice_color = (170, 170, 175)
        dpg.configure_item(self.connectivity_error, color=notice_color)

    def _refresh_connectivity(self):
        self.manager.refresh_connectivity()
        dpg.set_value(self.status_text, "Connectivity refresh started")

    def _save(self):
        settings = self.manager.update_app_settings(self._collect())
        self.desktop.configure(settings)
        self.typography.apply_font_size(settings.get("ui_font_size", 15))
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Preferences saved and applied")
        self._render_connectivity()

    def _restore_defaults(self):
        settings = self.manager.reset_app_settings()
        self.desktop.configure(settings)
        self.typography.apply_font_size(settings.get("ui_font_size", 15))
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Defaults restored and applied")
        self._render_connectivity()

    def on_show(self, **kwargs):
        self.layout.trigger(("settings_view", "root"))
        settings = self.manager.get_app_settings()
        settings["max_active_downloads"] = self.manager.get_max_active_downloads()
        self._sync_controls(settings)
        self._render_connectivity()
        self._last_connectivity_refresh = time.monotonic()
        dpg.set_value(self.status_text, "")

    def update(self, delta_time: float):
        del delta_time
        now = time.monotonic()
        if now - self._last_connectivity_refresh >= 1.0:
            self._last_connectivity_refresh = now
            self._render_connectivity()




