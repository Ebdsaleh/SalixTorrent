# app/views/download_view.py

import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.logic.torrent_manager import TorrentManager
from app.engine.desktop_integration import DesktopIntegration
from app.views.peer_view import PeerView
from app.views.piece_view import PieceView
from app.views.file_view import FileView
from app.views.source_view import SourceView
from app.views.speed_view import SpeedView
from app.views.help_terms import add_help_tooltip, add_text_tooltip
from app.views.transfer_rate import (
    TRANSFER_RATE_UNITS,
    format_transfer_rate,
    format_transfer_rate_pair,
    normalize_transfer_rate_unit,
)


class DownloadView:
    # Heavy detail tabs deliberately update less often than the lightweight
    # queue/general telemetry. Dear PyGui item creation/deletion is synchronous
    # on the UI thread, so rebuilding hidden tables/maps every 0.5 seconds can
    # make Windows mark the application as Not Responding.
    DETAIL_RENDER_INTERVALS = {
        "General": 0.0,
        "Peers": 0.75,
        "Pieces": 1.0,
        "Files": 1.0,
        "Sources": 1.0,
        "Speed": 0.45,
    }

    ACTIVE_PAUSABLE_STATES = {"Checking", "Downloading", "Seeding"}
    STARTABLE_STATES = {"Idle", "Stopped", "Completed", "Error"}
    STOPPABLE_STATES = {
        "Queued",
        "Checking",
        "Fast Resume",
        "Downloading",
        "Seeding",
        "Paused",
    }

    def __init__(self, ui_queue: queue.Queue):
        self.ui_queue = ui_queue
        self.manager = TorrentManager.get_instance()
        self.desktop = DesktopIntegration.get_instance()
        self._sort_specs = None
        self._sort_column_ids = {}
        # Restore the previously selected torrent before telemetry starts
        # rebuilding the rows. If the saved selection is unavailable the
        # manager returns an empty string and the first restored row wins.
        self.active_info_hash: str = self.manager.get_selected_torrent()

        # Each entry is a dictionary containing the table row, its cells and
        # the context-menu widgets belonging to that torrent.
        self.torrent_rows = {}
        self.torrent_order = []
        self.latest_stats = {}
        self._limit_controls_hash: str = ""
        self._pending_remove_info_hash: str = ""
        self._pending_recheck_info_hash: str = ""
        self._removed_info_hashes = set()
        self._search_query: str = ""
        self._state_filter: str = "All"
        self._completion_notified = set()
        self._completion_notice_info_hash: str = ""
        self._magnet_info_hash: str = ""
        self._magnet_close_at: float = 0.0
        self.peer_view = PeerView()
        self.piece_view = PieceView()
        self.file_view = FileView()
        self.source_view = SourceView()
        self.speed_view = SpeedView()
        self._transfer_rate_unit = normalize_transfer_rate_unit(
            self.manager.get_transfer_rate_display_unit()
        )
        self.peer_view.set_rate_unit(self._transfer_rate_unit)
        self.speed_view.set_rate_unit(self._transfer_rate_unit)
        self._queue_slots_value = self.manager.get_max_active_downloads()

        # Only the currently visible detail tab is rendered. Previously every
        # TRANSFER_STATS message rebuilt Peers, Pieces, Files, Sources and Speed
        # even when those tabs were hidden. That was the main UI-freeze source.
        self._active_detail_tab: str = "General"
        self._detail_tab_ids = {}
        self._detail_last_render_at = {}

    def build_view(self, parent_tag: str | int = "primary_window"):
        with dpg.group(parent=parent_tag):
            # Top Controls
            with dpg.group(horizontal=True):
                open_torrent_button = dpg.add_button(
                    label=" + Open Torrent ",
                    callback=self._open_native_file_dialog,
                )
                add_help_tooltip(open_torrent_button, "OPEN_TORRENT")
                open_magnet_button = dpg.add_button(
                    label=" + Open Magnet ",
                    callback=self._show_magnet_dialog,
                )
                add_help_tooltip(open_magnet_button, "OPEN_MAGNET")
                dpg.add_spacer(width=10)
                start_resume_button = dpg.add_button(
                    label=" Start / Resume ",
                    callback=self._on_resume_clicked,
                )
                add_help_tooltip(start_resume_button, "START_RESUME")
                pause_button = dpg.add_button(
                    label=" Pause ",
                    callback=self._on_pause_clicked,
                )
                add_help_tooltip(pause_button, "PAUSE_TORRENT")
                stop_button = dpg.add_button(
                    label=" Stop ",
                    callback=self._on_stop_clicked,
                )
                add_help_tooltip(stop_button, "STOP_TORRENT")
                dpg.add_spacer(width=18)
                slots_label = dpg.add_text("Active DL Slots")
                add_help_tooltip(slots_label, "ACTIVE_DL_SLOTS")
                self.queue_slots_input = dpg.add_input_int(
                    default_value=self._queue_slots_value,
                    min_value=0,
                    min_clamped=True,
                    width=70,
                )
                add_help_tooltip(self.queue_slots_input, "ACTIVE_DL_SLOTS")
                apply_queue_button = dpg.add_button(
                    label=" Apply Queue ",
                    callback=self._on_apply_queue_slots_clicked,
                )
                add_help_tooltip(apply_queue_button, "ACTIVE_DL_SLOTS")
                unlimited_slots = dpg.add_text("0 = Unlimited", color=(140, 140, 140))
                add_help_tooltip(unlimited_slots, "ACTIVE_DL_SLOTS")

            with dpg.group(horizontal=True):
                search_label = dpg.add_text("Search")
                add_help_tooltip(search_label, "QUEUE_SEARCH")
                self.queue_search_input = dpg.add_input_text(
                    hint="Filter torrent names...",
                    width=260,
                    callback=self._on_queue_filter_changed,
                )
                add_help_tooltip(self.queue_search_input, "QUEUE_SEARCH")
                dpg.add_spacer(width=8)
                status_filter_label = dpg.add_text("Status")
                add_help_tooltip(status_filter_label, "QUEUE_STATUS_FILTER")
                self.queue_state_filter = dpg.add_combo(
                    items=[
                        "All", "Active", "Downloading", "Seeding", "Checking",
                        "Queued", "Paused", "Stopped", "Completed", "Error",
                    ],
                    default_value="All",
                    width=135,
                    callback=self._on_queue_filter_changed,
                )
                add_help_tooltip(self.queue_state_filter, "QUEUE_STATUS_FILTER")
                clear_filter_button = dpg.add_button(label=" Clear Filter ", callback=self._clear_queue_filter)
                add_text_tooltip(clear_filter_button, "Clear filters\n\nRemoves the torrent-name search and status filter. This changes only what is visible in the queue and never changes transfer state.")
                queue_order_button = dpg.add_button(label=" Queue Order ", callback=self._clear_queue_sort)
                add_help_tooltip(queue_order_button, "QUEUE_ORDER")
                self.queue_filter_summary = dpg.add_text("Showing 0 / 0")
                add_help_tooltip(self.queue_filter_summary, "QUEUE_SORT")

            dpg.add_spacer(height=5)

            # Queue Table
            with dpg.child_window(height=140, border=True):
                dpg.add_text("TRANSFERS QUEUE", color=(100, 180, 255))
                with dpg.table(
                    header_row=True,
                    resizable=True,
                    sortable=True,
                    callback=self._on_queue_sort,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_outerH=True,
                    borders_innerV=True,
                    tag="torrent_queue_table",
                ) as self.queue_table:
                    name_col = dpg.add_table_column(
                        label="Name", width_stretch=True, init_width_or_weight=0.4
                    )
                    size_col = dpg.add_table_column(
                        label="Size", width_fixed=True, init_width_or_weight=90
                    )
                    progress_col = dpg.add_table_column(
                        label="Progress", width_fixed=True, init_width_or_weight=120
                    )
                    priority_col = dpg.add_table_column(
                        label="Priority", width_fixed=True, init_width_or_weight=90
                    )
                    status_col = dpg.add_table_column(
                        label="Status", width_fixed=True, init_width_or_weight=150
                    )
                    speed_col = dpg.add_table_column(
                        label="Down / Up", width_fixed=True, init_width_or_weight=190
                    )
                    self._sort_column_ids = {
                        name_col: "name",
                        size_col: "size",
                        progress_col: "progress",
                        priority_col: "priority",
                        status_col: "status",
                        speed_col: "speed",
                    }
                    add_text_tooltip(name_col, "Name\n\nThe torrent payload name. Click a column header to sort the visible table; click a row to select it. Right-click any row cell for torrent actions.")
                    add_text_tooltip(size_col, "Size\n\nTotal payload size described by the torrent metadata. This is not the size of the .torrent metadata file itself.")
                    add_text_tooltip(progress_col, "Progress\n\nVerified completion of the torrent payload. During selective downloading, the selected-files completion state can finish before the full torrent reaches 100%.")
                    add_help_tooltip(priority_col, "QUEUE_PRIORITY")
                    add_help_tooltip(status_col, "TORRENT_STATUS")
                    add_text_tooltip(speed_col, "Down / Up\n\nThe selected display unit is used for both the torrent's current download and upload rates. Right-click a torrent row to change Transfer Rate Units.")

            dpg.add_spacer(height=10)

            # Inspector
            with dpg.child_window(height=115, border=True):
                self.title_text = dpg.add_text(
                    "Torrent: Waiting for selection...",
                    color=(0, 255, 128),
                )
                add_text_tooltip(self.title_text, "Selected torrent\n\nThis inspector and the detail tabs below always describe the torrent currently selected in the transfer queue.")
                self.status_text = dpg.add_text(
                    "Status: Idle",
                    color=(180, 180, 180),
                )
                add_help_tooltip(self.status_text, "TORRENT_STATUS")
                dpg.add_spacer(height=5)

                self.progress_bar = dpg.add_progress_bar(
                    default_value=0.0,
                    width=-1,
                    height=22,
                )
                add_help_tooltip(self.progress_bar, "PIECE")
                self.progress_label = dpg.add_text(
                    "0.0% Complete (0 / 0 Pieces)",
                    color=(200, 200, 200),
                )
                add_help_tooltip(self.progress_label, "PIECE")

            dpg.add_spacer(height=10)

            # Selected-torrent detail views. General preserves the existing
            # inspector metrics while Peers exposes live connection telemetry.
            with dpg.tab_bar(callback=self._on_detail_tab_changed) as self.detail_tab_bar:
                with dpg.tab(label="General") as general_tab:
                    with dpg.group(horizontal=True):
                        with dpg.child_window(width=410, height=425, border=True):
                            transfer_heading = dpg.add_text("TRANSFER", color=(100, 180, 255))
                            add_text_tooltip(transfer_heading, "Transfer metrics\n\nLive payload rates, byte totals, remaining data, ETA, elapsed active time, share ratio and current connected-peer count for the selected torrent.")
                            dpg.add_separator()
                            self.speed_text = dpg.add_text("Download Speed: 0.0 KB/s")
                            self.upload_speed_text = dpg.add_text("Upload Speed: 0.0 KB/s")
                            add_help_tooltip(self.speed_text, "TRANSFER_RATE")
                            add_help_tooltip(self.upload_speed_text, "TRANSFER_RATE")
                            self.downloaded_text = dpg.add_text("Downloaded: 0 B / 0 B")
                            add_help_tooltip(self.downloaded_text, "DOWNLOADED")
                            self.remaining_text = dpg.add_text("Remaining: 0 B")
                            add_help_tooltip(self.remaining_text, "REMAINING")
                            self.uploaded_text = dpg.add_text("Uploaded Total: 0 B")
                            add_help_tooltip(self.uploaded_text, "UPLOADED")
                            self.uploaded_session_text = dpg.add_text("Uploaded This Session: 0 B")
                            add_help_tooltip(self.uploaded_session_text, "UPLOADED_SESSION")
                            self.upload_requests_text = dpg.add_text("Upload Requests: 0 served / 0 received")
                            add_help_tooltip(self.upload_requests_text, "UPLOAD_REQUESTS")
                            self.last_upload_text = dpg.add_text("Last Upload: --")
                            add_help_tooltip(self.last_upload_text, "LAST_UPLOAD")
                            self.eta_text = dpg.add_text("ETA: --")
                            add_help_tooltip(self.eta_text, "ETA")
                            self.elapsed_text = dpg.add_text("Active Time: 00:00")
                            add_help_tooltip(self.elapsed_text, "ELAPSED")
                            self.ratio_text = dpg.add_text("Share Ratio: --")
                            add_help_tooltip(self.ratio_text, "SHARE_RATIO")
                            self.peers_text = dpg.add_text("Connected Peers: 0")
                            add_help_tooltip(self.peers_text, "CONNECTED_PEERS")
                            self.error_text = dpg.add_text("", color=(255, 105, 105), wrap=390)
                            add_text_tooltip(self.error_text, "Error / Notice\n\nWhen SalixTorrent encounters a recoverable problem, the human-readable reason appears here. Use it to understand what failed before choosing Retry.")
                            self.retry_button = dpg.add_button(
                                label=" Retry Torrent ",
                                enabled=False,
                                callback=lambda: self._on_resume_clicked(),
                            )
                            add_help_tooltip(self.retry_button, "RETRY_TORRENT")

                        with dpg.child_window(width=430, height=425, border=True):
                            swarm_heading = dpg.add_text("SWARM STATUS", color=(255, 200, 100))
                            add_text_tooltip(swarm_heading, "Swarm status\n\nHow the selected torrent is participating in the BitTorrent swarm: lifecycle state, discovery, peers, availability, connectivity and storage mode.")
                            dpg.add_separator()
                            self.state_text = dpg.add_text("Session State: Idle")
                            add_help_tooltip(self.state_text, "SESSION_STATE")
                            self.client_id_text = dpg.add_text("Client ID: Salix_T 1.0")
                            add_text_tooltip(self.client_id_text, "Client ID\n\nThe peer identity prefix SalixTorrent presents during BitTorrent handshakes. Remote clients can use peer IDs and extension metadata to identify the software they are connected to.")
                            self.seed_leech_text = dpg.add_text("Seeds / Leechers: -- / --")
                            add_help_tooltip(self.seed_leech_text, "SEEDS_LEECHERS")
                            self.availability_text = dpg.add_text("Availability: --")
                            add_help_tooltip(self.availability_text, "AVAILABILITY")
                            self.discovery_text = dpg.add_text("Discovery: --")
                            add_help_tooltip(self.discovery_text, "DISCOVERY")
                            self.listen_port_text = dpg.add_text("Listen Port: --")
                            add_help_tooltip(self.listen_port_text, "LISTEN_PORT")
                            self.listener_endpoint_text = dpg.add_text("Listener: --")
                            add_help_tooltip(self.listener_endpoint_text, "LISTENER_ENDPOINT")
                            self.transport_text = dpg.add_text("Transport: --")
                            add_help_tooltip(self.transport_text, "TRANSPORT_SECURITY")
                            self.network_path_text = dpg.add_text("Network Path: --")
                            add_help_tooltip(self.network_path_text, "NETWORK_BINDING")
                            self.connectivity_text = dpg.add_text("Incoming: --")
                            add_help_tooltip(self.connectivity_text, "PORT_MAPPING")
                            self.incoming_peers_text = dpg.add_text("Incoming Peers: 0 active / 0 this session")
                            add_help_tooltip(self.incoming_peers_text, "INCOMING_CONNECTIONS")
                            self.mapping_methods_text = dpg.add_text("Mapping Methods: UPnP -- | NAT-PMP --")
                            add_help_tooltip(self.mapping_methods_text, "MAPPING_METHOD_STATUS")
                            self.mapping_detail_text = dpg.add_text("Mapping Detail: --", wrap=405)
                            add_help_tooltip(self.mapping_detail_text, "MAPPING_DIAGNOSIS")
                            self.connectivity_hint_text = dpg.add_text("Connectivity Hint: --", color=(155, 155, 160), wrap=405)
                            add_help_tooltip(self.connectivity_hint_text, "CONNECTIVITY_ACTION")
                            self.external_port_text = dpg.add_text("External: --")
                            add_help_tooltip(self.external_port_text, "EXTERNAL_ENDPOINT")
                            self.storage_text = dpg.add_text("Storage: Downloads")
                            add_help_tooltip(self.storage_text, "STORAGE_MODE")
                            self.lpd_text = dpg.add_text("LAN Discovery: --")
                            add_help_tooltip(self.lpd_text, "LPD")
                            self.health_text = dpg.add_text("Swarm Health: --")
                            add_help_tooltip(self.health_text, "SWARM_HEALTH")

                            dpg.add_spacer(height=5)
                            dpg.add_separator()
                            limits_heading = dpg.add_text("TRANSFER LIMITS", color=(180, 160, 255))
                            add_help_tooltip(limits_heading, "TRANSFER_LIMITS")
                            limits_unlimited = dpg.add_text("0 = Unlimited", color=(150, 150, 150))
                            add_help_tooltip(limits_unlimited, "TRANSFER_LIMITS")

                            with dpg.group(horizontal=True):
                                dpg.add_text("Down")
                                self.download_limit_input = dpg.add_input_float(
                                    default_value=0.0,
                                    min_value=0.0,
                                    min_clamped=True,
                                    format="%.2f",
                                    width=95,
                                )
                                self.download_limit_unit = dpg.add_combo(
                                    items=["KB/s", "MB/s", "kbps", "Mbps"],
                                    default_value="KB/s",
                                    width=80,
                                )
                                add_help_tooltip(self.download_limit_input, "TRANSFER_LIMITS")
                                add_help_tooltip(self.download_limit_unit, "TRANSFER_LIMITS")

                            with dpg.group(horizontal=True):
                                dpg.add_text("Up  ")
                                self.upload_limit_input = dpg.add_input_float(
                                    default_value=0.0,
                                    min_value=0.0,
                                    min_clamped=True,
                                    format="%.2f",
                                    width=95,
                                )
                                self.upload_limit_unit = dpg.add_combo(
                                    items=["KB/s", "MB/s", "kbps", "Mbps"],
                                    default_value="KB/s",
                                    width=80,
                                )
                                add_help_tooltip(self.upload_limit_input, "TRANSFER_LIMITS")
                                add_help_tooltip(self.upload_limit_unit, "TRANSFER_LIMITS")

                            with dpg.group(horizontal=True):
                                apply_limits_button = dpg.add_button(label=" Apply Limits ", callback=self._on_apply_limits_clicked)
                                add_help_tooltip(apply_limits_button, "TRANSFER_LIMITS")
                                unlimited_limits_button = dpg.add_button(label=" Unlimited ", callback=self._on_unlimited_limits_clicked)
                                add_help_tooltip(unlimited_limits_button, "TRANSFER_LIMITS")

                            self.limit_status_text = dpg.add_text(
                                "Limits: Down Unlimited | Up Unlimited",
                                color=(170, 170, 170),
                            )
                            add_help_tooltip(self.limit_status_text, "TRANSFER_LIMITS")

                        with dpg.child_window(width=-1, height=425, border=True):
                            torrent_info_heading = dpg.add_text("TORRENT INFO", color=(0, 255, 128))
                            add_text_tooltip(torrent_info_heading, "Torrent metadata\n\nDescriptive and protocol metadata read from the .torrent or resolved magnet, plus the local storage and cached metadata paths used by SalixTorrent.")
                            dpg.add_separator()
                            self.info_hash_text = dpg.add_text("Info Hash: --", wrap=500)
                            add_help_tooltip(self.info_hash_text, "INFO_HASH")
                            self.piece_info_text = dpg.add_text("Pieces: --")
                            add_help_tooltip(self.piece_info_text, "PIECE")
                            self.file_info_text = dpg.add_text("Files: --")
                            add_help_tooltip(self.file_info_text, "FILE_COUNT")
                            self.private_text = dpg.add_text("Private: --")
                            add_help_tooltip(self.private_text, "PRIVATE_TORRENT")
                            self.created_by_text = dpg.add_text("Created By: --", wrap=500)
                            add_help_tooltip(self.created_by_text, "CREATED_BY")
                            self.created_date_text = dpg.add_text("Created: --")
                            add_help_tooltip(self.created_date_text, "CREATION_DATE")
                            self.comment_text = dpg.add_text("Comment: --", wrap=500)
                            add_help_tooltip(self.comment_text, "TORRENT_COMMENT")
                            dpg.add_spacer(height=4)
                            dpg.add_separator()
                            self.storage_path_text = dpg.add_text("Storage Path: --", wrap=500)
                            add_help_tooltip(self.storage_path_text, "STORAGE_PATH")
                            self.torrent_path_text = dpg.add_text(".torrent: --", wrap=500)
                            add_help_tooltip(self.torrent_path_text, "TORRENT_PATH")
                            dpg.add_spacer(height=6)
                            with dpg.group(horizontal=True):
                                open_folder_button = dpg.add_button(label=" Open Folder ", callback=self._on_open_folder_clicked)
                                add_help_tooltip(open_folder_button, "OPEN_FOLDER")
                                properties_button = dpg.add_button(label=" Properties... ", callback=self._on_properties_clicked)
                                add_help_tooltip(properties_button, "PROPERTIES")

                with dpg.tab(label="Peers") as peers_tab:
                    self.peer_view.build_view(parent_tag=peers_tab)

                with dpg.tab(label="Pieces") as pieces_tab:
                    self.piece_view.build_view(parent_tag=pieces_tab)

                with dpg.tab(label="Files") as files_tab:
                    self.file_view.build_view(parent_tag=files_tab)

                with dpg.tab(label="Sources") as sources_tab:
                    self.source_view.build_view(parent_tag=sources_tab)

                with dpg.tab(label="Speed") as speed_tab:
                    self.speed_view.build_view(parent_tag=speed_tab)

            self._detail_tab_ids = {
                general_tab: "General",
                peers_tab: "Peers",
                pieces_tab: "Pieces",
                files_tab: "Files",
                sources_tab: "Sources",
                speed_tab: "Speed",
            }
            add_text_tooltip(general_tab, "General\n\nOverall transfer, swarm, connectivity and torrent metadata for the selected torrent.")
            add_text_tooltip(peers_tab, "Peers\n\nLive BitTorrent peer connections: client identity, discovery source, direction, piece completion, per-peer rates and protocol state.")
            add_text_tooltip(pieces_tab, "Pieces\n\nA compact map and focused table showing piece verification, requests, blocks and current swarm availability.")
            add_text_tooltip(files_tab, "Files\n\nPer-file verified progress, storage paths and selective-download priority controls for the selected torrent.")
            add_text_tooltip(sources_tab, "Sources\n\nTrackers, DHT, PEX and Local Peer Discovery with live status and discovery diagnostics.")
            add_text_tooltip(speed_tab, "Speed\n\nRolling download/upload history, recent averages, peaks and transfer-limit reference lines.")

        with dpg.window(
            label="Open Magnet Link",
            modal=True,
            show=False,
            no_resize=True,
            width=680,
            height=285,
        ) as self.magnet_modal:
            dpg.add_text("MAGNET LINK", color=(0, 255, 128))
            dpg.add_text(
                "Paste a BitTorrent v1 magnet link. SalixTorrent will discover peers "
                "through its trackers, DHT and LAN, then retrieve BEP-9 metadata.",
                color=(160, 160, 165),
                wrap=630,
            )
            dpg.add_spacer(height=5)
            self.magnet_input = dpg.add_input_text(
                multiline=True,
                height=70,
                width=-1,
                hint="magnet:?xt=urn:btih:...",
            )
            add_help_tooltip(self.magnet_input, "MAGNET_LINK")
            with dpg.group(horizontal=True):
                self.magnet_add_button = dpg.add_button(
                    label=" Add Magnet ",
                    callback=self._submit_magnet,
                )
                add_help_tooltip(self.magnet_add_button, "OPEN_MAGNET")
                paste_magnet_button = dpg.add_button(label=" Paste ", callback=self._paste_magnet)
                add_text_tooltip(paste_magnet_button, "Paste magnet link\n\nCopies the current clipboard text into the magnet field. SalixTorrent does not begin network activity until Add Magnet is pressed.")
                self.magnet_cancel_button = dpg.add_button(
                    label=" Cancel Lookup ",
                    enabled=False,
                    callback=self._cancel_magnet,
                )
                add_help_tooltip(self.magnet_cancel_button, "BEP9")
                dpg.add_button(
                    label=" Close ",
                    callback=self._close_magnet_dialog,
                )
            self.magnet_progress = dpg.add_progress_bar(
                default_value=0.0,
                width=-1,
                overlay="Idle",
            )
            add_help_tooltip(self.magnet_progress, "BEP9")
            self.magnet_status_text = dpg.add_text(
                "Paste a magnet link to begin.",
                wrap=630,
            )
            add_help_tooltip(self.magnet_status_text, "BEP9")

        # Shared confirmation dialog for destructive queue actions.
        with dpg.window(
            label="Remove Torrent",
            modal=True,
            show=False,
            no_resize=True,
            width=520,
            height=230,
        ) as self.remove_torrent_modal:
            self.remove_torrent_title = dpg.add_text(
                "Remove torrent?",
                color=(255, 200, 100),
            )
            dpg.add_spacer(height=4)
            self.remove_torrent_message = dpg.add_text(
                "",
                wrap=480,
            )
            dpg.add_spacer(height=8)
            dpg.add_separator()
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                remove_only_button = dpg.add_button(
                    label=" Remove from SalixTorrent ",
                    callback=lambda: self._confirm_remove_torrent(False),
                )
                add_help_tooltip(remove_only_button, "REMOVE_TORRENT")
                remove_delete_button = dpg.add_button(
                    label=" Remove + Delete Data ",
                    callback=lambda: self._confirm_remove_torrent(True),
                )
                add_help_tooltip(remove_delete_button, "DELETE_DATA")
                cancel_remove_button = dpg.add_button(
                    label=" Cancel ",
                    callback=lambda: dpg.hide_item(self.remove_torrent_modal),
                )
                add_text_tooltip(cancel_remove_button, "Cancel removal\n\nCloses this confirmation window without changing the torrent, payload, resume data or queue.")

        with dpg.window(
            label="Removal Notice",
            modal=True,
            show=False,
            no_resize=True,
            width=520,
            height=170,
        ) as self.remove_notice_modal:
            self.remove_notice_text = dpg.add_text("", wrap=480)
            dpg.add_spacer(height=10)
            dpg.add_button(
                label=" OK ",
                callback=lambda: dpg.hide_item(self.remove_notice_modal),
            )

        with dpg.window(
            label="Force Recheck",
            modal=True,
            show=False,
            no_resize=True,
            width=560,
            height=190,
        ) as self.recheck_modal:
            self.recheck_title = dpg.add_text("Force recheck?", color=(255, 200, 100))
            add_help_tooltip(self.recheck_title, "FORCE_RECHECK")
            dpg.add_spacer(height=4)
            dpg.add_text(
                "This discards SalixTorrent's fast-resume trust and SHA-1 checks the "
                "existing payload again. No downloaded data is deleted. An active "
                "torrent will resume automatically after a successful recheck.",
                wrap=520,
            )
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                force_recheck_button = dpg.add_button(label=" Force Recheck ", callback=self._confirm_force_recheck)
                add_help_tooltip(force_recheck_button, "FORCE_RECHECK")
                cancel_recheck_button = dpg.add_button(label=" Cancel ", callback=lambda: dpg.hide_item(self.recheck_modal))
                add_text_tooltip(cancel_recheck_button, "Cancel recheck\n\nCloses this confirmation window without invalidating fast-resume state or starting a verification pass.")

        with dpg.window(
            label="Torrent Properties",
            modal=True,
            show=False,
            width=720,
            height=520,
        ) as self.properties_modal:
            self.properties_title = dpg.add_text("Torrent Properties", color=(0, 255, 128))
            dpg.add_separator()
            with dpg.child_window(height=400, border=False):
                self.properties_text = dpg.add_text("", wrap=660)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                properties_hash_button = dpg.add_button(label=" Copy Info Hash ", callback=self._properties_copy_info_hash)
                add_help_tooltip(properties_hash_button, "COPY_INFO_HASH")
                properties_magnet_button = dpg.add_button(label=" Copy Magnet Link ", callback=self._properties_copy_magnet)
                add_help_tooltip(properties_magnet_button, "COPY_MAGNET")
                properties_folder_button = dpg.add_button(label=" Open Folder ", callback=self._properties_open_folder)
                add_help_tooltip(properties_folder_button, "OPEN_FOLDER")
                dpg.add_button(label=" Close ", callback=lambda: dpg.hide_item(self.properties_modal))

        with dpg.window(
            label="Download Complete",
            show=False,
            no_resize=True,
            width=480,
            height=150,
        ) as self.completion_notice_modal:
            self.completion_notice_title = dpg.add_text(
                "Download completed", color=(0, 255, 128)
            )
            self.completion_notice_text = dpg.add_text("", wrap=440)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                completion_folder_button = dpg.add_button(label=" Open Folder ", callback=self._completion_open_folder)
                add_help_tooltip(completion_folder_button, "OPEN_FOLDER")
                dpg.add_button(label=" Dismiss ", callback=lambda: dpg.hide_item(self.completion_notice_modal))

    def _on_detail_tab_changed(self, sender=None, app_data=None, user_data=None):
        """Render a detail view only when the user actually selects that tab."""
        del user_data

        selected = app_data
        if selected not in self._detail_tab_ids and sender is not None:
            try:
                selected = dpg.get_value(sender)
            except Exception:
                selected = app_data

        tab_name = self._detail_tab_ids.get(selected)
        if tab_name is None and isinstance(selected, str):
            # Defensive fallback for Dear PyGui builds that return a label.
            candidate = selected.strip()
            if candidate in self.DETAIL_RENDER_INTERVALS:
                tab_name = candidate

        if not tab_name:
            return

        self._active_detail_tab = tab_name
        if self.active_info_hash:
            snapshot = self.latest_stats.get(self.active_info_hash)
            if snapshot:
                self._render_active_detail(snapshot, force=True)

    def _render_active_detail(self, msg: dict, force: bool = False):
        """Update only the visible heavy detail tab.

        General's text fields are updated by _render_inspector itself. The
        table/map/plot tabs are intentionally lazy and rate-limited.
        """
        tab = self._active_detail_tab
        if tab == "General":
            return

        info_hash = str(msg.get("info_hash") or "")
        now = time.monotonic()
        key = (tab, info_hash)
        interval = float(self.DETAIL_RENDER_INTERVALS.get(tab, 1.0))
        last = float(self._detail_last_render_at.get(key, 0.0))
        if not force and interval > 0.0 and now - last < interval:
            return

        if tab == "Peers":
            self.peer_view.render(msg)
        elif tab == "Pieces":
            self.piece_view.render(msg)
        elif tab == "Files":
            self.file_view.render(msg)
        elif tab == "Sources":
            self.source_view.render(msg)
        elif tab == "Speed":
            self.speed_view.render(msg)
        else:
            return

        self._detail_last_render_at[key] = now

    def _show_magnet_dialog(self):
        self._magnet_close_at = 0.0
        dpg.set_value(self.magnet_progress, 0.0)
        dpg.configure_item(self.magnet_progress, overlay="Idle")
        dpg.set_value(self.magnet_status_text, "Paste a magnet link to begin.")
        dpg.configure_item(self.magnet_add_button, enabled=True)
        dpg.configure_item(self.magnet_cancel_button, enabled=False)
        dpg.show_item(self.magnet_modal)
        try:
            width = 680
            height = 285
            x = max(0, (dpg.get_viewport_client_width() - width) // 2)
            y = max(0, (dpg.get_viewport_client_height() - height) // 2)
            dpg.set_item_pos(self.magnet_modal, [x, y])
        except Exception:
            pass

    def _paste_magnet(self):
        try:
            value = dpg.get_clipboard_text() or ""
        except Exception:
            value = ""
        if value:
            dpg.set_value(self.magnet_input, value.strip())

    def _submit_magnet(self):
        magnet_uri = str(dpg.get_value(self.magnet_input) or "").strip()
        try:
            info_hash = self.manager.add_magnet(magnet_uri, start=True)
        except Exception as exc:
            dpg.set_value(self.magnet_status_text, f"Error: {exc}")
            dpg.set_value(self.magnet_progress, 0.0)
            dpg.configure_item(self.magnet_progress, overlay="Error")
            return

        self._magnet_info_hash = info_hash
        self._magnet_close_at = 0.0
        dpg.configure_item(self.magnet_add_button, enabled=False)
        dpg.configure_item(self.magnet_cancel_button, enabled=True)
        dpg.set_value(self.magnet_progress, 0.01)
        dpg.configure_item(self.magnet_progress, overlay="Starting")
        dpg.set_value(
            self.magnet_status_text,
            f"Resolving metadata for {info_hash[:12]}...",
        )

    def _cancel_magnet(self):
        if self._magnet_info_hash:
            self.manager.cancel_magnet(self._magnet_info_hash)
        dpg.configure_item(self.magnet_cancel_button, enabled=False)
        dpg.set_value(self.magnet_status_text, "Cancelling magnet lookup...")

    def _close_magnet_dialog(self):
        if self._magnet_info_hash:
            self.manager.cancel_magnet(self._magnet_info_hash)
        self._magnet_info_hash = ""
        self._magnet_close_at = 0.0
        dpg.hide_item(self.magnet_modal)

    def _handle_magnet_event(self, msg: dict):
        event_type = str(msg.get("type") or "")
        info_hash = str(msg.get("info_hash") or "")
        if info_hash:
            self._magnet_info_hash = info_hash

        progress = max(0.0, min(1.0, float(msg.get("progress", 0.0) or 0.0)))
        stage = str(msg.get("stage") or "Magnet")
        message = str(msg.get("message") or "")

        if hasattr(self, "magnet_progress") and dpg.does_item_exist(self.magnet_progress):
            dpg.set_value(self.magnet_progress, progress)
            dpg.configure_item(
                self.magnet_progress,
                overlay=f"{stage} {progress * 100:.0f}%" if 0.0 < progress < 1.0 else stage,
            )
            dpg.set_value(self.magnet_status_text, message or stage)

        if event_type == "MAGNET_READY":
            dpg.configure_item(self.magnet_add_button, enabled=True)
            dpg.configure_item(self.magnet_cancel_button, enabled=False)
            self._magnet_close_at = time.monotonic() + 1.25
            if info_hash:
                self._removed_info_hashes.discard(info_hash)
                self._select_torrent(info_hash)
        elif event_type in {"MAGNET_ERROR", "MAGNET_CANCELLED"}:
            dpg.configure_item(self.magnet_add_button, enabled=True)
            dpg.configure_item(self.magnet_cancel_button, enabled=False)
            self._magnet_close_at = 0.0
            if event_type == "MAGNET_CANCELLED":
                self._magnet_info_hash = ""

    def _open_native_file_dialog(self):
        """Native Windows file picker (instant, zero DPG selection bugs)."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Select Torrent File",
            filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")],
        )
        root.destroy()

        if file_path and os.path.exists(file_path):
            session = self.manager.add_torrent(file_path)
            self._removed_info_hashes.discard(session.torrent.hex_info_hash)
            self._select_torrent(session.torrent.hex_info_hash)
            self.manager.start_torrent(session.torrent.hex_info_hash)

    def _on_resume_clicked(self):
        if self.active_info_hash:
            self.manager.resume_torrent(self.active_info_hash)

    def _on_pause_clicked(self):
        if self.active_info_hash:
            self.manager.pause_torrent(self.active_info_hash)

    def _on_stop_clicked(self):
        if self.active_info_hash:
            self.manager.stop_torrent(self.active_info_hash)

    def _on_apply_limits_clicked(self):
        if not self.active_info_hash:
            return

        self.manager.set_transfer_limits(
            self.active_info_hash,
            dpg.get_value(self.download_limit_input),
            dpg.get_value(self.download_limit_unit),
            dpg.get_value(self.upload_limit_input),
            dpg.get_value(self.upload_limit_unit),
        )

    def _on_unlimited_limits_clicked(self):
        dpg.set_value(self.download_limit_input, 0.0)
        dpg.set_value(self.upload_limit_input, 0.0)
        self._on_apply_limits_clicked()

    def _on_apply_queue_slots_clicked(self):
        value = max(0, int(dpg.get_value(self.queue_slots_input) or 0))
        dpg.set_value(self.queue_slots_input, value)
        self._queue_slots_value = value
        self.manager.set_max_active_downloads(value)

    @staticmethod
    def _format_bytes(value: object) -> str:
        try:
            size = max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            size = 0.0
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        unit = units[0]
        for candidate in units:
            unit = candidate
            if size < 1024.0 or candidate == units[-1]:
                break
            size /= 1024.0
        if unit == "B":
            return f"{size:.0f} {unit}"
        return f"{size:,.2f} {unit}"

    @staticmethod
    def _format_duration(seconds: object) -> str:
        if seconds is None:
            return "--"
        try:
            total = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "--"
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        if days:
            return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_age(seconds: object) -> str:
        if seconds is None:
            return "--"
        try:
            total = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "--"
        if total < 60:
            return f"{total}s ago"
        if total < 3600:
            minutes, secs = divmod(total, 60)
            return f"{minutes}m {secs:02d}s ago"
        hours, rem = divmod(total, 3600)
        minutes = rem // 60
        if hours < 24:
            return f"{hours}h {minutes:02d}m ago"
        days, hours = divmod(hours, 24)
        return f"{days}d {hours:02d}h ago"

    @staticmethod
    def _format_creation_date(timestamp: object) -> str:
        try:
            value = int(timestamp or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return "--"
        try:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return "--"

    def _on_queue_filter_changed(self, sender=None, app_data=None, user_data=None):
        self._search_query = str(dpg.get_value(self.queue_search_input) or "").strip().lower()
        self._state_filter = str(dpg.get_value(self.queue_state_filter) or "All")
        self._apply_queue_filters()

    def _clear_queue_filter(self):
        dpg.set_value(self.queue_search_input, "")
        dpg.set_value(self.queue_state_filter, "All")
        self._search_query = ""
        self._state_filter = "All"
        self._apply_queue_filters()

    def _on_queue_sort(self, sender, sort_specs):
        del sender
        self._sort_specs = sort_specs
        self._apply_queue_sort()
        self._apply_queue_filters()

    def _clear_queue_sort(self):
        self._sort_specs = None
        self._apply_queue_sort()
        self._apply_queue_filters()

    def _queue_sort_value(self, info_hash: str, key: str):
        stats = self.latest_stats.get(info_hash, {})
        if key == "name":
            return str(stats.get("torrent_name") or "").lower()
        if key == "size":
            return int(stats.get("total_bytes") or 0)
        if key == "progress":
            return float(stats.get("progress") or 0.0)
        if key == "priority":
            rank = {"High": 0, "Normal": 1, "Low": 2}
            return rank.get(str(stats.get("queue_priority") or "Normal"), 1)
        if key == "status":
            return str(stats.get("state_label") or stats.get("state") or "").lower()
        if key == "speed":
            return (
                float(stats.get("speed_kbps") or 0.0),
                float(stats.get("upload_speed_kbps") or 0.0),
            )
        return 0

    def _apply_queue_sort(self):
        if not hasattr(self, "queue_table") or not dpg.does_item_exist(self.queue_table):
            return

        order = [h for h in self.torrent_order if h in self.torrent_rows]
        specs = self._sort_specs
        if specs:
            # Dear PyGui supports multi-column sort specs. Apply them in reverse
            # order so Python's stable sort preserves the higher-priority key.
            for column_id, direction in reversed(list(specs)):
                key = self._sort_column_ids.get(column_id)
                if not key:
                    continue
                order.sort(
                    key=lambda h, k=key: self._queue_sort_value(h, k),
                    reverse=int(direction) < 0,
                )

        row_ids = [self.torrent_rows[h]["row"] for h in order]
        if row_ids:
            try:
                dpg.reorder_items(self.queue_table, 1, row_ids)
            except Exception:
                pass

    def _row_matches_filter(self, info_hash: str) -> bool:
        stats = self.latest_stats.get(info_hash, {})
        name = str(stats.get("torrent_name") or "").lower()
        if self._search_query and self._search_query not in name:
            return False

        state = str(stats.get("state") or "Idle")
        wanted = self._state_filter
        if wanted == "All":
            return True
        if wanted == "Active":
            return state in {"Queued", "Checking", "Fast Resume", "Downloading", "Seeding"}
        return state == wanted

    def _apply_queue_filters(self):
        visible = 0
        for info_hash, row in self.torrent_rows.items():
            show = self._row_matches_filter(info_hash)
            if dpg.does_item_exist(row["row"]):
                dpg.configure_item(row["row"], show=show)
            if show:
                visible += 1
        if hasattr(self, "queue_filter_summary") and dpg.does_item_exist(self.queue_filter_summary):
            sort_suffix = ""
            if self._sort_specs:
                try:
                    column_id, direction = self._sort_specs[0]
                    key = self._sort_column_ids.get(column_id, "")
                    if key:
                        sort_suffix = f" | Sort: {key.title()} {'ASC' if int(direction) > 0 else 'DESC'}"
                except Exception:
                    sort_suffix = ""
            dpg.set_value(
                self.queue_filter_summary,
                f"Showing {visible} / {len(self.torrent_rows)}{sort_suffix}",
            )

    @staticmethod
    def _folder_for_stats(stats: dict) -> str:
        path = str(stats.get("storage_path") or stats.get("download_dir") or "").strip()
        if not path:
            return ""
        if bool(stats.get("is_multi_file")) or os.path.isdir(path):
            folder = path
        else:
            folder = os.path.dirname(path) or path
        return os.path.abspath(folder)

    @staticmethod
    def _open_folder_path(folder: str) -> bool:
        folder = os.path.abspath(os.path.expanduser(str(folder or "")))
        if not folder or not os.path.isdir(folder):
            return False
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            return True
        except Exception:
            return False

    def _open_folder_for_hash(self, info_hash: str):
        stats = self.latest_stats.get(info_hash, {})
        folder = self._folder_for_stats(stats)
        if folder:
            self._open_folder_path(folder)

    def _on_open_folder_clicked(self):
        if self.active_info_hash:
            self._open_folder_for_hash(self.active_info_hash)

    def _on_properties_clicked(self):
        if self.active_info_hash:
            self._show_properties(self.active_info_hash)

    def _copy_text(self, value: object):
        text = str(value or "")
        if text:
            try:
                dpg.set_clipboard_text(text)
            except Exception:
                pass

    def _show_properties(self, info_hash: str):
        stats = self.latest_stats.get(info_hash, {})
        if not stats:
            return
        self._select_torrent(info_hash)
        dpg.set_value(self.properties_title, f"Torrent Properties - {stats.get('torrent_name', '')}")

        trackers = list(stats.get("trackers") or [])
        tracker_text = "\n    ".join(trackers) if trackers else "--"
        ratio = stats.get("share_ratio")
        ratio_text = f"{float(ratio):.3f}" if ratio is not None else "--"
        seeders = stats.get("swarm_seeders")
        leechers = stats.get("swarm_leechers")
        properties = (
            f"Name: {stats.get('torrent_name', '--')}\n"
            f"State: {stats.get('state_label', stats.get('state', '--'))}\n"
            f"Info Hash: {stats.get('info_hash', '--')}\n"
            f"Private: {'Yes' if stats.get('private') else 'No'}\n"
            f"Total Size: {self._format_bytes(stats.get('total_bytes'))}\n"
            f"Downloaded: {self._format_bytes(stats.get('downloaded_bytes'))}\n"
            f"Uploaded Total: {self._format_bytes(stats.get('uploaded_bytes'))}\n"
            f"Uploaded This Session: {self._format_bytes(stats.get('uploaded_this_session_bytes'))}\n"
            f"Upload Requests: {int(stats.get('upload_requests_served', 0) or 0)} served / "
            f"{int(stats.get('upload_requests_received', 0) or 0)} received\n"
            f"Last Upload: {self._format_age(stats.get('last_upload_seconds'))}\n"
            f"Share Ratio: {ratio_text}\n"
            f"Pieces: {stats.get('total_pieces', 0)} x {self._format_bytes(stats.get('piece_length'))}\n"
            f"Files: {stats.get('file_count', 0)}\n"
            f"Seeds / Leechers: {seeders if seeders is not None else '--'} / "
            f"{leechers if leechers is not None else '--'}\n"
            f"Availability: {float(stats.get('swarm_availability', 0.0) or 0.0):.2f}\n"
            f"Discovery: {stats.get('discovery_summary', '--')}\n"
            f"Active Time: {self._format_duration(stats.get('elapsed_seconds'))}\n"
            f"Incoming Peers: {int(stats.get('incoming_peers', 0) or 0)} active / "
            f"{int(stats.get('incoming_connections_total', 0) or 0)} this session\n"
            f"ETA: {self._format_duration(stats.get('eta_seconds'))}\n\n"
            f"Storage Mode: {stats.get('storage_mode', '--')}\n"
            f"Storage Path: {stats.get('storage_path', '--')}\n"
            f".torrent File: {stats.get('torrent_path', '--')}\n\n"
            f"Created By: {stats.get('created_by') or '--'}\n"
            f"Created: {self._format_creation_date(stats.get('creation_date'))}\n"
            f"Comment: {stats.get('comment') or '--'}\n\n"
            f"Trackers:\n    {tracker_text}"
        )
        dpg.set_value(self.properties_text, properties)
        dpg.show_item(self.properties_modal)

    def _properties_copy_info_hash(self):
        if self.active_info_hash:
            self._copy_text(self.latest_stats.get(self.active_info_hash, {}).get("info_hash"))

    def _properties_copy_magnet(self):
        if self.active_info_hash:
            self._copy_text(self.latest_stats.get(self.active_info_hash, {}).get("magnet_uri"))

    def _properties_open_folder(self):
        if self.active_info_hash:
            self._open_folder_for_hash(self.active_info_hash)

    def _completion_open_folder(self):
        if self._completion_notice_info_hash:
            self._open_folder_for_hash(self._completion_notice_info_hash)

    def _show_completion_notice(self, info_hash: str, stats: dict):
        settings = self.manager.get_app_settings()
        torrent_name = stats.get("torrent_name", "Torrent")
        state = stats.get("state_label", stats.get("state", "Completed"))
        downloaded = self._format_bytes(stats.get("downloaded_bytes"))

        # Native desktop notifications are independent from the in-app popup.
        # This lets users keep Windows notifications while disabling the modal,
        # or vice versa. The Windows backend uses the native shell tray API.
        if settings.get("native_notifications", True):
            self.desktop.notify(
                "SalixTorrent - Download complete",
                f"{torrent_name} - {state} ({downloaded})",
            )

        if not self.manager.completion_notifications_enabled():
            return

        self._completion_notice_info_hash = info_hash
        dpg.set_value(
            self.completion_notice_title,
            f"Download completed - {torrent_name}",
        )
        dpg.set_value(
            self.completion_notice_text,
            f"{state}. Downloaded {downloaded}. "
            "You can open the payload folder now or dismiss this notice.",
        )
        dpg.show_item(self.completion_notice_modal)

    def _request_force_recheck(self, info_hash: str):
        if info_hash not in self.torrent_rows:
            return
        self._select_torrent(info_hash)
        self._pending_recheck_info_hash = info_hash
        stats = self.latest_stats.get(info_hash, {})
        dpg.set_value(
            self.recheck_title,
            f"Force Recheck - {stats.get('torrent_name', 'Torrent')}",
        )
        dpg.show_item(self.recheck_modal)

    def _confirm_force_recheck(self):
        info_hash = self._pending_recheck_info_hash
        self._pending_recheck_info_hash = ""
        dpg.hide_item(self.recheck_modal)
        if info_hash:
            self.manager.force_recheck(info_hash)

    # ------------------------------------------------------------------
    # Torrent row context menu
    # ------------------------------------------------------------------

    def _build_row_context_menu(self, info_hash: str, row_cells):
        """Create one in-place right-click context menu for a torrent row.

        Dear PyGui's dpg.popup() helper installs its own item-handler registry.
        Binding a second registry to the same item replaces that popup binding,
        so the menu never opens.  Build the popup window explicitly instead and
        use one registry to both select the row and show the context menu.
        """
        with dpg.window(
            popup=True,
            show=False,
            autosize=True,
            no_title_bar=True,
        ) as popup_id:
            move_up_item = dpg.add_menu_item(
                label="Move Up",
                user_data=info_hash,
                callback=lambda s, a, u: self._move_torrent_up(u),
            )
            move_down_item = dpg.add_menu_item(
                label="Move Down",
                user_data=info_hash,
                callback=lambda s, a, u: self._move_torrent_down(u),
            )

            dpg.add_separator()

            priority_high_item = dpg.add_menu_item(
                label="Priority: High",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_set_priority(u, "High"),
            )
            priority_normal_item = dpg.add_menu_item(
                label="Priority: Normal",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_set_priority(u, "Normal"),
            )
            priority_low_item = dpg.add_menu_item(
                label="Priority: Low",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_set_priority(u, "Low"),
            )

            with dpg.menu(label="Transfer Rate Units") as rate_menu:
                rate_items = {}
                rate_labels = {
                    "Auto": "Automatic",
                    "KB/s": "KB/s - Kilobytes per second",
                    "MB/s": "MB/s - Megabytes per second",
                    "kbps": "kbps - Kilobits per second",
                    "Mbps": "Mbps - Megabits per second",
                }
                for unit in TRANSFER_RATE_UNITS:
                    rate_items[unit] = dpg.add_menu_item(
                        label=rate_labels[unit],
                        check=True,
                        user_data=unit,
                        callback=lambda s, a, u: self._context_set_transfer_rate_unit(u),
                    )
                    add_help_tooltip(rate_items[unit], "TRANSFER_RATE")
            add_help_tooltip(rate_menu, "TRANSFER_RATE")

            dpg.add_separator()

            start_item = dpg.add_menu_item(
                label="Start",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_start(u),
            )
            pause_item = dpg.add_menu_item(
                label="Pause",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_pause(u),
            )
            resume_item = dpg.add_menu_item(
                label="Resume",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_resume(u),
            )
            stop_item = dpg.add_menu_item(
                label="Stop",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_stop(u),
            )
            retry_item = dpg.add_menu_item(
                label="Retry",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_retry(u),
            )

            dpg.add_separator()

            open_folder_item = dpg.add_menu_item(
                label="Open Download Folder",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_open_folder(u),
            )
            announce_item = dpg.add_menu_item(
                label="Update Trackers",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_update_trackers(u),
            )
            recheck_item = dpg.add_menu_item(
                label="Force Recheck...",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_force_recheck(u),
            )

            dpg.add_separator()

            copy_hash_item = dpg.add_menu_item(
                label="Copy Info Hash",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_copy_info_hash(u),
            )
            copy_magnet_item = dpg.add_menu_item(
                label="Copy Magnet Link",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_copy_magnet(u),
            )
            properties_item = dpg.add_menu_item(
                label="Properties...",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_properties(u),
            )

            dpg.add_separator()

            remove_item = dpg.add_menu_item(
                label="Remove Torrent...",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_remove(u),
            )

        add_help_tooltip(move_up_item, "QUEUE_ORDER")
        add_help_tooltip(move_down_item, "QUEUE_ORDER")
        add_help_tooltip(priority_high_item, "QUEUE_PRIORITY")
        add_help_tooltip(priority_normal_item, "QUEUE_PRIORITY")
        add_help_tooltip(priority_low_item, "QUEUE_PRIORITY")
        add_help_tooltip(start_item, "START_RESUME")
        add_help_tooltip(pause_item, "PAUSE_TORRENT")
        add_help_tooltip(resume_item, "START_RESUME")
        add_help_tooltip(stop_item, "STOP_TORRENT")
        add_help_tooltip(retry_item, "RETRY_TORRENT")
        add_help_tooltip(open_folder_item, "OPEN_FOLDER")
        add_help_tooltip(announce_item, "UPDATE_TRACKERS")
        add_help_tooltip(recheck_item, "FORCE_RECHECK")
        add_help_tooltip(copy_hash_item, "COPY_INFO_HASH")
        add_help_tooltip(copy_magnet_item, "COPY_MAGNET")
        add_help_tooltip(properties_item, "PROPERTIES")
        add_help_tooltip(remove_item, "REMOVE_TORRENT")

        # Use ONE handler registry for the entire row.  This is important:
        # dpg.popup() also uses an item-handler registry internally, and an item
        # can only have one registry bound at a time.  The previous code bound
        # our selection registry after dpg.popup(), replacing the popup handler.
        with dpg.item_handler_registry() as right_click_registry:
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                user_data=(info_hash, popup_id),
                callback=lambda s, a, u: self._on_row_right_clicked(u[0], u[1]),
            )

        # Bind the same registry to every visible cell so right-clicking Name,
        # Size, Progress, Status, or Down / Up opens the same torrent menu.
        for cell in row_cells:
            dpg.bind_item_handler_registry(cell, right_click_registry)

        return {
            "popup": popup_id,
            "move_up": move_up_item,
            "move_down": move_down_item,
            "priority_high": priority_high_item,
            "priority_normal": priority_normal_item,
            "priority_low": priority_low_item,
            "rate_items": rate_items,
            "start": start_item,
            "pause": pause_item,
            "resume": resume_item,
            "stop": stop_item,
            "retry": retry_item,
            "open_folder": open_folder_item,
            "announce": announce_item,
            "recheck": recheck_item,
            "copy_hash": copy_hash_item,
            "copy_magnet": copy_magnet_item,
            "properties": properties_item,
            "remove": remove_item,
            "right_click_registry": right_click_registry,
        }

    def _on_row_right_clicked(self, info_hash: str, popup_id):
        self._select_torrent(info_hash)
        self._refresh_context_menu_states()
        dpg.configure_item(popup_id, show=True)

    def _context_set_priority(self, info_hash: str, priority: str):
        self._select_torrent(info_hash)
        self.manager.set_torrent_priority(info_hash, priority)

    def _context_set_transfer_rate_unit(self, unit: str):
        self._set_transfer_rate_unit(unit, persist=True)

    def _set_transfer_rate_unit(self, unit: object, persist: bool = False):
        normalized = normalize_transfer_rate_unit(unit)
        if persist:
            normalized = self.manager.set_transfer_rate_display_unit(normalized)

        if normalized == self._transfer_rate_unit:
            self._refresh_context_menu_states()
            return

        self._transfer_rate_unit = normalized
        self.peer_view.set_rate_unit(normalized)
        self.speed_view.set_rate_unit(normalized)

        # This setting changes presentation only. Reformat cached rows locally
        # without touching torrent sessions, peer workers or bandwidth limits.
        for info_hash, row in self.torrent_rows.items():
            stats = self.latest_stats.get(info_hash, {})
            if not stats:
                continue
            dpg.set_value(
                row["speed"],
                format_transfer_rate_pair(
                    stats.get("speed_kbps", 0.0),
                    stats.get("upload_speed_kbps", 0.0),
                    normalized,
                ),
            )

        if self.active_info_hash in self.latest_stats:
            self._render_inspector(
                self.latest_stats[self.active_info_hash],
                force_detail=self._active_detail_tab == "Speed",
            )
        self._refresh_context_menu_states()

    def _context_start(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.start_torrent(info_hash)

    def _context_pause(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.pause_torrent(info_hash)

    def _context_resume(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.resume_torrent(info_hash)

    def _context_stop(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.stop_torrent(info_hash)

    def _context_retry(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.start_torrent(info_hash)

    def _context_open_folder(self, info_hash: str):
        self._select_torrent(info_hash)
        self._open_folder_for_hash(info_hash)

    def _context_update_trackers(self, info_hash: str):
        self._select_torrent(info_hash)
        self.manager.update_trackers(info_hash)

    def _context_force_recheck(self, info_hash: str):
        self._request_force_recheck(info_hash)

    def _context_copy_info_hash(self, info_hash: str):
        self._select_torrent(info_hash)
        self._copy_text(self.latest_stats.get(info_hash, {}).get("info_hash"))

    def _context_copy_magnet(self, info_hash: str):
        self._select_torrent(info_hash)
        self._copy_text(self.latest_stats.get(info_hash, {}).get("magnet_uri"))

    def _context_properties(self, info_hash: str):
        self._show_properties(info_hash)

    def _context_remove(self, info_hash: str):
        if info_hash not in self.torrent_rows:
            return

        self._select_torrent(info_hash)
        self._pending_remove_info_hash = info_hash

        row = self.torrent_rows[info_hash]
        popup_id = row["menu"].get("popup")
        if popup_id and dpg.does_item_exist(popup_id):
            dpg.hide_item(popup_id)

        name = self.latest_stats.get(info_hash, {}).get("torrent_name", "this torrent")
        dpg.set_value(
            self.remove_torrent_title,
            f"Remove: {name}",
        )
        stats = self.latest_stats.get(info_hash, {})
        if stats.get("seed_source_path"):
            removal_text = (
                "Remove from SalixTorrent removes the transfer from the queue and leaves "
                "the original seed source untouched.\n\n"
                "Remove + Delete Data only deletes SalixTorrent-managed data under the "
                "downloads folder and resume metadata. The external seed source and your "
                "original .torrent file are NEVER deleted."
            )
        else:
            removal_text = (
                "Remove from SalixTorrent removes the transfer from the queue but keeps "
                "downloaded data on disk.\n\n"
                "Remove + Delete Data permanently deletes the downloaded payload and its "
                "SalixTorrent resume metadata. Your original .torrent file is NOT deleted."
            )

        dpg.set_value(self.remove_torrent_message, removal_text)

        dpg.show_item(self.remove_torrent_modal)
        try:
            width = 520
            height = 230
            x = max(0, (dpg.get_viewport_client_width() - width) // 2)
            y = max(0, (dpg.get_viewport_client_height() - height) // 2)
            dpg.set_item_pos(self.remove_torrent_modal, [x, y])
        except Exception:
            pass

    def _confirm_remove_torrent(self, delete_data: bool):
        info_hash = self._pending_remove_info_hash
        self._pending_remove_info_hash = ""
        dpg.hide_item(self.remove_torrent_modal)

        if not info_hash or info_hash not in self.torrent_rows:
            return

        row = self.torrent_rows[info_hash]
        dpg.set_value(row["status"], "Removing...")
        self.manager.remove_torrent(info_hash, delete_data=delete_data)

    def _move_torrent_up(self, info_hash: str):
        if info_hash not in self.torrent_rows:
            return

        try:
            index = self.torrent_order.index(info_hash)
        except ValueError:
            return

        if index <= 0:
            return

        self._select_torrent(info_hash)
        row_id = self.torrent_rows[info_hash]["row"]

        # Dear PyGui moves the actual table-row item, so subsequent telemetry
        # updates modify the same row without undoing the user's ordering.
        dpg.move_item_up(row_id)
        self.torrent_order[index - 1], self.torrent_order[index] = (
            self.torrent_order[index],
            self.torrent_order[index - 1],
        )
        self.manager.set_queue_order(self.torrent_order)
        if self._sort_specs:
            self._apply_queue_sort()
        self._refresh_context_menu_states()

    def _move_torrent_down(self, info_hash: str):
        if info_hash not in self.torrent_rows:
            return

        try:
            index = self.torrent_order.index(info_hash)
        except ValueError:
            return

        if index >= len(self.torrent_order) - 1:
            return

        self._select_torrent(info_hash)
        row_id = self.torrent_rows[info_hash]["row"]

        dpg.move_item_down(row_id)
        self.torrent_order[index], self.torrent_order[index + 1] = (
            self.torrent_order[index + 1],
            self.torrent_order[index],
        )
        self.manager.set_queue_order(self.torrent_order)
        if self._sort_specs:
            self._apply_queue_sort()
        self._refresh_context_menu_states()

    def _refresh_context_menu_state(self, info_hash: str):
        row = self.torrent_rows.get(info_hash)
        if not row:
            return

        menu = row["menu"]
        stats = self.latest_stats.get(info_hash, {})
        state = stats.get("state", "Idle")

        try:
            index = self.torrent_order.index(info_hash)
        except ValueError:
            index = -1

        can_move_up = index > 0
        can_move_down = 0 <= index < len(self.torrent_order) - 1

        # Keep every lifecycle action visible and disable only actions that do
        # not make sense for the torrent's current state.
        can_start = state in self.STARTABLE_STATES
        can_pause = state in self.ACTIVE_PAUSABLE_STATES
        can_resume = state == "Paused"
        can_stop = state in self.STOPPABLE_STATES
        queue_priority = stats.get("queue_priority", "Normal")

        dpg.configure_item(menu["move_up"], enabled=can_move_up)
        dpg.configure_item(menu["move_down"], enabled=can_move_down)
        dpg.configure_item(menu["priority_high"], enabled=queue_priority != "High")
        dpg.configure_item(menu["priority_normal"], enabled=queue_priority != "Normal")
        dpg.configure_item(menu["priority_low"], enabled=queue_priority != "Low")
        for unit, item in menu.get("rate_items", {}).items():
            dpg.set_value(item, unit == self._transfer_rate_unit)
        dpg.configure_item(menu["start"], enabled=can_start and state != "Error")
        dpg.configure_item(menu["pause"], enabled=can_pause)
        dpg.configure_item(menu["resume"], enabled=can_resume)
        dpg.configure_item(menu["stop"], enabled=can_stop)
        dpg.configure_item(menu["retry"], enabled=state == "Error")
        dpg.configure_item(menu["open_folder"], enabled=bool(stats.get("storage_path")))
        dpg.configure_item(menu["announce"], enabled=state in {"Downloading", "Seeding"})
        dpg.configure_item(
            menu["recheck"],
            enabled=state not in {"Checking", "Fast Resume", "Queued"},
        )
        dpg.configure_item(menu["copy_hash"], enabled=bool(stats.get("info_hash")))
        dpg.configure_item(menu["copy_magnet"], enabled=bool(stats.get("magnet_uri")))
        dpg.configure_item(menu["properties"], enabled=True)
        dpg.configure_item(menu["remove"], enabled=True)

    def _refresh_context_menu_states(self):
        for info_hash in self.torrent_order:
            self._refresh_context_menu_state(info_hash)

    def _reset_inspector(self):
        dpg.set_value(self.title_text, "Torrent: Waiting for selection...")
        dpg.set_value(self.status_text, "Status: Idle")
        dpg.set_value(self.progress_bar, 0.0)
        dpg.set_value(self.progress_label, "0.0% Complete (0 / 0 Pieces)")
        dpg.set_value(
            self.speed_text,
            f"Download Speed: {format_transfer_rate(0.0, self._transfer_rate_unit)}",
        )
        dpg.set_value(
            self.upload_speed_text,
            f"Upload Speed: {format_transfer_rate(0.0, self._transfer_rate_unit)}",
        )
        dpg.set_value(self.downloaded_text, "Downloaded: 0 B / 0 B")
        dpg.set_value(self.remaining_text, "Remaining: 0 B")
        dpg.set_value(self.uploaded_text, "Uploaded Total: 0 B")
        dpg.set_value(self.uploaded_session_text, "Uploaded This Session: 0 B")
        dpg.set_value(self.upload_requests_text, "Upload Requests: 0 served / 0 received")
        dpg.set_value(self.last_upload_text, "Last Upload: --")
        dpg.set_value(self.eta_text, "ETA: --")
        dpg.set_value(self.elapsed_text, "Active Time: 00:00")
        dpg.set_value(self.ratio_text, "Share Ratio: --")
        dpg.set_value(self.peers_text, "Connected Peers: 0")
        dpg.set_value(self.error_text, "")
        dpg.configure_item(self.retry_button, enabled=False)
        dpg.set_value(self.state_text, "Session State: Idle")
        dpg.set_value(self.seed_leech_text, "Seeds / Leechers: -- / --")
        dpg.set_value(self.availability_text, "Availability: --")
        dpg.set_value(self.discovery_text, "Discovery: --")
        dpg.set_value(self.listen_port_text, "Listen Port: --")
        dpg.set_value(self.listener_endpoint_text, "Listener: --")
        dpg.set_value(self.transport_text, "Transport: --")
        dpg.set_value(self.network_path_text, "Network Path: --")
        dpg.set_value(self.connectivity_text, "Incoming: --")
        dpg.set_value(self.incoming_peers_text, "Incoming Peers: 0 active / 0 this session")
        dpg.set_value(self.mapping_methods_text, "Mapping Methods: UPnP -- | NAT-PMP --")
        dpg.set_value(self.mapping_detail_text, "Mapping Detail: --")
        dpg.set_value(self.connectivity_hint_text, "Connectivity Hint: --")
        dpg.set_value(self.external_port_text, "External: --")
        dpg.set_value(self.storage_text, "Storage: Downloads")
        dpg.set_value(self.lpd_text, "LAN Discovery: --")
        dpg.set_value(self.health_text, "Swarm Health: --")
        dpg.set_value(self.info_hash_text, "Info Hash: --")
        dpg.set_value(self.piece_info_text, "Pieces: --")
        dpg.set_value(self.file_info_text, "Files: --")
        dpg.set_value(self.private_text, "Private: --")
        dpg.set_value(self.created_by_text, "Created By: --")
        dpg.set_value(self.created_date_text, "Created: --")
        dpg.set_value(self.comment_text, "Comment: --")
        dpg.set_value(self.storage_path_text, "Storage Path: --")
        dpg.set_value(self.torrent_path_text, ".torrent: --")
        dpg.set_value(self.limit_status_text, "Limits: Down Unlimited | Up Unlimited")
        dpg.set_value(self.download_limit_input, 0.0)
        dpg.set_value(self.upload_limit_input, 0.0)
        self._limit_controls_hash = ""
        self.peer_view.reset()
        self.piece_view.reset()
        self.file_view.reset()
        self.source_view.reset()
        self.speed_view.reset()

    def _handle_torrent_removed(self, msg: dict):
        info_hash = msg.get("info_hash", "")
        if not info_hash:
            return

        self._removed_info_hashes.add(info_hash)
        self.latest_stats.pop(info_hash, None)

        row = self.torrent_rows.pop(info_hash, None)
        if row:
            menu = row.get("menu", {})
            for item_key in ("popup", "right_click_registry"):
                item = menu.get(item_key)
                if item and dpg.does_item_exist(item):
                    dpg.delete_item(item)

            row_id = row.get("row")
            if row_id and dpg.does_item_exist(row_id):
                dpg.delete_item(row_id)

        if info_hash in self.torrent_order:
            self.torrent_order.remove(info_hash)

        selected = msg.get("selected_info_hash", "")
        if self.active_info_hash == info_hash:
            self.active_info_hash = selected if selected in self.torrent_rows else ""
            self._limit_controls_hash = ""

            if self.active_info_hash and self.active_info_hash in self.latest_stats:
                self._select_torrent(self.active_info_hash)
            else:
                self._reset_inspector()

        self._refresh_context_menu_states()
        self._apply_queue_filters()

        cleanup_error = str(msg.get("cleanup_error") or "")
        if cleanup_error:
            dpg.set_value(
                self.remove_notice_text,
                (
                    "The torrent was removed from SalixTorrent, but downloaded-data "
                    f"cleanup was not fully completed:\n\n{cleanup_error}"
                ),
            )
            dpg.show_item(self.remove_notice_modal)

    @staticmethod
    def _format_limit(value: float, unit: str) -> str:
        if value <= 0:
            return "Unlimited"
        return f"{value:g} {unit}"

    def _sync_limit_controls(self, msg: dict):
        h = msg.get("info_hash", "")
        if h == self._limit_controls_hash:
            return

        dpg.set_value(
            self.download_limit_input,
            float(msg.get("download_limit_value", 0.0)),
        )
        dpg.set_value(
            self.download_limit_unit,
            msg.get("download_limit_unit", "KB/s"),
        )
        dpg.set_value(
            self.upload_limit_input,
            float(msg.get("upload_limit_value", 0.0)),
        )
        dpg.set_value(
            self.upload_limit_unit,
            msg.get("upload_limit_unit", "KB/s"),
        )
        self._limit_controls_hash = h

    def _update_table_row(self, msg: dict):
        h = msg["info_hash"]
        size_str = f"{msg['total_bytes'] / (1024 * 1024):.1f} MB"
        prog_str = f"{msg['progress'] * 100:.1f}%"
        down_kbps = msg.get("speed_kbps", 0.0)
        up_kbps = msg.get("upload_speed_kbps", 0.0)
        speed_str = format_transfer_rate_pair(
            down_kbps,
            up_kbps,
            self._transfer_rate_unit,
        )
        state_label = msg.get("state_label", msg["state"])

        if h not in self.torrent_rows:
            with dpg.table_row(parent="torrent_queue_table") as row_id:
                name_cell = dpg.add_selectable(
                    label=msg["torrent_name"],
                    span_columns=True,
                    user_data=h,
                    callback=lambda s, a, u: self._select_torrent(u),
                )
                size_cell = dpg.add_text(size_str)
                prog_cell = dpg.add_text(prog_str)
                priority_cell = dpg.add_text(msg.get("queue_priority", "Normal"))
                status_cell = dpg.add_text(state_label)
                speed_cell = dpg.add_text(speed_str)

            add_text_tooltip(name_cell, "Torrent row\n\nClick to select this torrent and populate the inspector below. Right-click any cell in this row for queue, transfer, recheck, copy, properties and removal actions.")
            add_text_tooltip(size_cell, "Payload size\n\nTotal size described by this torrent's metadata, not the size of the .torrent file itself.")
            add_help_tooltip(prog_cell, "PIECE")
            add_help_tooltip(priority_cell, "QUEUE_PRIORITY")
            add_help_tooltip(status_cell, "TORRENT_STATUS")
            add_help_tooltip(speed_cell, "TRANSFER_RATE")

            menu = self._build_row_context_menu(
                h,
                (name_cell, size_cell, prog_cell, priority_cell, status_cell, speed_cell),
            )
            self.torrent_rows[h] = {
                "row": row_id,
                "name": name_cell,
                "size": size_cell,
                "progress": prog_cell,
                "priority": priority_cell,
                "status": status_cell,
                "speed": speed_cell,
                "menu": menu,
            }
            self.torrent_order.append(h)
            self._refresh_context_menu_states()

        else:
            row = self.torrent_rows[h]
            dpg.set_value(row["size"], size_str)
            dpg.set_value(row["progress"], prog_str)
            dpg.set_value(row["priority"], msg.get("queue_priority", "Normal"))
            dpg.set_value(row["status"], state_label)
            dpg.set_value(row["speed"], speed_str)
            dpg.set_value(row["name"], self.active_info_hash == h)
            self._refresh_context_menu_state(h)

        if self._sort_specs:
            self._apply_queue_sort()

    def _select_torrent(self, info_hash: str):
        self.active_info_hash = info_hash
        self._limit_controls_hash = ""
        self.manager.set_selected_torrent(info_hash)

        for h, row in self.torrent_rows.items():
            dpg.set_value(row["name"], h == info_hash)

        if info_hash in self.latest_stats:
            self._render_inspector(self.latest_stats[info_hash], force_detail=True)

    def _render_inspector(self, msg: dict, force_detail: bool = False):
        dpg.set_value(self.title_text, f"Torrent: {msg['torrent_name']}")

        state = msg["state"]
        state_label = msg.get("state_label", state)
        dpg.set_value(
            self.status_text,
            f"Status: {state_label} ({msg['connected_peers']} peers)",
        )
        dpg.set_value(self.state_text, f"Session State: {state_label}")

        # During a payload verification pass, the main progress bar shows the
        # *checking operation* rather than download completion. Download
        # completion remains visible in the transfer table and byte metrics.
        checking_progress = msg.get("checking_progress", 0.0)
        paused_while_checking = state == "Paused" and "Checking" in state_label

        if state == "Checking" or paused_while_checking:
            dpg.set_value(self.progress_bar, checking_progress)

            checked_pieces = msg.get("checked_pieces", 0)
            check_total_pieces = msg.get("check_total_pieces", 0)
            dpg.set_value(
                self.progress_label,
                (
                    f"{checking_progress * 100:.1f}% Checked "
                    f"({checked_pieces} / {check_total_pieces} Pieces Scanned)"
                ),
            )
        elif state == "Fast Resume":
            prog = msg["progress"]
            dpg.set_value(self.progress_bar, prog)
            dpg.set_value(
                self.progress_label,
                (
                    "Fast resume restored - "
                    f"{msg['completed_pieces']} / {msg['total_pieces']} Pieces Verified"
                ),
            )
        elif state == "Completed" and msg.get("wanted_finished") and msg.get("progress", 0.0) < 1.0:
            wanted_prog = float(msg.get("wanted_progress", 1.0) or 0.0)
            total_prog = float(msg.get("progress", 0.0) or 0.0)
            dpg.set_value(self.progress_bar, wanted_prog)
            dpg.set_value(
                self.progress_label,
                (
                    f"{wanted_prog * 100:.2f}% Selected Files Complete "
                    f"({msg.get('wanted_completed_pieces', 0)} / "
                    f"{msg.get('wanted_total_pieces', 0)} Wanted Pieces) - "
                    f"{total_prog * 100:.2f}% of full torrent"
                ),
            )
        else:
            prog = msg["progress"]
            dpg.set_value(self.progress_bar, prog)

            suffix = " - Seeding" if state == "Seeding" else ""
            dpg.set_value(
                self.progress_label,
                (
                    f"{prog * 100:.2f}% Complete "
                    f"({msg['completed_pieces']} / {msg['total_pieces']} Pieces){suffix}"
                ),
            )

        dpg.set_value(
            self.speed_text,
            "Download Speed: "
            + format_transfer_rate(
                msg.get("speed_kbps", 0.0),
                self._transfer_rate_unit,
            ),
        )
        dpg.set_value(
            self.upload_speed_text,
            "Upload Speed: "
            + format_transfer_rate(
                msg.get("upload_speed_kbps", 0.0),
                self._transfer_rate_unit,
            ),
        )
        dpg.set_value(
            self.downloaded_text,
            f"Downloaded: {self._format_bytes(msg.get('downloaded_bytes'))} / "
            f"{self._format_bytes(msg.get('total_bytes'))}",
        )
        dpg.set_value(
            self.remaining_text,
            f"Remaining: {self._format_bytes(msg.get('remaining_bytes'))}",
        )
        dpg.set_value(
            self.uploaded_text,
            f"Uploaded Total: {self._format_bytes(msg.get('uploaded_bytes'))}",
        )
        dpg.set_value(
            self.uploaded_session_text,
            f"Uploaded This Session: {self._format_bytes(msg.get('uploaded_this_session_bytes'))}",
        )
        dpg.set_value(
            self.upload_requests_text,
            f"Upload Requests: {int(msg.get('upload_requests_served', 0) or 0):,} served / "
            f"{int(msg.get('upload_requests_received', 0) or 0):,} received",
        )
        dpg.set_value(
            self.last_upload_text,
            f"Last Upload: {self._format_age(msg.get('last_upload_seconds'))}",
        )
        dpg.set_value(self.eta_text, f"ETA: {self._format_duration(msg.get('eta_seconds'))}")
        dpg.set_value(
            self.elapsed_text,
            f"Active Time: {self._format_duration(msg.get('elapsed_seconds'))}",
        )
        ratio = msg.get("share_ratio")
        ratio_text = f"{float(ratio):.3f}" if ratio is not None else "--"
        dpg.set_value(self.ratio_text, f"Share Ratio: {ratio_text}")
        dpg.set_value(
            self.peers_text,
            f"Connected Peers: {msg['connected_peers']}",
        )

        error_message = str(msg.get("error_message") or "")
        dpg.set_value(
            self.error_text,
            f"Error / Notice: {error_message}" if error_message else "",
        )
        dpg.configure_item(self.retry_button, enabled=state == "Error")

        seeders = msg.get("swarm_seeders")
        leechers = msg.get("swarm_leechers")
        dpg.set_value(
            self.seed_leech_text,
            f"Seeds / Leechers: {seeders if seeders is not None else '--'} / "
            f"{leechers if leechers is not None else '--'}",
        )
        availability = float(msg.get("swarm_availability", 0.0) or 0.0)
        dpg.set_value(self.availability_text, f"Availability: {availability:.2f}")
        dpg.set_value(
            self.discovery_text,
            f"Discovery: {msg.get('discovery_summary', '--')}",
        )

        self._sync_limit_controls(msg)
        download_limit_text = self._format_limit(
            float(msg.get("download_limit_value", 0.0)),
            msg.get("download_limit_unit", "KB/s"),
        )
        upload_limit_text = self._format_limit(
            float(msg.get("upload_limit_value", 0.0)),
            msg.get("upload_limit_unit", "KB/s"),
        )
        dpg.set_value(
            self.limit_status_text,
            f"Limits: Down {download_limit_text} | Up {upload_limit_text}",
        )

        listen_port = int(msg.get("listen_port", 0) or 0)
        preferred_port = int(msg.get("preferred_listen_port", 0) or 0)
        shown_port = listen_port or preferred_port
        port_suffix = "" if listen_port or not preferred_port else " (configured)"
        dpg.set_value(
            self.listen_port_text,
            f"Listen Port: {shown_port if shown_port else '--'}{port_suffix}",
        )
        listener_address = str(msg.get("listener_address") or "").strip()
        if listen_port and listener_address:
            listener_suffix = " (all IPv4 interfaces)" if listener_address == "0.0.0.0" else ""
            listener_value = f"Listener: {listener_address}:{listen_port}{listener_suffix}"
        elif listen_port:
            listener_value = f"Listener: port {listen_port}"
        else:
            listener_value = "Listener: Not listening"
        dpg.set_value(self.listener_endpoint_text, listener_value)

        encrypted_count = int(msg.get("encrypted_peer_count", 0) or 0)
        plaintext_count = int(msg.get("plaintext_peer_count", 0) or 0)
        encryption_policy = str(msg.get("encryption_policy") or "Prefer Encryption")
        dpg.set_value(
            self.transport_text,
            f"Transport: {encryption_policy} | MSE/RC4 {encrypted_count} | Plaintext {plaintext_count}",
        )

        bind_address = str(msg.get("network_bind_address") or "").strip()
        lock_enabled = bool(msg.get("interface_lock", False))
        lock_active = bool(msg.get("interface_lock_active", False))
        if bind_address:
            lock_label = "Locked" if lock_enabled and lock_active else ("Lock enabled" if lock_enabled else "Lock off")
            network_path = f"Network Path: {bind_address} | {lock_label}"
        else:
            network_path = "Network Path: Any interface (system routing) | Lock off"
        dpg.set_value(self.network_path_text, network_path)

        if listen_port:
            connectivity = self.manager.get_connectivity_snapshot(port=listen_port)
        else:
            connectivity = {
                "status": "Not listening",
                "method": "None",
                "external_ip": "",
                "external_port": 0,
            }
        connectivity_status = str(connectivity.get("status") or "Waiting")
        mapping_method = str(connectivity.get("method") or "").strip()
        if mapping_method and mapping_method not in {"--", "None"}:
            incoming_value = f"Incoming: {connectivity_status} ({mapping_method})"
        else:
            incoming_value = f"Incoming: {connectivity_status}"
        dpg.set_value(self.connectivity_text, incoming_value)
        incoming_active = int(msg.get("incoming_peers", 0) or 0)
        incoming_total = int(msg.get("incoming_connections_total", 0) or 0)
        dpg.set_value(
            self.incoming_peers_text,
            f"Incoming Peers: {incoming_active:,} active / {incoming_total:,} this session",
        )
        dpg.set_value(
            self.mapping_methods_text,
            f"Mapping Methods: UPnP {connectivity.get('upnp_status', '--')} | "
            f"NAT-PMP {connectivity.get('natpmp_status', '--')}",
        )
        upnp_summary = str(connectivity.get("upnp_summary") or "").strip()
        natpmp_summary = str(connectivity.get("natpmp_summary") or "").strip()
        method_details = [
            value for value in (upnp_summary, natpmp_summary)
            if value and not value.endswith("Not tried") and not value.endswith("Not needed")
        ]
        dpg.set_value(
            self.mapping_detail_text,
            f"Mapping Detail: {' | '.join(method_details) if method_details else '--'}",
        )
        action_hint = str(connectivity.get("action_hint") or "").strip()
        dpg.set_value(
            self.connectivity_hint_text,
            f"Connectivity Hint: {action_hint or '--'}",
        )

        external_ip = str(connectivity.get("external_ip") or "").strip()
        external_port = int(connectivity.get("external_port") or 0)
        external_scope = str(connectivity.get("external_scope") or "Unknown")
        if external_ip and external_port:
            scope_suffix = f" ({external_scope})" if external_scope != "Unknown" else ""
            external_value = f"External: {external_ip}:{external_port}{scope_suffix}"
        elif external_port:
            external_value = f"External: port {external_port}"
        else:
            external_value = "External: --"
        dpg.set_value(self.external_port_text, external_value)

        storage_mode = msg.get("storage_mode", "Download")
        if storage_mode == "External Seed":
            dpg.set_value(self.storage_text, "Storage: External Seed (read-only)")
        else:
            dpg.set_value(self.storage_text, "Storage: Downloads")

        local_count = int(msg.get("local_peers_discovered", 0))
        lan_enabled = bool(msg.get("lan_discovery_enabled", msg.get("local_discovery_enabled", False)))
        if not lan_enabled:
            dpg.set_value(self.lpd_text, "LAN Discovery: Disabled")
        elif msg.get("local_discovery_enabled"):
            dpg.set_value(
                self.lpd_text,
                f"LAN Discovery: Active ({local_count} peer(s) found)",
            )
        else:
            dpg.set_value(self.lpd_text, "LAN Discovery: Starting")

        if error_message:
            dpg.set_value(self.health_text, "Swarm Health: Attention required")
        elif state in {"Downloading", "Seeding"}:
            if availability and availability < 1.0 and msg.get("progress", 0.0) < 1.0:
                dpg.set_value(self.health_text, "Swarm Health: Incomplete availability")
            elif availability >= 2.0:
                dpg.set_value(self.health_text, "Swarm Health: Healthy")
            else:
                dpg.set_value(self.health_text, "Swarm Health: Active")
        else:
            dpg.set_value(self.health_text, "Swarm Health: --")

        dpg.set_value(self.info_hash_text, f"Info Hash: {msg.get('info_hash', '--')}")
        dpg.set_value(
            self.piece_info_text,
            f"Pieces: {msg.get('total_pieces', 0):,} x {self._format_bytes(msg.get('piece_length'))}",
        )
        file_kind = "multi-file" if msg.get("is_multi_file") else "single-file"
        dpg.set_value(
            self.file_info_text,
            f"Files: {msg.get('file_count', 0):,} ({file_kind})",
        )
        dpg.set_value(self.private_text, f"Private: {'Yes' if msg.get('private') else 'No'}")
        dpg.set_value(self.created_by_text, f"Created By: {msg.get('created_by') or '--'}")
        dpg.set_value(
            self.created_date_text,
            f"Created: {self._format_creation_date(msg.get('creation_date'))}",
        )
        dpg.set_value(self.comment_text, f"Comment: {msg.get('comment') or '--'}")
        dpg.set_value(
            self.storage_path_text,
            f"Storage Path: {msg.get('storage_path') or '--'}",
        )
        dpg.set_value(
            self.torrent_path_text,
            f".torrent: {msg.get('torrent_path') or '--'}",
        )

        self._render_active_detail(msg, force=force_detail)

    def update(self, delta_time: float):
        del delta_time

        # Presentation preferences can be changed from Preferences while this
        # view is hidden. Apply them locally on return without waiting for a new
        # network telemetry snapshot.
        configured_rate_unit = normalize_transfer_rate_unit(
            self.manager.get_transfer_rate_display_unit()
        )
        if configured_rate_unit != self._transfer_rate_unit:
            self._set_transfer_rate_unit(configured_rate_unit, persist=False)

        # Keep the toolbar synchronized when queue settings are changed from
        # the Preferences view.
        current_slots = self.manager.get_max_active_downloads()
        if current_slots != self._queue_slots_value:
            self._queue_slots_value = current_slots
            if hasattr(self, "queue_slots_input") and dpg.does_item_exist(self.queue_slots_input):
                dpg.set_value(self.queue_slots_input, current_slots)

        # Drain the thread-safe queue without touching Dear PyGui, coalescing
        # multiple telemetry snapshots for the same torrent down to the newest
        # one. This is essential when DownloadView has been hidden: telemetry
        # can arrive while Preferences/Create Torrent is visible, and replaying
        # every stale 0.5-second snapshot on return can lock the UI for seconds.
        latest_transfer = {}
        removed_messages = []
        latest_magnet = {}

        while True:
            try:
                msg = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            msg_type = msg.get("type")
            if msg_type == "TRANSFER_STATS":
                h = str(msg.get("info_hash") or "")
                if h and h not in self._removed_info_hashes:
                    latest_transfer[h] = msg
            elif msg_type == "TORRENT_REMOVED":
                h = str(msg.get("info_hash") or "")
                latest_transfer.pop(h, None)
                removed_messages.append(msg)
            elif msg_type in {
                "MAGNET_PROGRESS",
                "MAGNET_READY",
                "MAGNET_ERROR",
                "MAGNET_CANCELLED",
            }:
                h = str(msg.get("info_hash") or "magnet")
                latest_magnet[h] = msg

        # Magnet metadata can contain hundreds of 16 KiB chunks. If this view
        # was hidden, show only the newest progress/terminal event per magnet
        # rather than replaying every stale percentage update on return.
        for msg in latest_magnet.values():
            self._handle_magnet_event(msg)

        if self._magnet_close_at and time.monotonic() >= self._magnet_close_at:
            self._magnet_close_at = 0.0
            self._magnet_info_hash = ""
            if dpg.does_item_exist(self.magnet_modal):
                dpg.hide_item(self.magnet_modal)

        changed_rows = False

        # Removal wins over any older telemetry drained in the same frame.
        for msg in removed_messages:
            h = str(msg.get("info_hash") or "")
            self._completion_notified.discard(h)
            self._handle_torrent_removed(msg)
            changed_rows = True

        for h, msg in latest_transfer.items():
            if h in self._removed_info_hashes:
                continue

            previous = self.latest_stats.get(h, {})
            previous_state = str(previous.get("state") or "")
            self.latest_stats[h] = msg

            if not self.active_info_hash:
                self.active_info_hash = h
                self.manager.set_selected_torrent(h)

            self._update_table_row(msg)
            changed_rows = True

            if self.active_info_hash == h:
                self._render_inspector(msg)

            new_state = str(msg.get("state") or "")
            if (
                h not in self._completion_notified
                and previous_state in {"Downloading", "Checking", "Fast Resume"}
                and new_state in {"Completed", "Seeding"}
            ):
                self._completion_notified.add(h)
                self._show_completion_notice(h, msg)

            # If the user later makes more files wanted or restarts an
            # incomplete torrent, allow a fresh future completion notice.
            if new_state in {"Downloading", "Checking"} and not msg.get("wanted_finished"):
                self._completion_notified.discard(h)

        # Filtering walks the whole queue; do it once per UI frame instead of
        # once for every torrent snapshot.
        if changed_rows:
            self._apply_queue_filters()

    def on_show(self, **kwargs):
        del kwargs
        # Render the selected torrent immediately from the latest cached state.
        # Incoming queue telemetry will be coalesced by update() on the next
        # frame rather than replayed one-by-one.
        if self.active_info_hash:
            snapshot = self.latest_stats.get(self.active_info_hash)
            if snapshot:
                self._render_inspector(snapshot, force_detail=True)




