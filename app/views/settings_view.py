# app/views/settings_view.py

import os
import time
import tkinter as tk
from tkinter import filedialog

from app.engine.desktop_integration import DesktopIntegration
from app.engine.components import (
    BindingSet,
    Button,
    CheckBox,
    ComboBox,
    ControlColumn,
    ControlLayout,
    ControlRow,
    DurationEditor,
    Label,
    LabeledComboField,
    LabeledField,
    LabeledNumericField,
    NumericKind,
    NumericStepper,
    NumericUnitField,
    SectionPanel,
    Spacer,
    TextInput,
    ValueBinding,
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
        self.preferences_root = ControlColumn()
        with self.preferences_root.context(parent=parent_tag):
            preferences_heading_component = Label(
                tr("settings.heading", "PREFERENCES"), color=(0, 255, 128)
            )
            preferences_heading = preferences_heading_component.build()
            add_help_tooltip(preferences_heading, "PREFERENCES_VIEW")
            self.preferences_intro_component = Label(
                tr(
                    "settings.intro",
                    "Network toggles and global limits apply to active sessions immediately. "
                    "New-torrent defaults only affect torrents added later.",
                ),
                color=(155, 155, 160),
                wrap=1000,
            )
            self.preferences_intro = self.preferences_intro_component.build()
            add_help_tooltip(self.preferences_intro, "PREFERENCES_VIEW")
            Spacer(layout=ControlLayout(height=6)).build()

            self.downloads_section = SectionPanel(
                tr('view.settings_view.downloads', "DOWNLOADS"),
                heading_color=(100, 180, 255),
                profile_key="settings.downloads_panel",
            )
            with self.downloads_section.context() as self.downloads_panel:
                self.download_directory_field = LabeledField(
                    tr("settings.default_download_directory", "Default download directory"),
                    TextInput(
                        default_value=self.settings["download_dir"],
                        profile_key="settings.download_path",
                    ),
                    accessories=(
                        Button(
                            tr("settings.choose_folder", " Choose Folder "),
                            callback=self._choose_download_dir,
                        ),
                    ),
                )
                self.download_directory_field.build()
                self.download_dir_input = self.download_directory_field.control.require_item()
                choose_download_dir_button = self.download_directory_field.accessories[0].require_item()
                add_help_tooltip(self.download_directory_field.label.require_item(), "DEFAULT_DOWNLOAD_DIR")
                add_help_tooltip(self.download_dir_input, "DEFAULT_DOWNLOAD_DIR")
                add_help_tooltip(choose_download_dir_button, "DEFAULT_DOWNLOAD_DIR")

            Spacer(layout=ControlLayout(height=7)).build()
            self.networking_pair = ControlRow()
            with self.networking_pair.context():
                self.networking_section = SectionPanel(
                    tr('view.settings_view.networking', "NETWORKING"),
                    heading_color=(255, 200, 100),
                    profile_key="settings.networking_panel",
                )
                with self.networking_section.context() as self.networking_panel:
                    self.listen_port_field = LabeledField(
                        tr('view.settings_view.bittorrent_listen_port', "BitTorrent listen port"),
                        NumericStepper(
                            kind=NumericKind.INTEGER,
                            default_value=int(self.settings["listen_port"]),
                            min_value=1,
                            max_value=65535,
                            min_clamped=True,
                            max_clamped=True,
                            profile_key="settings.listen_port",
                        ),
                        accessories=(
                            Label(
                                tr('view.settings_view.fallback_next_10_ports', "Fallback: next 10 ports"),
                                color=(140, 140, 145),
                            ),
                        ),
                    )
                    self.listen_port_field.build()
                    self.listen_port_input = self.listen_port_field.control.require_item()
                    fallback_ports = self.listen_port_field.accessories[0].require_item()
                    add_help_tooltip(self.listen_port_field.label.require_item(), "LISTEN_PORT")
                    add_help_tooltip(self.listen_port_input, "LISTEN_PORT")
                    add_text_tooltip(fallback_ports, tr('view.settings_view.listen_port_fallback_if_the_preferred_tcp', "Listen-port fallback\n\nIf the preferred TCP port is already occupied, SalixTorrent tries the next ten port numbers rather than failing the entire torrent subsystem."))

                    self.torrent_protocol_field = LabeledComboField(
                        tr('view.settings_view.torrent_protocol', "Torrent protocol"),
                        localized_choices(TORRENT_PROTOCOL_POLICIES),
                        default_value=tr_value(self.settings.get(
                            "torrent_protocol_policy", TORRENT_PROTOCOL_AUTO
                        )),
                        control_profile_key="settings.protocol",
                    )
                    self.torrent_protocol_field.build()
                    self.torrent_protocol_combo = self.torrent_protocol_field.control.require_item()
                    add_help_tooltip(self.torrent_protocol_field.label.require_item(), "TORRENT_PROTOCOL_POLICY")
                    add_help_tooltip(self.torrent_protocol_combo, "TORRENT_PROTOCOL_POLICY")

                    self.max_peers_field = LabeledNumericField(
                        tr('view.settings_view.default_max_peers', "Default max peers"),
                        kind=NumericKind.INTEGER,
                        default_value=int(self.settings["default_max_peers"]),
                        min_value=1,
                        max_value=500,
                        min_clamped=True,
                        max_clamped=True,
                        control_profile_key="settings.max_peers",
                    )
                    self.max_peers_field.build()
                    self.max_peers_input = self.max_peers_field.control.require_item()
                    add_help_tooltip(self.max_peers_field.label.require_item(), "MAX_PEERS")
                    add_help_tooltip(self.max_peers_input, "MAX_PEERS")

                    self.enable_dht_control = CheckBox(
                        tr('view.settings_view.enable_dht_bep_5_bep_32', "Enable DHT (BEP-5 / BEP-32)"),
                        default_value=bool(self.settings["enable_dht"]),
                    )
                    self.enable_dht_checkbox = self.enable_dht_control.build()
                    add_help_tooltip(self.enable_dht_checkbox, "DHT")
                    self.enable_pex_control = CheckBox(
                        tr('view.settings_view.enable_peer_exchange_pex_bep_10_11', "Enable Peer Exchange / PEX (BEP-10/11)"),
                        default_value=bool(self.settings["enable_pex"]),
                    )
                    self.enable_pex_checkbox = self.enable_pex_control.build()
                    add_help_tooltip(self.enable_pex_checkbox, "PEX")
                    self.enable_lan_control = CheckBox(
                        tr('view.settings_view.enable_local_peer_discovery_lan_bep_14', "Enable Local Peer Discovery / LAN (BEP-14)"),
                        default_value=bool(self.settings["enable_lan_discovery"]),
                    )
                    self.enable_lan_checkbox = self.enable_lan_control.build()
                    add_help_tooltip(self.enable_lan_checkbox, "LPD")
                    self.port_mapping_row = ControlRow(
                        (
                            CheckBox(
                                tr('view.settings_view.upnp_port_mapping', "UPnP port mapping"),
                                default_value=bool(self.settings["enable_upnp"]),
                            ),
                            CheckBox(
                                tr('view.settings_view.nat_pmp_fallback', "NAT-PMP fallback"),
                                default_value=bool(self.settings["enable_natpmp"]),
                            ),
                        )
                    )
                    self.port_mapping_row.build()
                    self.enable_upnp_checkbox = self.port_mapping_row.children[0].require_item()
                    self.enable_natpmp_checkbox = self.port_mapping_row.children[1].require_item()
                    add_help_tooltip(self.enable_upnp_checkbox, "UPNP")
                    add_help_tooltip(self.enable_natpmp_checkbox, "NATPMP")

                self.connectivity_section = SectionPanel(
                    tr('view.settings_view.incoming_connectivity', "INCOMING CONNECTIVITY"),
                    heading_color=(0, 255, 128),
                    profile_key="settings.connectivity_panel",
                )
                with self.connectivity_section.context() as self.connectivity_panel:
                    self.connectivity_status_component = Label(tr('view.settings_view.status_waiting', "Status: Waiting"))
                    self.connectivity_status = self.connectivity_status_component.build()
                    add_help_tooltip(self.connectivity_status, "PORT_MAPPING")
                    self.connectivity_method_component = Label(tr('view.settings_view.mapping', "Mapping: --"))
                    self.connectivity_method = self.connectivity_method_component.build()
                    add_help_tooltip(self.connectivity_method, "PORT_MAPPING")
                    self.connectivity_methods_component = Label(tr('view.settings_view.methods_upnp_nat_pmp', "Methods: UPnP -- | NAT-PMP --"))
                    self.connectivity_methods = self.connectivity_methods_component.build()
                    add_help_tooltip(self.connectivity_methods, "MAPPING_METHOD_STATUS")
                    self.connectivity_local_component = Label(tr('view.settings_view.local', "Local: --"))
                    self.connectivity_local = self.connectivity_local_component.build()
                    add_help_tooltip(self.connectivity_local, "LOCAL_ENDPOINT")
                    self.connectivity_external_component = Label(tr('view.settings_view.external', "External: --"))
                    self.connectivity_external = self.connectivity_external_component.build()
                    add_help_tooltip(self.connectivity_external, "EXTERNAL_ENDPOINT")
                    self.connectivity_protocols_component = Label(tr('view.settings_view.mapped_protocols', "Mapped protocols: --"))
                    self.connectivity_protocols = self.connectivity_protocols_component.build()
                    add_help_tooltip(self.connectivity_protocols, "MAPPED_PROTOCOLS")
                    self.connectivity_incoming_component = Label(tr('view.settings_view.last_incoming_peer', "Last incoming peer: --"))
                    self.connectivity_incoming = self.connectivity_incoming_component.build()
                    add_help_tooltip(self.connectivity_incoming, "LAST_INCOMING")
                    self.connectivity_refresh_age_component = Label(tr('view.settings_view.last_mapping_check', "Last mapping check: --"))
                    self.connectivity_refresh_age = self.connectivity_refresh_age_component.build()
                    add_help_tooltip(self.connectivity_refresh_age, "MAPPING_METHOD_STATUS")
                    self.connectivity_next_refresh_component = Label(tr('view.settings_view.next_lease_refresh', "Next lease refresh: --"))
                    self.connectivity_next_refresh = self.connectivity_next_refresh_component.build()
                    add_help_tooltip(self.connectivity_next_refresh, "MAPPING_LEASE")
                    self.connectivity_error_component = Label(
                        "", color=(220, 180, 100), wrap=480
                    )
                    self.connectivity_error = self.connectivity_error_component.build()
                    add_help_tooltip(self.connectivity_error, "PORT_MAPPING")
                    Spacer(layout=ControlLayout(height=6)).build()
                    self.refresh_connectivity_control = Button(
                        tr('view.settings_view.refresh_remap_now', " Refresh / Remap Now "),
                        callback=self._refresh_connectivity,
                    )
                    refresh_connectivity_button = self.refresh_connectivity_control.build()
                    add_help_tooltip(refresh_connectivity_button, "PORT_MAPPING")
                    self.connectivity_note_component = Label(
                        tr('view.settings_view.mapped_means_the_router_accepted_a_mapping', "'Mapped' means the router accepted a mapping. 'Incoming Confirmed' "
                        "means a real remote peer has reached SalixTorrent."),
                        color=(145, 145, 150),
                        wrap=480,
                    )
                    self.connectivity_note = self.connectivity_note_component.build()
                    add_help_tooltip(self.connectivity_note, "PORT_MAPPING")

            Spacer(layout=ControlLayout(height=7)).build()
            self.privacy_section = SectionPanel(
                tr('view.settings_view.privacy_transport', "PRIVACY / TRANSPORT"),
                heading_color=(100, 220, 200),
                profile_key="settings.privacy_panel",
            )
            with self.privacy_section.context() as self.privacy_panel:
                self.peer_encryption_field = LabeledComboField(
                    tr('view.settings_view.peer_transport_encryption', "Peer transport encryption"),
                    localized_choices(PEER_ENCRYPTION_POLICIES),
                    default_value=tr_value(self.settings.get("peer_encryption", "Prefer Encryption")),
                    control_profile_key="settings.peer_encryption",
                )
                self.peer_encryption_field.build()
                self.peer_encryption_combo = self.peer_encryption_field.control.require_item()
                add_help_tooltip(self.peer_encryption_field.label.require_item(), "MSE")
                add_help_tooltip(self.peer_encryption_combo, "PEER_ENCRYPTION_POLICY")

                bind_options, selected_bind_option = self._build_network_interface_options(
                    self.settings.get("network_bind_address", "")
                )
                self.network_bind_field = LabeledField(
                    tr('view.settings_view.network_interface_vpn', "Network interface / VPN"),
                    ComboBox(
                        bind_options,
                        default_value=selected_bind_option,
                        profile_key="settings.network_interface",
                    ),
                    accessories=(
                        Button(
                            tr('view.settings_view.refresh_interfaces', " Refresh Interfaces "),
                            callback=self._refresh_network_interfaces,
                        ),
                    ),
                )
                self.network_bind_field.build()
                self.network_bind_combo = self.network_bind_field.control.require_item()
                refresh_interfaces_button = self.network_bind_field.accessories[0].require_item()
                add_help_tooltip(self.network_bind_field.label.require_item(), "NETWORK_BINDING")
                add_help_tooltip(self.network_bind_combo, "NETWORK_BINDING")
                add_help_tooltip(refresh_interfaces_button, "NETWORK_BINDING")

                self.interface_lock_control = CheckBox(
                    tr('view.settings_view.interface_lock_kill_switch_fail_closed_if', "Interface Lock / kill switch (fail closed if the selected address disappears)"),
                    default_value=bool(self.settings.get("interface_lock", False)),
                )
                self.interface_lock_checkbox = self.interface_lock_control.build()
                add_help_tooltip(self.interface_lock_checkbox, "INTERFACE_LOCK")
                self.mask_peer_ips_control = CheckBox(
                    tr('view.settings_view.mask_peer_ip_addresses_in_the_interface', "Mask peer IP addresses in the interface"),
                    default_value=bool(self.settings.get("mask_peer_ips", False)),
                )
                self.mask_peer_ips_checkbox = self.mask_peer_ips_control.build()
                add_help_tooltip(self.mask_peer_ips_checkbox, "IP_MASKING")
                self.transport_note_component = Label(
                    tr('view.settings_view.binding_chooses_one_local_ipv4_or_ipv6', "Binding chooses one local IPv4 or IPv6 source address for torrent traffic. "
                    "Any interface uses both families when the operating system provides them. Interface Lock "
                    "additionally monitors the selected address and stops torrent networking immediately if it disappears."),
                    color=(145, 145, 150),
                    wrap=1000,
                )
                self.transport_note = self.transport_note_component.build()
                add_help_tooltip(self.transport_note, "INTERFACE_LOCK")

            Spacer(layout=ControlLayout(height=7)).build()
            self.queue_bandwidth_pair = ControlRow()
            with self.queue_bandwidth_pair.context():
                self.queue_section = SectionPanel(
                    tr('view.settings_view.queue', "QUEUE"),
                    heading_color=(180, 160, 255),
                    profile_key="settings.queue_panel",
                )
                with self.queue_section.context() as self.queue_preferences_panel:
                    self.active_slots_field = LabeledField(
                        tr('view.settings_view.active_download_slots', "Active download slots"),
                        NumericStepper(
                            kind=NumericKind.INTEGER,
                            default_value=int(self.settings["max_active_downloads"]),
                            min_value=0,
                            min_clamped=True,
                            profile_key="settings.active_slots",
                        ),
                        accessories=(
                            Label(
                                tr('view.settings_view.0_unlimited', "0 = Unlimited"),
                                color=(150, 150, 150),
                            ),
                        ),
                    )
                    self.active_slots_field.build()
                    self.active_slots_input = self.active_slots_field.control.require_item()
                    active_slots_unlimited = self.active_slots_field.accessories[0].require_item()
                    add_help_tooltip(self.active_slots_field.label.require_item(), "ACTIVE_DL_SLOTS")
                    add_help_tooltip(self.active_slots_input, "ACTIVE_DL_SLOTS")
                    add_help_tooltip(active_slots_unlimited, "ACTIVE_DL_SLOTS")

                    self.default_priority_field = LabeledComboField(
                        tr('view.settings_view.default_queue_priority', "Default queue priority"),
                        localized_choices(("High", "Normal", "Low")),
                        default_value=tr_value(self.settings["default_queue_priority"]),
                        control_profile_key="settings.queue_priority",
                    )
                    self.default_priority_field.build()
                    self.default_priority_combo = self.default_priority_field.control.require_item()
                    add_help_tooltip(self.default_priority_field.label.require_item(), "QUEUE_PRIORITY")
                    add_help_tooltip(self.default_priority_combo, "QUEUE_PRIORITY")

                    self.auto_resume_control = CheckBox(
                        tr('view.settings_view.resume_torrents_that_were_active_when_salixtorrent', "Resume torrents that were active when SalixTorrent closed"),
                        default_value=bool(self.settings["auto_resume_active"]),
                    )
                    self.auto_resume_checkbox = self.auto_resume_control.build()
                    add_help_tooltip(self.auto_resume_checkbox, "AUTO_RESUME")

                self.global_bandwidth_section = SectionPanel(
                    tr('view.settings_view.global_bandwidth', "GLOBAL BANDWIDTH"),
                    heading_color=(255, 170, 100),
                    profile_key="settings.global_bandwidth_panel",
                )
                with self.global_bandwidth_section.context() as self.global_bandwidth_panel:
                    global_bandwidth_note_component = Label(
                        tr('view.settings_view.aggregate_limit_shared_by_every_active_torrent', "Aggregate limit shared by every active torrent. 0 = Unlimited."),
                        color=(150, 150, 150),
                    )
                    global_bandwidth_note = global_bandwidth_note_component.build()
                    add_help_tooltip(global_bandwidth_note, "GLOBAL_BANDWIDTH")
                    self.global_download_limit_field = NumericUnitField(
                        tr('view.settings_view.download', "Download"),
                        RATE_UNITS,
                        default_value=float(self.settings["global_download_limit_value"]),
                        default_unit=self.settings["global_download_limit_unit"],
                        min_value=0.0,
                        min_clamped=True,
                        format="%.2f",
                        value_profile_key="settings.bandwidth.value",
                        unit_profile_key="settings.bandwidth.unit",
                    )
                    self.global_download_limit_field.build()
                    (
                        self.global_download_limit_input,
                        self.global_download_limit_unit,
                    ) = self.global_download_limit_field.value_items()
                    add_help_tooltip(self.global_download_limit_input, "GLOBAL_BANDWIDTH")
                    add_help_tooltip(self.global_download_limit_unit, "GLOBAL_BANDWIDTH")

                    self.global_upload_limit_field = NumericUnitField(
                        tr('view.settings_view.upload', "Upload   "),
                        RATE_UNITS,
                        default_value=float(self.settings["global_upload_limit_value"]),
                        default_unit=self.settings["global_upload_limit_unit"],
                        min_value=0.0,
                        min_clamped=True,
                        format="%.2f",
                        value_profile_key="settings.bandwidth.value",
                        unit_profile_key="settings.bandwidth.unit",
                    )
                    self.global_upload_limit_field.build()
                    (
                        self.global_upload_limit_input,
                        self.global_upload_limit_unit,
                    ) = self.global_upload_limit_field.value_items()
                    add_help_tooltip(self.global_upload_limit_input, "GLOBAL_BANDWIDTH")
                    add_help_tooltip(self.global_upload_limit_unit, "GLOBAL_BANDWIDTH")

            Spacer(layout=ControlLayout(height=7)).build()
            self.defaults_desktop_pair = ControlRow()
            with self.defaults_desktop_pair.context():
                self.new_defaults_section = SectionPanel(
                    tr('view.settings_view.new_torrent_defaults', "NEW TORRENT DEFAULTS"),
                    heading_color=(100, 180, 255),
                    profile_key="settings.new_defaults_panel",
                )
                with self.new_defaults_section.context() as self.new_defaults_panel:
                    new_torrent_defaults_note_component = Label(
                        tr('view.settings_view.per_torrent_limits_assigned_when_a_torrent', "Per-torrent limits assigned when a torrent is added.")
                    )
                    new_torrent_defaults_note = new_torrent_defaults_note_component.build()
                    add_help_tooltip(new_torrent_defaults_note, "NEW_TORRENT_LIMITS")
                    self.default_download_limit_field = NumericUnitField(
                        tr('view.settings_view.download', "Download"),
                        RATE_UNITS,
                        default_value=float(self.settings["default_download_limit_value"]),
                        default_unit=self.settings["default_download_limit_unit"],
                        min_value=0.0,
                        min_clamped=True,
                        format="%.2f",
                        value_profile_key="settings.bandwidth.value",
                        unit_profile_key="settings.bandwidth.unit",
                    )
                    self.default_download_limit_field.build()
                    self.download_limit_input, self.download_limit_unit = (
                        self.default_download_limit_field.value_items()
                    )
                    add_help_tooltip(self.download_limit_input, "NEW_TORRENT_LIMITS")
                    add_help_tooltip(self.download_limit_unit, "NEW_TORRENT_LIMITS")

                    self.default_upload_limit_field = NumericUnitField(
                        tr('view.settings_view.upload', "Upload   "),
                        RATE_UNITS,
                        default_value=float(self.settings["default_upload_limit_value"]),
                        default_unit=self.settings["default_upload_limit_unit"],
                        min_value=0.0,
                        min_clamped=True,
                        format="%.2f",
                        value_profile_key="settings.bandwidth.value",
                        unit_profile_key="settings.bandwidth.unit",
                    )
                    self.default_upload_limit_field.build()
                    self.upload_limit_input, self.upload_limit_unit = (
                        self.default_upload_limit_field.value_items()
                    )
                    add_help_tooltip(self.upload_limit_input, "NEW_TORRENT_LIMITS")
                    add_help_tooltip(self.upload_limit_unit, "NEW_TORRENT_LIMITS")

                    Spacer(layout=ControlLayout(height=5)).build()
                    self.default_seeding_goal_field = LabeledComboField(
                        tr("settings.default_seeding_goal", "Default seeding goal"),
                        localized_choices(SEEDING_GOAL_MODES),
                        default_value=tr_value(self.settings["default_seeding_goal_mode"]),
                        control_profile_key="settings.seeding_goal",
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
                        control_profile_key="settings.seeding_ratio",
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
                        input_profile_key="settings.seeding_duration.input",
                        grid_profile_key="settings.seeding_duration.grid",
                        columns_profile_key="settings.seeding_duration.columns",
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
                    seed_defaults_note_component = Label(
                        tr(
                            "settings.seeding_defaults_note",
                            "Used as the default for new torrents. Existing torrents keep their own seeding goal unless the option below is selected.",
                        ),
                        color=(150, 150, 150),
                        wrap=480,
                    )
                    seed_defaults_note = seed_defaults_note_component.build()
                    add_help_tooltip(seed_defaults_note, "SEEDING_GOAL")
                    self.apply_seeding_goal_existing_control = CheckBox(
                        tr(
                            "settings.apply_seeding_goal_existing",
                            "Apply this seeding goal to all existing torrents when saving",
                        ),
                        default_value=False,
                    )
                    self.apply_seeding_goal_existing_checkbox = (
                        self.apply_seeding_goal_existing_control.build()
                    )
                    add_help_tooltip(
                        self.apply_seeding_goal_existing_checkbox, "SEEDING_GOAL"
                    )

                self.desktop_section = SectionPanel(
                    tr("settings.desktop.heading", "DESKTOP"),
                    heading_color=(0, 255, 128),
                    profile_key="settings.desktop_panel",
                )
                with self.desktop_section.context() as self.desktop_panel:
                    language_restart_note = tr(
                        "settings.language.restart_note",
                        "Language changes are applied after the interface is rebuilt. "
                        "Restart SalixTorrent to update every open control and document safely.",
                    )
                    self.language_field = LabeledComboField(
                        tr("settings.language.label", "Application language"),
                        list(LANGUAGE_OPTION_LABELS.values()),
                        default_value=locale_label(self.settings.get("language", "auto")),
                        control_profile_key="settings.language",
                    )
                    self.language_field.build()
                    self.language_combo = self.language_field.control.require_item()
                    add_text_tooltip(self.language_field.label.require_item(), language_restart_note)
                    add_text_tooltip(self.language_combo, language_restart_note)

                    self.ui_font_size_field = LabeledComboField(
                        tr("settings.interface_text_size", "Interface text size"),
                        [UI_FONT_LABELS[size] for size in UI_FONT_SIZES],
                        default_value=ui_font_label(self.settings.get("ui_font_size", 15)),
                        control_profile_key="settings.ui_text_size",
                    )
                    self.ui_font_size_field.build()
                    self.ui_font_size_combo = self.ui_font_size_field.control.require_item()
                    add_help_tooltip(self.ui_font_size_field.label.require_item(), "UI_TEXT_SIZE")
                    add_help_tooltip(self.ui_font_size_combo, "UI_TEXT_SIZE")

                    self.documentation_scale_field = LabeledComboField(
                        tr("settings.documentation_scale", "Documentation scale"),
                        [DOCUMENTATION_SCALE_LABELS[scale] for scale in DOCUMENTATION_SCALES],
                        default_value=documentation_scale_label(
                            self.settings.get("documentation_scale", 100)
                        ),
                        control_profile_key="settings.documentation_scale",
                    )
                    self.documentation_scale_field.build()
                    self.documentation_scale_combo = (
                        self.documentation_scale_field.control.require_item()
                    )
                    add_help_tooltip(
                        self.documentation_scale_field.label.require_item(),
                        "DOCUMENTATION_SCALE",
                    )
                    add_help_tooltip(self.documentation_scale_combo, "DOCUMENTATION_SCALE")

                    self.transfer_rate_display_field = LabeledComboField(
                        tr("settings.transfer_rate_display", "Transfer rate display"),
                        localized_choices(TRANSFER_RATE_UNITS),
                        default_value=tr_value(
                            self.settings.get("transfer_rate_display_unit", "Auto")
                        ),
                        control_profile_key="settings.transfer_rate_display",
                    )
                    self.transfer_rate_display_field.build()
                    self.transfer_rate_display_combo = (
                        self.transfer_rate_display_field.control.require_item()
                    )
                    add_help_tooltip(
                        self.transfer_rate_display_field.label.require_item(),
                        "TRANSFER_RATE",
                    )
                    add_help_tooltip(self.transfer_rate_display_combo, "TRANSFER_RATE")

                    self.completion_notifications_control = CheckBox(
                        tr("settings.completion_notices", "Show in-app completion notices"),
                        default_value=bool(self.settings["completion_notifications"]),
                    )
                    self.completion_notifications_checkbox = (
                        self.completion_notifications_control.build()
                    )
                    add_help_tooltip(self.completion_notifications_checkbox, "COMPLETION_NOTICE")
                    desktop_caps = self.desktop.capability_snapshot()
                    self.native_notifications_control = CheckBox(
                        tr("settings.native_notifications", "Show native desktop completion notifications"),
                        default_value=bool(self.settings["native_notifications"]),
                        enabled=bool(desktop_caps.notifications_supported),
                    )
                    self.native_notifications_checkbox = self.native_notifications_control.build()
                    add_help_tooltip(self.native_notifications_checkbox, "NATIVE_NOTIFICATION")
                    self.system_tray_control = CheckBox(
                        tr("settings.system_tray", "Enable system tray / menu bar icon and controls"),
                        default_value=bool(self.settings["system_tray_enabled"]),
                        enabled=bool(desktop_caps.tray_supported),
                    )
                    self.system_tray_checkbox = self.system_tray_control.build()
                    add_help_tooltip(self.system_tray_checkbox, "SYSTEM_TRAY")
                    self.minimize_to_tray_control = CheckBox(
                        tr("settings.minimize_tray", "Minimize to system tray"),
                        default_value=bool(self.settings["minimize_to_tray"]),
                        enabled=bool(desktop_caps.minimize_to_tray_supported),
                    )
                    self.minimize_to_tray_checkbox = self.minimize_to_tray_control.build()
                    add_help_tooltip(self.minimize_to_tray_checkbox, "MINIMIZE_TRAY")
                    self.close_to_tray_control = CheckBox(
                        tr("settings.close_tray", "Close window to system tray"),
                        default_value=bool(self.settings.get("close_to_tray", True)),
                        enabled=bool(desktop_caps.close_to_tray_supported),
                    )
                    self.close_to_tray_checkbox = self.close_to_tray_control.build()
                    add_help_tooltip(self.close_to_tray_checkbox, "CLOSE_TO_TRAY")
                    tray_state = (
                        "running"
                        if desktop_caps.tray_running
                        else ("available" if desktop_caps.tray_supported else "unavailable")
                    )
                    desktop_status = (
                        tr('view.settings_view.desktop_backend_value_tray_value_notifications_value', 'Desktop backend: {tray_backend} | Tray: {tray_state} | Notifications: {value2}', tray_backend=desktop_caps.tray_backend, tray_state=tray_state, value2='available' if desktop_caps.notifications_supported else 'unavailable')
                    )
                    Label(desktop_status, color=(155, 155, 160)).build()
                    if desktop_caps.detail:
                        Label(
                            desktop_caps.detail,
                            color=(155, 155, 160),
                            wrap=680,
                        ).build()

            Spacer(layout=ControlLayout(height=10)).build()
            self.preference_actions_row = ControlRow(
                (
                    Button(tr("settings.save", " Save Preferences "), callback=self._save),
                    Button(
                        tr("settings.restore_defaults", " Restore Defaults "),
                        callback=self._restore_defaults,
                    ),
                    Label("", color=(0, 255, 128)),
                )
            )
            self.preference_actions_row.build()
            save_preferences_button = self.preference_actions_row.children[0].require_item()
            restore_defaults_button = self.preference_actions_row.children[1].require_item()
            self.status_component = self.preference_actions_row.children[2]
            self.status_text = self.status_component.require_item()
            add_text_tooltip(save_preferences_button, tr('view.settings_view.save_preferences_validates_persists_and_applies_the', "Save Preferences\n\nValidates, persists and applies the values shown on this page. Networking toggles and global limits can affect active sessions immediately."))
            add_text_tooltip(restore_defaults_button, tr('view.settings_view.restore_defaults_replaces_the_current_application_preferences', "Restore Defaults\n\nReplaces the current application preferences with SalixTorrent's built-in defaults and applies them. This does not delete torrents or payload data."))

            Spacer(layout=ControlLayout(height=7)).build()
            settings_path_component = Label(
                tr('view.settings_view.settings_file_value', 'Settings file: {settings_path}', settings_path=self.manager.settings_path),
                color=(130, 130, 135),
            )
            settings_path_text = settings_path_component.build()
            add_help_tooltip(settings_path_text, "SETTINGS_FILE")

        self.preference_bindings = self._build_preference_bindings()
        self._layout_root = parent_tag
        self.layout.watch_item(
            parent_tag,
            ("settings_view", "root"),
            self._layout_settings_view,
        )

    def _build_preference_bindings(self) -> BindingSet:
        """Create the explicit, synchronous Preferences value-binding contract."""

        any_interface_label = lambda: tr(
            "view.settings_view.any_interface_system_routing",
            "Any interface (system routing)",
        )

        return BindingSet(
            ValueBinding(
                "download_dir",
                self.download_directory_field.control,
                read_transform=lambda value: str(value or "downloads"),
                default="downloads",
            ),
            ValueBinding(
                "default_max_peers",
                self.max_peers_field.control,
                read_transform=lambda value: int(value or 25),
                default=25,
            ),
            ValueBinding(
                "max_active_downloads",
                self.active_slots_field.control,
                read_transform=lambda value: int(value or 0),
                default=0,
            ),
            ValueBinding("auto_resume_active", self.auto_resume_control, read_transform=bool),
            ValueBinding(
                "completion_notifications",
                self.completion_notifications_control,
                read_transform=bool,
            ),
            ValueBinding("native_notifications", self.native_notifications_control, read_transform=bool),
            ValueBinding("system_tray_enabled", self.system_tray_control, read_transform=bool),
            ValueBinding("minimize_to_tray", self.minimize_to_tray_control, read_transform=bool),
            ValueBinding(
                "close_to_tray",
                self.close_to_tray_control,
                read_transform=bool,
                default=True,
            ),
            ValueBinding(
                "transfer_rate_display_unit",
                self.transfer_rate_display_field.control,
                read_transform=lambda value: canonical_choice(
                    value, TRANSFER_RATE_UNITS, "Auto"
                ),
                write_transform=tr_value,
                default="Auto",
            ),
            ValueBinding(
                "ui_font_size",
                self.ui_font_size_field.control,
                read_transform=ui_font_size_from_label,
                write_transform=ui_font_label,
                default=15,
            ),
            ValueBinding(
                "documentation_scale",
                self.documentation_scale_field.control,
                read_transform=documentation_scale_from_label,
                write_transform=documentation_scale_label,
                default=100,
            ),
            ValueBinding(
                "language",
                self.language_field.control,
                read_transform=locale_code_from_label,
                write_transform=locale_label,
                default="auto",
            ),
            ValueBinding(
                "listen_port",
                self.listen_port_field.control,
                read_transform=lambda value: int(value or 6881),
                default=6881,
            ),
            ValueBinding(
                "peer_encryption",
                self.peer_encryption_field.control,
                read_transform=lambda value: canonical_choice(
                    value, PEER_ENCRYPTION_POLICIES, "Prefer Encryption"
                ),
                write_transform=tr_value,
                default="Prefer Encryption",
            ),
            ValueBinding(
                "torrent_protocol_policy",
                self.torrent_protocol_field.control,
                read_transform=lambda value: canonical_choice(
                    value, TORRENT_PROTOCOL_POLICIES, TORRENT_PROTOCOL_AUTO
                ),
                write_transform=tr_value,
                default=TORRENT_PROTOCOL_AUTO,
            ),
            ValueBinding(
                "network_bind_address",
                self.network_bind_field.control,
                read_transform=lambda value: self._bind_option_to_address.get(
                    str(value or ""), ""
                ),
                write_transform=lambda value: self._bind_address_to_option.get(
                    normalise_bind_address(value), any_interface_label()
                ),
                default="",
            ),
            ValueBinding("interface_lock", self.interface_lock_control, read_transform=bool),
            ValueBinding("mask_peer_ips", self.mask_peer_ips_control, read_transform=bool),
            ValueBinding("enable_dht", self.enable_dht_control, read_transform=bool),
            ValueBinding("enable_pex", self.enable_pex_control, read_transform=bool),
            ValueBinding("enable_lan_discovery", self.enable_lan_control, read_transform=bool),
            ValueBinding(
                "enable_upnp",
                self.port_mapping_row.children[0],
                read_transform=bool,
            ),
            ValueBinding(
                "enable_natpmp",
                self.port_mapping_row.children[1],
                read_transform=bool,
            ),
            ValueBinding(
                "global_download_limit_value",
                self.global_download_limit_field.value_control,
                read_transform=lambda value: float(value or 0.0),
                default=0.0,
            ),
            ValueBinding(
                "global_download_limit_unit",
                self.global_download_limit_field.unit_control,
                read_transform=lambda value: str(value or "KB/s"),
                default="KB/s",
            ),
            ValueBinding(
                "global_upload_limit_value",
                self.global_upload_limit_field.value_control,
                read_transform=lambda value: float(value or 0.0),
                default=0.0,
            ),
            ValueBinding(
                "global_upload_limit_unit",
                self.global_upload_limit_field.unit_control,
                read_transform=lambda value: str(value or "KB/s"),
                default="KB/s",
            ),
            ValueBinding(
                "default_download_limit_value",
                self.default_download_limit_field.value_control,
                read_transform=lambda value: float(value or 0.0),
                default=0.0,
            ),
            ValueBinding(
                "default_download_limit_unit",
                self.default_download_limit_field.unit_control,
                read_transform=lambda value: str(value or "KB/s"),
                default="KB/s",
            ),
            ValueBinding(
                "default_upload_limit_value",
                self.default_upload_limit_field.value_control,
                read_transform=lambda value: float(value or 0.0),
                default=0.0,
            ),
            ValueBinding(
                "default_upload_limit_unit",
                self.default_upload_limit_field.unit_control,
                read_transform=lambda value: str(value or "KB/s"),
                default="KB/s",
            ),
            ValueBinding(
                "default_queue_priority",
                self.default_priority_field.control,
                read_transform=lambda value: canonical_choice(
                    value, ("High", "Normal", "Low"), "Normal"
                ),
                write_transform=tr_value,
                default="Normal",
            ),
            ValueBinding(
                "default_seeding_goal_mode",
                self.default_seeding_goal_field.control,
                read_transform=lambda value: canonical_choice(
                    value, SEEDING_GOAL_MODES, SEEDING_GOAL_MODES[0]
                ),
                write_transform=tr_value,
                default=SEEDING_GOAL_MODES[0],
            ),
            ValueBinding(
                "default_seeding_ratio",
                self.default_seeding_ratio_field.control,
                read_transform=lambda value: float(value or 1.0),
                default=1.0,
            ),
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
        selected_label = str(self.network_bind_field.control.get_value() or "")
        selected_address = self._bind_option_to_address.get(selected_label, "")
        options, selected = self._build_network_interface_options(selected_address)
        self.network_bind_field.control.set_items(options)
        self.network_bind_field.control.set_value(selected)
        self.status_component.set_text(
            tr(
                'view.settings_view.network_interface_list_refreshed',
                "Network interface list refreshed",
            )
        )

    def _choose_download_dir(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = str(self.download_directory_field.control.get_value() or os.getcwd())
        folder = filedialog.askdirectory(
            title=tr(
                'view.settings_view.choose_default_download_directory',
                "Choose Default Download Directory",
            ),
            initialdir=initial if os.path.isdir(initial) else os.getcwd(),
        )
        root.destroy()
        if folder:
            self.download_directory_field.control.set_value(os.path.abspath(folder))

    def _collect(self) -> dict:
        values = self.preference_bindings.collect()
        values["default_seeding_time_minutes"] = seeding_time_parts_to_minutes(
            self.default_seeding_duration_editor.days.get_value(),
            self.default_seeding_duration_editor.hours.get_value(),
            self.default_seeding_duration_editor.minutes.get_value(),
        )
        return values

    def _sync_controls(self, settings: dict):
        self.settings = dict(settings)
        bind_options, _bind_selected = self._build_network_interface_options(
            settings.get("network_bind_address", "")
        )
        if self.network_bind_field.control.exists():
            self.network_bind_field.control.set_items(bind_options)

        self.preference_bindings.apply(settings)

        default_days, default_hours, default_minutes = seeding_time_parts_from_minutes(
            settings.get("default_seeding_time_minutes", 60)
        )
        self.default_seeding_duration_editor.days.set_value(default_days)
        self.default_seeding_duration_editor.hours.set_value(default_hours)
        self.default_seeding_duration_editor.minutes.set_value(default_minutes)

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

        self.connectivity_status_component.set_text(tr('view.settings_view.status_value', 'Status: {status}', status=status))
        self.connectivity_method_component.set_text(tr('view.settings_view.mapping_value', 'Mapping: {method}', method=method))
        self.connectivity_methods_component.set_text(
            tr('view.settings_view.methods_upnp_value_nat_pmp_value', 'Methods: UPnP {value0} | NAT-PMP {value1}', value0=snap.get('upnp_status', '--'), value1=snap.get('natpmp_status', '--'))
        )
        self.connectivity_local_component.set_text(local_value)
        self.connectivity_external_component.set_text(external_value)
        self.connectivity_protocols_component.set_text(
            tr('view.settings_view.mapped_protocols_value', 'Mapped protocols: {value0}', value0=' + '.join(protocols) if protocols else 'not applicable to IPv6 direct' if ipv6_direct else '--')
        )
        incoming_peer = str(snap.get("last_incoming_peer") or "--")
        if self.settings.get("mask_peer_ips") and incoming_peer not in {"", "--"}:
            incoming_peer = mask_ip_for_display(incoming_peer)
        incoming_age = self._format_age(snap.get("last_incoming_seconds"))
        self.connectivity_incoming_component.set_text(
            tr('view.settings_view.last_incoming_peer_value_value', 'Last incoming peer: {incoming_peer} ({incoming_age})', incoming_peer=incoming_peer, incoming_age=incoming_age)
        )
        self.connectivity_refresh_age_component.set_text(
            tr('view.settings_view.last_mapping_check_value', 'Last mapping check: {value0}', value0=self._format_age(snap.get('last_refresh_seconds')))
        )
        next_refresh = snap.get("next_mapping_refresh_seconds")
        if snap.get("mapping_permanent") and int(snap.get("mapping_count") or 0) > 0:
            next_refresh_text = "not required (permanent lease)"
        else:
            next_refresh_text = (
                f"in {self._format_duration(next_refresh)}"
                if next_refresh is not None else "--"
            )
        self.connectivity_next_refresh_component.set_text(
            tr('view.settings_view.next_lease_refresh_value', 'Next lease refresh: {next_refresh_text}', next_refresh_text=next_refresh_text)
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
        self.connectivity_error_component.set_text(mapping_notice)
        if status == "Incoming Confirmed":
            notice_color = (0, 220, 128)
        elif status.startswith("Mapped"):
            notice_color = (100, 180, 255)
        elif status == "Unmapped":
            notice_color = (255, 200, 100)
        else:
            notice_color = (170, 170, 175)
        self.connectivity_error_component.configure(color=notice_color)

    def _refresh_connectivity(self):
        self.manager.refresh_connectivity()
        self.status_component.set_text(tr('view.settings_view.connectivity_refresh_started', "Connectivity refresh started"))

    def _save(self):
        previous_language = str(self.settings.get("language", "auto"))
        apply_existing = bool(self.apply_seeding_goal_existing_control.get_value())
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
        self.apply_seeding_goal_existing_control.set_value(False)

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
        self.status_component.set_text(status_text)
        self._render_connectivity()

    def _restore_defaults(self):
        settings = self.manager.reset_app_settings()
        self.localization.configure(settings.get("language", "auto"))
        self.desktop.configure(settings)
        self.typography.apply_font_size(settings.get("ui_font_size", 15))
        self._sync_controls(settings)
        self.apply_seeding_goal_existing_control.set_value(False)
        self.status_component.set_text(
            tr("settings.defaults_restored", "Defaults restored and applied")
        )
        self._render_connectivity()

    def on_show(self, **kwargs):
        self.layout.trigger(("settings_view", "root"))
        settings = self.manager.get_app_settings()
        settings["max_active_downloads"] = self.manager.get_max_active_downloads()
        self._sync_controls(settings)
        self.apply_seeding_goal_existing_control.set_value(False)
        self._render_connectivity()
        self._last_connectivity_refresh = time.monotonic()
        self.status_component.set_text("")

    def update(self, delta_time: float):
        del delta_time
        now = time.monotonic()
        if now - self._last_connectivity_refresh >= 1.0:
            self._last_connectivity_refresh = now
            self._render_connectivity()
