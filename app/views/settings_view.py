# app/views/settings_view.py

import os
import time
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.engine.desktop_integration import DesktopIntegration
from app.engine.components import (
    DurationEditor,
    LabeledComboField,
    LabeledNumericField,
    NumericKind,
)
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
from app.localization import (
    LANGUAGE_OPTION_LABELS,
    locale_code_from_label,
    locale_label,
    localization_manager,
    tr,
    tr_value,
    localized_choices,
    canonical_choice,
)
from app.logic.network_binding import (
    format_endpoint,
    list_network_interfaces,
    mask_ip_for_display,
    normalise_bind_address,
)
from app.logic.peer import PEER_ENCRYPTION_POLICIES
from app.logic.seeding_policy import (
    SEEDING_GOAL_MODES,
    seeding_time_parts_from_minutes,
    seeding_time_parts_to_minutes,
)
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
        self.localization = localization_manager()
        self._layout_root = None

    def build_view(self, parent_tag):
        with dpg.group(parent=parent_tag):
            preferences_heading = dpg.add_text(tr("settings.heading", "PREFERENCES"), color=(0, 255, 128))
            add_help_tooltip(preferences_heading, "PREFERENCES_VIEW")
            self.preferences_intro = dpg.add_text(
                tr(
                    "settings.intro",
                    "Network toggles and global limits apply to active sessions immediately. "
                    "New-torrent defaults only affect torrents added later.",
                ),
                color=(155, 155, 160),
                wrap=1000,
            )
            add_help_tooltip(self.preferences_intro, "PREFERENCES_VIEW")
            dpg.add_spacer(height=6)

            with dpg.child_window(height=112, width=-1, border=True) as self.downloads_panel:
                dpg.add_text(tr('view.settings_view.downloads', "DOWNLOADS"), color=(100, 180, 255))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    download_dir_label = dpg.add_text(tr("settings.default_download_directory", "Default download directory"))
                    add_help_tooltip(download_dir_label, "DEFAULT_DOWNLOAD_DIR")
                    self.download_dir_input = dpg.add_input_text(
                        default_value=self.settings["download_dir"], width=700
                    )
                    add_help_tooltip(self.download_dir_input, "DEFAULT_DOWNLOAD_DIR")
                    choose_download_dir_button = dpg.add_button(label=tr("settings.choose_folder", " Choose Folder "), callback=self._choose_download_dir)
                    add_help_tooltip(choose_download_dir_button, "DEFAULT_DOWNLOAD_DIR")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=290, border=True) as self.networking_panel:
                    dpg.add_text(tr('view.settings_view.networking', "NETWORKING"), color=(255, 200, 100))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        listen_port_label = dpg.add_text(tr('view.settings_view.bittorrent_listen_port', "BitTorrent listen port"))
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
                        fallback_ports = dpg.add_text(tr('view.settings_view.fallback_next_10_ports', "Fallback: next 10 ports"), color=(140, 140, 145))
                        add_text_tooltip(fallback_ports, tr('view.settings_view.listen_port_fallback_if_the_preferred_tcp', "Listen-port fallback\n\nIf the preferred TCP port is already occupied, SalixTorrent tries the next ten port numbers rather than failing the entire torrent subsystem."))

                    with dpg.group(horizontal=True):
                        protocol_label = dpg.add_text(tr('view.settings_view.torrent_protocol', "Torrent protocol"))
                        add_help_tooltip(protocol_label, "TORRENT_PROTOCOL_POLICY")
                        self.torrent_protocol_combo = dpg.add_combo(
                            items=localized_choices(TORRENT_PROTOCOL_POLICIES),
                            default_value=tr_value(self.settings.get(
                                "torrent_protocol_policy", TORRENT_PROTOCOL_AUTO
                            )),
                            width=220,
                        )
                        add_help_tooltip(self.torrent_protocol_combo, "TORRENT_PROTOCOL_POLICY")

                    with dpg.group(horizontal=True):
                        max_peers_label = dpg.add_text(tr('view.settings_view.default_max_peers', "Default max peers"))
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
                        label=tr('view.settings_view.enable_dht_bep_5_bep_32', "Enable DHT (BEP-5 / BEP-32)"),
                        default_value=bool(self.settings["enable_dht"]),
                    )
                    add_help_tooltip(self.enable_dht_checkbox, "DHT")
                    self.enable_pex_checkbox = dpg.add_checkbox(
                        label=tr('view.settings_view.enable_peer_exchange_pex_bep_10_11', "Enable Peer Exchange / PEX (BEP-10/11)"),
                        default_value=bool(self.settings["enable_pex"]),
                    )
                    add_help_tooltip(self.enable_pex_checkbox, "PEX")
                    self.enable_lan_checkbox = dpg.add_checkbox(
                        label=tr('view.settings_view.enable_local_peer_discovery_lan_bep_14', "Enable Local Peer Discovery / LAN (BEP-14)"),
                        default_value=bool(self.settings["enable_lan_discovery"]),
                    )
                    add_help_tooltip(self.enable_lan_checkbox, "LPD")
                    with dpg.group(horizontal=True):
                        self.enable_upnp_checkbox = dpg.add_checkbox(
                            label=tr('view.settings_view.upnp_port_mapping', "UPnP port mapping"),
                            default_value=bool(self.settings["enable_upnp"]),
                        )
                        add_help_tooltip(self.enable_upnp_checkbox, "UPNP")
                        self.enable_natpmp_checkbox = dpg.add_checkbox(
                            label=tr('view.settings_view.nat_pmp_fallback', "NAT-PMP fallback"),
                            default_value=bool(self.settings["enable_natpmp"]),
                        )
                        add_help_tooltip(self.enable_natpmp_checkbox, "NATPMP")

                with dpg.child_window(width=-1, height=360, border=True) as self.connectivity_panel:
                    dpg.add_text(tr('view.settings_view.incoming_connectivity', "INCOMING CONNECTIVITY"), color=(0, 255, 128))
                    dpg.add_separator()
                    self.connectivity_status = dpg.add_text(tr('view.settings_view.status_waiting', "Status: Waiting"))
                    add_help_tooltip(self.connectivity_status, "PORT_MAPPING")
                    self.connectivity_method = dpg.add_text(tr('view.settings_view.mapping', "Mapping: --"))
                    add_help_tooltip(self.connectivity_method, "PORT_MAPPING")
                    self.connectivity_methods = dpg.add_text(tr('view.settings_view.methods_upnp_nat_pmp', "Methods: UPnP -- | NAT-PMP --"))
                    add_help_tooltip(self.connectivity_methods, "MAPPING_METHOD_STATUS")
                    self.connectivity_local = dpg.add_text(tr('view.settings_view.local', "Local: --"))
                    add_help_tooltip(self.connectivity_local, "LOCAL_ENDPOINT")
                    self.connectivity_external = dpg.add_text(tr('view.settings_view.external', "External: --"))
                    add_help_tooltip(self.connectivity_external, "EXTERNAL_ENDPOINT")
                    self.connectivity_protocols = dpg.add_text(tr('view.settings_view.mapped_protocols', "Mapped protocols: --"))
                    add_help_tooltip(self.connectivity_protocols, "MAPPED_PROTOCOLS")
                    self.connectivity_incoming = dpg.add_text(tr('view.settings_view.last_incoming_peer', "Last incoming peer: --"))
                    add_help_tooltip(self.connectivity_incoming, "LAST_INCOMING")
                    self.connectivity_refresh_age = dpg.add_text(tr('view.settings_view.last_mapping_check', "Last mapping check: --"))
                    add_help_tooltip(self.connectivity_refresh_age, "MAPPING_METHOD_STATUS")
                    self.connectivity_next_refresh = dpg.add_text(tr('view.settings_view.next_lease_refresh', "Next lease refresh: --"))
                    add_help_tooltip(self.connectivity_next_refresh, "MAPPING_LEASE")
                    self.connectivity_error = dpg.add_text(
                        "", color=(220, 180, 100), wrap=480
                    )
                    add_help_tooltip(self.connectivity_error, "PORT_MAPPING")
                    dpg.add_spacer(height=6)
                    refresh_connectivity_button = dpg.add_button(
                        label=tr('view.settings_view.refresh_remap_now', " Refresh / Remap Now "),
                        callback=self._refresh_connectivity,
                    )
                    add_help_tooltip(refresh_connectivity_button, "PORT_MAPPING")
                    self.connectivity_note = dpg.add_text(
                        tr('view.settings_view.mapped_means_the_router_accepted_a_mapping', "'Mapped' means the router accepted a mapping. 'Incoming Confirmed' "
                        "means a real remote peer has reached SalixTorrent."),
                        color=(145, 145, 150),
                        wrap=480,
                    )
                    add_help_tooltip(self.connectivity_note, "PORT_MAPPING")

            dpg.add_spacer(height=7)
            with dpg.child_window(height=238, width=-1, border=True) as self.privacy_panel:
                dpg.add_text(tr('view.settings_view.privacy_transport', "PRIVACY / TRANSPORT"), color=(100, 220, 200))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    encryption_label = dpg.add_text(tr('view.settings_view.peer_transport_encryption', "Peer transport encryption"))
                    add_help_tooltip(encryption_label, "MSE")
                    self.peer_encryption_combo = dpg.add_combo(
                        items=localized_choices(PEER_ENCRYPTION_POLICIES),
                        default_value=tr_value(self.settings.get("peer_encryption", "Prefer Encryption")),
                        width=190,
                    )
                    add_help_tooltip(self.peer_encryption_combo, "PEER_ENCRYPTION_POLICY")

                bind_options, selected_bind_option = self._build_network_interface_options(
                    self.settings.get("network_bind_address", "")
                )
                with dpg.group(horizontal=True):
                    bind_label = dpg.add_text(tr('view.settings_view.network_interface_vpn', "Network interface / VPN"))
                    add_help_tooltip(bind_label, "NETWORK_BINDING")
                    self.network_bind_combo = dpg.add_combo(
                        items=bind_options,
                        default_value=selected_bind_option,
                        width=430,
                    )
                    add_help_tooltip(self.network_bind_combo, "NETWORK_BINDING")
                    refresh_interfaces_button = dpg.add_button(
                        label=tr('view.settings_view.refresh_interfaces', " Refresh Interfaces "),
                        callback=self._refresh_network_interfaces,
                    )
                    add_help_tooltip(refresh_interfaces_button, "NETWORK_BINDING")

                self.interface_lock_checkbox = dpg.add_checkbox(
                    label=tr('view.settings_view.interface_lock_kill_switch_fail_closed_if', "Interface Lock / kill switch (fail closed if the selected address disappears)"),
                    default_value=bool(self.settings.get("interface_lock", False)),
                )
                add_help_tooltip(self.interface_lock_checkbox, "INTERFACE_LOCK")
                self.mask_peer_ips_checkbox = dpg.add_checkbox(
                    label=tr('view.settings_view.mask_peer_ip_addresses_in_the_interface', "Mask peer IP addresses in the interface"),
                    default_value=bool(self.settings.get("mask_peer_ips", False)),
                )
                add_help_tooltip(self.mask_peer_ips_checkbox, "IP_MASKING")
                self.transport_note = dpg.add_text(
                    tr('view.settings_view.binding_chooses_one_local_ipv4_or_ipv6', "Binding chooses one local IPv4 or IPv6 source address for torrent traffic. "
                    "Any interface uses both families when the operating system provides them. Interface Lock "
                    "additionally monitors the selected address and stops torrent networking immediately if it disappears."),
                    color=(145, 145, 150),
                    wrap=1000,
                )
                add_help_tooltip(self.transport_note, "INTERFACE_LOCK")

            dpg.add_spacer(height=7)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=530, height=225, border=True) as self.queue_preferences_panel:
                    dpg.add_text(tr('view.settings_view.queue', "QUEUE"), color=(180, 160, 255))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        active_slots_label = dpg.add_text(tr('view.settings_view.active_download_slots', "Active download slots"))
                        add_help_tooltip(active_slots_label, "ACTIVE_DL_SLOTS")
                        self.active_slots_input = dpg.add_input_int(
                            default_value=int(self.settings["max_active_downloads"]),
                            min_value=0,
                            min_clamped=True,
                            width=90,
                        )
                        add_help_tooltip(self.active_slots_input, "ACTIVE_DL_SLOTS")
                        active_slots_unlimited = dpg.add_text(tr('view.settings_view.0_unlimited', "0 = Unlimited"), color=(150, 150, 150))
                        add_help_tooltip(active_slots_unlimited, "ACTIVE_DL_SLOTS")
                    with dpg.group(horizontal=True):
                        default_priority_label = dpg.add_text(tr('view.settings_view.default_queue_priority', "Default queue priority"))
                        add_help_tooltip(default_priority_label, "QUEUE_PRIORITY")
                        self.default_priority_combo = dpg.add_combo(
                            items=localized_choices(("High", "Normal", "Low")),
                            default_value=tr_value(self.settings["default_queue_priority"]),
                            width=130,
                        )
                        add_help_tooltip(self.default_priority_combo, "QUEUE_PRIORITY")
                    self.auto_resume_checkbox = dpg.add_checkbox(
                        label=tr('view.settings_view.resume_torrents_that_were_active_when_salixtorrent', "Resume torrents that were active when SalixTorrent closed"),
                        default_value=bool(self.settings["auto_resume_active"]),
                    )
                    add_help_tooltip(self.auto_resume_checkbox, "AUTO_RESUME")

                with dpg.child_window(width=-1, height=225, border=True) as self.global_bandwidth_panel:
                    dpg.add_text(tr('view.settings_view.global_bandwidth', "GLOBAL BANDWIDTH"), color=(255, 170, 100))
                    dpg.add_separator()
                    global_bandwidth_note = dpg.add_text(
                        tr('view.settings_view.aggregate_limit_shared_by_every_active_torrent', "Aggregate limit shared by every active torrent. 0 = Unlimited."),
                        color=(150, 150, 150),
                    )
                    add_help_tooltip(global_bandwidth_note, "GLOBAL_BANDWIDTH")
                    with dpg.group(horizontal=True):
                        dpg.add_text(tr('view.settings_view.download', "Download"))
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
                        dpg.add_text(tr('view.settings_view.upload', "Upload   "))
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
                with dpg.child_window(width=530, height=350, border=True) as self.new_defaults_panel:
                    dpg.add_text(tr('view.settings_view.new_torrent_defaults', "NEW TORRENT DEFAULTS"), color=(100, 180, 255))
                    dpg.add_separator()
                    new_torrent_defaults_note = dpg.add_text(tr('view.settings_view.per_torrent_limits_assigned_when_a_torrent', "Per-torrent limits assigned when a torrent is added."))
                    add_help_tooltip(new_torrent_defaults_note, "NEW_TORRENT_LIMITS")
                    with dpg.group(horizontal=True):
                        dpg.add_text(tr('view.settings_view.download', "Download"))
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
                        dpg.add_text(tr('view.settings_view.upload', "Upload   "))
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

                    dpg.add_spacer(height=5)
                    self.default_seeding_goal_field = LabeledComboField(
                        tr("settings.default_seeding_goal", "Default seeding goal"),
                        localized_choices(SEEDING_GOAL_MODES),
                        default_value=tr_value(self.settings["default_seeding_goal_mode"]),
                        control_width=230,
                    )
                    self.default_seeding_goal_field.build()
                    self.default_seeding_goal_combo = self.default_seeding_goal_field.control.require_item()
                    add_help_tooltip(
                        self.default_seeding_goal_field.label.require_item(),
                        "SEEDING_GOAL",
                    )
                    add_help_tooltip(self.default_seeding_goal_combo, "SEEDING_GOAL")

                    self.default_seeding_ratio_field = LabeledNumericField(
                        tr("settings.default_seed_ratio", "Ratio target"),
                        kind=NumericKind.FLOAT,
                        default_value=float(self.settings["default_seeding_ratio"]),
                        min_value=0.1,
                        max_value=1000.0,
                        min_clamped=True,
                        max_clamped=True,
                        format="%.2f",
                        control_width=120,
                    )
                    self.default_seeding_ratio_field.build()
                    self.default_seeding_ratio_input = self.default_seeding_ratio_field.control.require_item()
                    add_help_tooltip(
                        self.default_seeding_ratio_field.label.require_item(),
                        "SEEDING_RATIO",
                    )
                    add_help_tooltip(self.default_seeding_ratio_input, "SEEDING_RATIO")

                    default_days, default_hours, default_minutes = seeding_time_parts_from_minutes(
                        self.settings["default_seeding_time_minutes"]
                    )
                    # The defaults pane remains deliberately narrow.  The
                    # reusable DurationEditor preserves the stacked aligned
                    # presentation while standardising its primitive controls.
                    self.default_seeding_duration_editor = DurationEditor(
                        heading=tr("settings.default_seed_time", "Time target"),
                        day_label=tr("settings.seed_time_days", "Days"),
                        hour_label=tr("settings.seed_time_hours", "Hours"),
                        minute_label=tr("settings.seed_time_minutes", "Minutes"),
                        days=default_days,
                        hours=default_hours,
                        minutes=default_minutes,
                        input_width=120,
                        grid_width=250,
                        label_column_width=80,
                        control_column_width=150,
                    )
                    self.default_seeding_duration_editor.build()
                    add_help_tooltip(
                        self.default_seeding_duration_editor.heading.require_item(),
                        "SEEDING_TIME",
                    )
                    (
                        self.default_seeding_time_days_input,
                        self.default_seeding_time_hours_input,
                        self.default_seeding_time_minutes_input,
                    ) = self.default_seeding_duration_editor.value_items()
                    for item in (
                        self.default_seeding_time_days_input,
                        self.default_seeding_time_hours_input,
                        self.default_seeding_time_minutes_input,
                    ):
                        add_help_tooltip(item, "SEEDING_TIME")
                    seed_defaults_note = dpg.add_text(
                        tr(
                            "settings.seeding_defaults_note",
                            "Used as the default for new torrents. Existing torrents keep their own seeding goal unless the option below is selected.",
                        ),
                        color=(150, 150, 150),
                        wrap=480,
                    )
                    add_help_tooltip(seed_defaults_note, "SEEDING_GOAL")
                    self.apply_seeding_goal_existing_checkbox = dpg.add_checkbox(
                        label=tr(
                            "settings.apply_seeding_goal_existing",
                            "Apply this seeding goal to all existing torrents when saving",
                        ),
                        default_value=False,
                    )
                    add_help_tooltip(
                        self.apply_seeding_goal_existing_checkbox, "SEEDING_GOAL"
                    )

                with dpg.child_window(width=-1, height=350, border=True) as self.desktop_panel:
                    dpg.add_text(tr("settings.desktop.heading", "DESKTOP"), color=(0, 255, 128))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        language_label_item = dpg.add_text(
                            tr("settings.language.label", "Application language")
                        )
                        self.language_combo = dpg.add_combo(
                            items=list(LANGUAGE_OPTION_LABELS.values()),
                            default_value=locale_label(self.settings.get("language", "auto")),
                            width=205,
                        )
                        add_text_tooltip(
                            language_label_item,
                            tr(
                                "settings.language.restart_note",
                                "Language changes are applied after the interface is rebuilt. "
                                "Restart SalixTorrent to update every open control and document safely.",
                            ),
                        )
                        add_text_tooltip(
                            self.language_combo,
                            tr(
                                "settings.language.restart_note",
                                "Language changes are applied after the interface is rebuilt. "
                                "Restart SalixTorrent to update every open control and document safely.",
                            ),
                        )
                    with dpg.group(horizontal=True):
                        text_size_label = dpg.add_text(
                            tr("settings.interface_text_size", "Interface text size")
                        )
                        self.ui_font_size_combo = dpg.add_combo(
                            items=[UI_FONT_LABELS[size] for size in UI_FONT_SIZES],
                            default_value=ui_font_label(self.settings.get("ui_font_size", 15)),
                            width=180,
                        )
                        add_help_tooltip(text_size_label, "UI_TEXT_SIZE")
                        add_help_tooltip(self.ui_font_size_combo, "UI_TEXT_SIZE")
                    with dpg.group(horizontal=True):
                        documentation_scale_label_item = dpg.add_text(tr("settings.documentation_scale", "Documentation scale"))
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
                        rate_display_label = dpg.add_text(tr("settings.transfer_rate_display", "Transfer rate display"))
                        self.transfer_rate_display_combo = dpg.add_combo(
                            items=localized_choices(TRANSFER_RATE_UNITS),
                            default_value=tr_value(self.settings.get("transfer_rate_display_unit", "Auto")),
                            width=105,
                        )
                        add_help_tooltip(rate_display_label, "TRANSFER_RATE")
                        add_help_tooltip(self.transfer_rate_display_combo, "TRANSFER_RATE")
                    self.completion_notifications_checkbox = dpg.add_checkbox(
                        label=tr("settings.completion_notices", "Show in-app completion notices"),
                        default_value=bool(self.settings["completion_notifications"]),
                    )
                    add_help_tooltip(self.completion_notifications_checkbox, "COMPLETION_NOTICE")
                    desktop_caps = self.desktop.capability_snapshot()
                    self.native_notifications_checkbox = dpg.add_checkbox(
                        label=tr("settings.native_notifications", "Show native desktop completion notifications"),
                        default_value=bool(self.settings["native_notifications"]),
                        enabled=bool(desktop_caps.notifications_supported),
                    )
                    add_help_tooltip(self.native_notifications_checkbox, "NATIVE_NOTIFICATION")
                    self.system_tray_checkbox = dpg.add_checkbox(
                        label=tr("settings.system_tray", "Enable system tray / menu bar icon and controls"),
                        default_value=bool(self.settings["system_tray_enabled"]),
                        enabled=bool(desktop_caps.tray_supported),
                    )
                    add_help_tooltip(self.system_tray_checkbox, "SYSTEM_TRAY")
                    self.minimize_to_tray_checkbox = dpg.add_checkbox(
                        label=tr("settings.minimize_tray", "Minimize to system tray"),
                        default_value=bool(self.settings["minimize_to_tray"]),
                        enabled=bool(desktop_caps.minimize_to_tray_supported),
                    )
                    add_help_tooltip(self.minimize_to_tray_checkbox, "MINIMIZE_TRAY")
                    self.close_to_tray_checkbox = dpg.add_checkbox(
                        label=tr("settings.close_tray", "Close window to system tray"),
                        default_value=bool(self.settings.get("close_to_tray", True)),
                        enabled=bool(desktop_caps.close_to_tray_supported),
                    )
                    add_help_tooltip(self.close_to_tray_checkbox, "CLOSE_TO_TRAY")
                    tray_state = (
                        "running"
                        if desktop_caps.tray_running
                        else ("available" if desktop_caps.tray_supported else "unavailable")
                    )
                    desktop_status = (
                        tr('view.settings_view.desktop_backend_value_tray_value_notifications_value', 'Desktop backend: {tray_backend} | Tray: {tray_state} | Notifications: {value2}', tray_backend=desktop_caps.tray_backend, tray_state=tray_state, value2='available' if desktop_caps.notifications_supported else 'unavailable')
                    )
                    dpg.add_text(desktop_status, color=(155, 155, 160))
                    if desktop_caps.detail:
                        dpg.add_text(
                            desktop_caps.detail,
                            color=(155, 155, 160),
                            wrap=680,
                        )

            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                save_preferences_button = dpg.add_button(label=tr("settings.save", " Save Preferences "), callback=self._save)
                add_text_tooltip(save_preferences_button, tr('view.settings_view.save_preferences_validates_persists_and_applies_the', "Save Preferences\n\nValidates, persists and applies the values shown on this page. Networking toggles and global limits can affect active sessions immediately."))
                restore_defaults_button = dpg.add_button(label=tr("settings.restore_defaults", " Restore Defaults "), callback=self._restore_defaults)
                add_text_tooltip(restore_defaults_button, tr('view.settings_view.restore_defaults_replaces_the_current_application_preferences', "Restore Defaults\n\nReplaces the current application preferences with SalixTorrent's built-in defaults and applies them. This does not delete torrents or payload data."))
                self.status_text = dpg.add_text("", color=(0, 255, 128))

            dpg.add_spacer(height=7)
            settings_path_text = dpg.add_text(
                tr('view.settings_view.settings_file_value', 'Settings file: {settings_path}', settings_path=self.manager.settings_path),
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
        option_to_address = {tr("view.settings_view.any_interface_system_routing", "Any interface (system routing)"): ""}

        for interface in list_network_interfaces():
            address = normalise_bind_address(interface.address)
            if not address:
                continue
            label = interface.label
            if label in option_to_address and option_to_address[label] != address:
                label = f"{label} [{address}]"
            option_to_address[label] = address

        if selected_address and selected_address not in option_to_address.values():
            option_to_address[tr("view.settings_view.unavailable_address", "Unavailable — {address}", address=selected_address)] = selected_address

        self._bind_option_to_address = option_to_address
        self._bind_address_to_option = {address: label for label, address in option_to_address.items()}
        selected_label = self._bind_address_to_option.get(
            selected_address, tr("view.settings_view.any_interface_system_routing", "Any interface (system routing)")
        )
        return list(option_to_address), selected_label

    def _refresh_network_interfaces(self):
        selected_label = str(dpg.get_value(self.network_bind_combo) or "")
        selected_address = self._bind_option_to_address.get(selected_label, "")
        options, selected = self._build_network_interface_options(selected_address)
        dpg.configure_item(self.network_bind_combo, items=options)
        dpg.set_value(self.network_bind_combo, selected)
        dpg.set_value(self.status_text, tr('view.settings_view.network_interface_list_refreshed', "Network interface list refreshed"))

    def _choose_download_dir(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = str(dpg.get_value(self.download_dir_input) or os.getcwd())
        folder = filedialog.askdirectory(
            title=tr('view.settings_view.choose_default_download_directory', "Choose Default Download Directory"),
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
            "close_to_tray": bool(dpg.get_value(self.close_to_tray_checkbox)),
            "transfer_rate_display_unit": canonical_choice(
                dpg.get_value(self.transfer_rate_display_combo), TRANSFER_RATE_UNITS, "Auto"
            ),
            "ui_font_size": ui_font_size_from_label(
                dpg.get_value(self.ui_font_size_combo)
            ),
            "documentation_scale": documentation_scale_from_label(
                dpg.get_value(self.documentation_scale_combo)
            ),
            "language": locale_code_from_label(dpg.get_value(self.language_combo)),
            "listen_port": int(dpg.get_value(self.listen_port_input) or 6881),
            "peer_encryption": canonical_choice(
                dpg.get_value(self.peer_encryption_combo), PEER_ENCRYPTION_POLICIES, "Prefer Encryption"
            ),
            "torrent_protocol_policy": canonical_choice(
                dpg.get_value(self.torrent_protocol_combo), TORRENT_PROTOCOL_POLICIES, TORRENT_PROTOCOL_AUTO
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
            "default_queue_priority": canonical_choice(dpg.get_value(self.default_priority_combo), ("High", "Normal", "Low"), "Normal"),
            "default_seeding_goal_mode": canonical_choice(
                dpg.get_value(self.default_seeding_goal_combo),
                SEEDING_GOAL_MODES,
                SEEDING_GOAL_MODES[0],
            ),
            "default_seeding_ratio": float(
                dpg.get_value(self.default_seeding_ratio_input) or 1.0
            ),
            "default_seeding_time_minutes": seeding_time_parts_to_minutes(
                dpg.get_value(self.default_seeding_time_days_input),
                dpg.get_value(self.default_seeding_time_hours_input),
                dpg.get_value(self.default_seeding_time_minutes_input),
            ),
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
            self.close_to_tray_checkbox: settings.get("close_to_tray", True),
            self.transfer_rate_display_combo: tr_value(settings.get("transfer_rate_display_unit", "Auto")),
            self.ui_font_size_combo: ui_font_label(settings.get("ui_font_size", 15)),
            self.documentation_scale_combo: documentation_scale_label(
                settings.get("documentation_scale", 100)
            ),
            self.language_combo: locale_label(settings.get("language", "auto")),
            self.listen_port_input: settings["listen_port"],
            self.peer_encryption_combo: tr_value(settings.get("peer_encryption", "Prefer Encryption")),
            self.torrent_protocol_combo: tr_value(settings.get(
                "torrent_protocol_policy", TORRENT_PROTOCOL_AUTO
            )),
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
            self.default_priority_combo: tr_value(settings["default_queue_priority"]),
            self.default_seeding_goal_combo: tr_value(
                settings.get("default_seeding_goal_mode", SEEDING_GOAL_MODES[0])
            ),
            self.default_seeding_ratio_input: settings.get("default_seeding_ratio", 1.0),
        }
        for item, value in values.items():
            dpg.set_value(item, value)

        default_days, default_hours, default_minutes = seeding_time_parts_from_minutes(
            settings.get("default_seeding_time_minutes", 60)
        )
        dpg.set_value(self.default_seeding_time_days_input, default_days)
        dpg.set_value(self.default_seeding_time_hours_input, default_hours)
        dpg.set_value(self.default_seeding_time_minutes_input, default_minutes)

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
                status = tr('view.settings_view.ipv6_direct_value_active_listener_ports_ipv4_nat_mapping', 'IPv6 Direct ({listener_count} active listener ports; IPv4 NAT mapping not applicable)', listener_count=listener_count)
            else:
                status = tr('view.settings_view.value_value_value_listener_ports_mapped', '{status} ({mapping_count}/{listener_count} listener ports mapped)', status=status, mapping_count=mapping_count, listener_count=listener_count)
            local_value = tr('view.settings_view.local_value_ports_value', 'Local: {local_ip} | ports {value1}', local_ip=local_ip, value1=', '.join((str(p) for p in listener_ports)))
            if external_ip not in {"", "--"}:
                external_scope = str(snap.get("external_scope") or "Unknown")
                scope_suffix = f" ({external_scope})" if external_scope != "Unknown" else ""
                external_value = tr('view.settings_view.external_value_value_mapped_ports_value', 'External: {external_ip}{scope_suffix} | mapped ports {value2}', external_ip=external_ip, scope_suffix=scope_suffix, value2=', '.join((str(p) for p in mapped_ports)) or '--')
            else:
                external_value = (
                    "External: IPv6 route/firewall dependent; no IPv4 NAT mapping"
                    if ipv6_direct
                    else f"External mapped ports: {', '.join(str(p) for p in mapped_ports) or '--'}"
                )
        else:
            local_value = tr('view.settings_view.local_value', 'Local: {value0}', value0=format_endpoint(local_ip, internal_port) if internal_port else local_ip)
            external_scope = str(snap.get("external_scope") or "Unknown")
            scope_suffix = f" ({external_scope})" if external_ip not in {"", "--"} and external_scope != "Unknown" else ""
            if external_ip not in {"", "--"}:
                external_value = tr('view.settings_view.external_value_value', 'External: {value0}{scope_suffix}', value0=format_endpoint(external_ip, external_port), scope_suffix=scope_suffix)
            elif ipv6_direct:
                external_value = tr("view.settings_view.external_ipv6_route_firewall_dependent", "External: IPv6 route/firewall dependent; no IPv4 NAT mapping")
            else:
                external_value = tr("view.settings_view.external_unknown", "External: --")

        dpg.set_value(self.connectivity_status, tr('view.settings_view.status_value', 'Status: {status}', status=status))
        dpg.set_value(self.connectivity_method, tr('view.settings_view.mapping_value', 'Mapping: {method}', method=method))
        dpg.set_value(
            self.connectivity_methods,
            tr('view.settings_view.methods_upnp_value_nat_pmp_value', 'Methods: UPnP {value0} | NAT-PMP {value1}', value0=snap.get('upnp_status', '--'), value1=snap.get('natpmp_status', '--')),
        )
        dpg.set_value(self.connectivity_local, local_value)
        dpg.set_value(self.connectivity_external, external_value)
        dpg.set_value(
            self.connectivity_protocols,
            tr('view.settings_view.mapped_protocols_value', 'Mapped protocols: {value0}', value0=' + '.join(protocols) if protocols else 'not applicable to IPv6 direct' if ipv6_direct else '--'),
        )
        incoming_peer = str(snap.get("last_incoming_peer") or "--")
        if self.settings.get("mask_peer_ips") and incoming_peer not in {"", "--"}:
            incoming_peer = mask_ip_for_display(incoming_peer)
        incoming_age = self._format_age(snap.get("last_incoming_seconds"))
        dpg.set_value(
            self.connectivity_incoming,
            tr('view.settings_view.last_incoming_peer_value_value', 'Last incoming peer: {incoming_peer} ({incoming_age})', incoming_peer=incoming_peer, incoming_age=incoming_age),
        )
        dpg.set_value(
            self.connectivity_refresh_age,
            tr('view.settings_view.last_mapping_check_value', 'Last mapping check: {value0}', value0=self._format_age(snap.get('last_refresh_seconds'))),
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
            tr('view.settings_view.next_lease_refresh_value', 'Next lease refresh: {next_refresh_text}', next_refresh_text=next_refresh_text),
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
        dpg.set_value(self.status_text, tr('view.settings_view.connectivity_refresh_started', "Connectivity refresh started"))

    def _save(self):
        previous_language = str(self.settings.get("language", "auto"))
        apply_existing = bool(
            dpg.get_value(self.apply_seeding_goal_existing_checkbox)
        )
        settings = self.manager.update_app_settings(self._collect())
        applied_count = 0
        if apply_existing:
            applied_count = self.manager.apply_seeding_goal_to_all_existing(
                settings.get("default_seeding_goal_mode", SEEDING_GOAL_MODES[0]),
                settings.get("default_seeding_ratio", 1.0),
                settings.get("default_seeding_time_minutes", 60),
            )

        self.desktop.configure(settings)
        self.typography.apply_font_size(settings.get("ui_font_size", 15))
        language_changed = str(settings.get("language", "auto")) != previous_language
        if language_changed:
            self.localization.configure(settings.get("language", "auto"))
        self._sync_controls(settings)
        dpg.set_value(self.apply_seeding_goal_existing_checkbox, False)

        if apply_existing:
            status_text = tr(
                "settings.saved_applied_seeding_goal",
                "Preferences saved. Seeding goal applied to {count} existing torrent(s).",
                count=applied_count,
            )
            if language_changed:
                status_text += " " + tr(
                    "settings.saved_restart_language_suffix",
                    "Restart SalixTorrent to apply the selected language everywhere.",
                )
        elif language_changed:
            status_text = tr(
                "settings.saved_restart",
                "Preferences saved. Restart SalixTorrent to apply the selected language everywhere.",
            )
        else:
            status_text = tr("settings.saved", "Preferences saved and applied")
        dpg.set_value(self.status_text, status_text)
        self._render_connectivity()

    def _restore_defaults(self):
        settings = self.manager.reset_app_settings()
        self.localization.configure(settings.get("language", "auto"))
        self.desktop.configure(settings)
        self.typography.apply_font_size(settings.get("ui_font_size", 15))
        self._sync_controls(settings)
        dpg.set_value(self.apply_seeding_goal_existing_checkbox, False)
        dpg.set_value(
            self.status_text,
            tr("settings.defaults_restored", "Defaults restored and applied"),
        )
        self._render_connectivity()

    def on_show(self, **kwargs):
        self.layout.trigger(("settings_view", "root"))
        settings = self.manager.get_app_settings()
        settings["max_active_downloads"] = self.manager.get_max_active_downloads()
        self._sync_controls(settings)
        dpg.set_value(self.apply_seeding_goal_existing_checkbox, False)
        self._render_connectivity()
        self._last_connectivity_refresh = time.monotonic()
        dpg.set_value(self.status_text, "")

    def update(self, delta_time: float):
        del delta_time
        now = time.monotonic()
        if now - self._last_connectivity_refresh >= 1.0:
            self._last_connectivity_refresh = now
            self._render_connectivity()
