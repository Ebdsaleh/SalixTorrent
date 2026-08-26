# app/views/settings_view.py

import os
import time
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.engine.desktop_integration import DesktopIntegration
from app.logic.torrent_manager import TorrentManager
from app.views.help_terms import add_help_tooltip, add_text_tooltip
from app.views.transfer_rate import TRANSFER_RATE_UNITS


RATE_UNITS = ["KB/s", "MB/s", "kbps", "Mbps"]


class SettingsView:
    """Persistent application preferences and connectivity controls."""

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.desktop = DesktopIntegration.get_instance()
        self.settings = self.manager.get_app_settings()
        self._last_connectivity_refresh = 0.0

    def build_view(self, parent_tag):
        with dpg.group(parent=parent_tag):
            preferences_heading = dpg.add_text("PREFERENCES", color=(0, 255, 128))
            add_help_tooltip(preferences_heading, "PREFERENCES_VIEW")
            preferences_intro = dpg.add_text(
                "Network toggles and global limits apply to active sessions immediately. "
                "New-torrent defaults only affect torrents added later.",
                color=(155, 155, 160),
                wrap=1000,
            )
            add_help_tooltip(preferences_intro, "PREFERENCES_VIEW")
            dpg.add_spacer(height=6)

            with dpg.child_window(height=112, border=True):
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
                with dpg.child_window(width=530, height=250, border=True):
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
                        label="Enable DHT (BEP-5)",
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

                with dpg.child_window(width=-1, height=250, border=True):
                    dpg.add_text("INCOMING CONNECTIVITY", color=(0, 255, 128))
                    dpg.add_separator()
                    self.connectivity_status = dpg.add_text("Status: Waiting")
                    add_help_tooltip(self.connectivity_status, "PORT_MAPPING")
                    self.connectivity_method = dpg.add_text("Mapping: --")
                    add_help_tooltip(self.connectivity_method, "PORT_MAPPING")
                    self.connectivity_local = dpg.add_text("Local: --")
                    add_help_tooltip(self.connectivity_local, "LOCAL_ENDPOINT")
                    self.connectivity_external = dpg.add_text("External: --")
                    add_help_tooltip(self.connectivity_external, "EXTERNAL_ENDPOINT")
                    self.connectivity_protocols = dpg.add_text("Mapped protocols: --")
                    add_help_tooltip(self.connectivity_protocols, "MAPPED_PROTOCOLS")
                    self.connectivity_incoming = dpg.add_text("Last incoming peer: --")
                    add_help_tooltip(self.connectivity_incoming, "LAST_INCOMING")
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
                    connectivity_note = dpg.add_text(
                        "'Mapped' means the router accepted a mapping. 'Incoming Confirmed' "
                        "means a real remote peer has reached SalixTorrent.",
                        color=(145, 145, 150),
                        wrap=480,
                    )
                    add_help_tooltip(connectivity_note, "PORT_MAPPING")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=225, border=True):
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

                with dpg.child_window(width=-1, height=225, border=True):
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
                with dpg.child_window(width=530, height=205, border=True):
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

                with dpg.child_window(width=-1, height=225, border=True):
                    dpg.add_text("DESKTOP", color=(0, 255, 128))
                    dpg.add_separator()
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
            "listen_port": int(dpg.get_value(self.listen_port_input) or 6881),
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
            self.listen_port_input: settings["listen_port"],
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
        dpg.set_value(self.connectivity_status, f"Status: {status}")
        dpg.set_value(self.connectivity_method, f"Mapping: {method}")
        dpg.set_value(self.connectivity_local, f"Local: {local_ip}:{internal_port or '--'}")
        dpg.set_value(
            self.connectivity_external,
            f"External: {external_ip}:{external_port or '--'}",
        )
        dpg.set_value(
            self.connectivity_protocols,
            f"Mapped protocols: {' + '.join(protocols) if protocols else '--'}",
        )
        incoming_peer = str(snap.get("last_incoming_peer") or "--")
        incoming_age = self._format_age(snap.get("last_incoming_seconds"))
        dpg.set_value(
            self.connectivity_incoming,
            f"Last incoming peer: {incoming_peer} ({incoming_age})",
        )
        mapping_notice = str(snap.get("last_error") or "")
        if mapping_notice:
            if str(snap.get("status") or "") == "Unmapped":
                mapping_notice = f"Port mapping notice: {mapping_notice}"
            else:
                mapping_notice = f"Connectivity notice: {mapping_notice}"
        dpg.set_value(self.connectivity_error, mapping_notice)

    def _refresh_connectivity(self):
        self.manager.refresh_connectivity()
        dpg.set_value(self.status_text, "Connectivity refresh started")

    def _save(self):
        settings = self.manager.update_app_settings(self._collect())
        self.desktop.configure(settings)
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Preferences saved and applied")
        self._render_connectivity()

    def _restore_defaults(self):
        settings = self.manager.reset_app_settings()
        self.desktop.configure(settings)
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Defaults restored and applied")
        self._render_connectivity()

    def on_show(self, **kwargs):
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


