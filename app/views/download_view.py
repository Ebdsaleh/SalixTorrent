# app/views/download_view.py

import os
import queue
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.logic.torrent_manager import TorrentManager
from app.views.peer_view import PeerView
from app.views.piece_view import PieceView
from app.views.file_view import FileView
from app.views.source_view import SourceView
from app.views.speed_view import SpeedView


class DownloadView:
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
        self._removed_info_hashes = set()
        self.peer_view = PeerView()
        self.piece_view = PieceView()
        self.file_view = FileView()
        self.source_view = SourceView()
        self.speed_view = SpeedView()
        self._queue_slots_value = self.manager.get_max_active_downloads()

    def build_view(self, parent_tag: str | int = "primary_window"):
        with dpg.group(parent=parent_tag):
            # Top Controls
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=" + Open Torrent ",
                    callback=self._open_native_file_dialog,
                )
                dpg.add_spacer(width=10)
                dpg.add_button(
                    label=" Start / Resume ",
                    callback=self._on_resume_clicked,
                )
                dpg.add_button(
                    label=" Pause ",
                    callback=self._on_pause_clicked,
                )
                dpg.add_button(
                    label=" Stop ",
                    callback=self._on_stop_clicked,
                )
                dpg.add_spacer(width=18)
                dpg.add_text("Active DL Slots")
                self.queue_slots_input = dpg.add_input_int(
                    default_value=self._queue_slots_value,
                    min_value=0,
                    min_clamped=True,
                    width=70,
                )
                dpg.add_button(
                    label=" Apply Queue ",
                    callback=self._on_apply_queue_slots_clicked,
                )
                dpg.add_text("0 = Unlimited", color=(140, 140, 140))

            dpg.add_spacer(height=5)

            # Queue Table
            with dpg.child_window(height=140, border=True):
                dpg.add_text("TRANSFERS QUEUE", color=(100, 180, 255))
                with dpg.table(
                    header_row=True,
                    resizable=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_outerH=True,
                    borders_innerV=True,
                    tag="torrent_queue_table",
                ):
                    dpg.add_table_column(
                        label="Name",
                        width_stretch=True,
                        init_width_or_weight=0.4,
                    )
                    dpg.add_table_column(
                        label="Size",
                        width_fixed=True,
                        init_width_or_weight=90,
                    )
                    dpg.add_table_column(
                        label="Progress",
                        width_fixed=True,
                        init_width_or_weight=120,
                    )
                    dpg.add_table_column(
                        label="Priority",
                        width_fixed=True,
                        init_width_or_weight=90,
                    )
                    dpg.add_table_column(
                        label="Status",
                        width_fixed=True,
                        init_width_or_weight=150,
                    )
                    dpg.add_table_column(
                        label="Down / Up",
                        width_fixed=True,
                        init_width_or_weight=135,
                    )

            dpg.add_spacer(height=10)

            # Inspector
            with dpg.child_window(height=115, border=True):
                self.title_text = dpg.add_text(
                    "Torrent: Waiting for selection...",
                    color=(0, 255, 128),
                )
                self.status_text = dpg.add_text(
                    "Status: Idle",
                    color=(180, 180, 180),
                )
                dpg.add_spacer(height=5)

                self.progress_bar = dpg.add_progress_bar(
                    default_value=0.0,
                    width=-1,
                    height=22,
                )
                self.progress_label = dpg.add_text(
                    "0.0% Complete (0 / 0 Pieces)",
                    color=(200, 200, 200),
                )

            dpg.add_spacer(height=10)

            # Selected-torrent detail views. General preserves the existing
            # inspector metrics while Peers exposes live connection telemetry.
            with dpg.tab_bar():
                with dpg.tab(label="General"):
                    with dpg.group(horizontal=True):
                        with dpg.child_window(width=520, height=285, border=True):
                            dpg.add_text("TRANSFER METRICS", color=(100, 180, 255))
                            dpg.add_separator()
                            self.speed_text = dpg.add_text("Download Speed: 0.0 KB/s")
                            self.upload_speed_text = dpg.add_text("Upload Speed: 0.0 KB/s")
                            self.downloaded_text = dpg.add_text("Downloaded: 0.0 MB / 0.0 MB")
                            self.uploaded_text = dpg.add_text("Uploaded: 0.0 MB")
                            self.peers_text = dpg.add_text("Connected Peers: 0")

                        with dpg.child_window(width=-1, height=285, border=True):
                            dpg.add_text("SWARM STATUS", color=(255, 200, 100))
                            dpg.add_separator()
                            self.state_text = dpg.add_text("Session State: Idle")
                            self.client_id_text = dpg.add_text("Client ID: Salix_T 1.0")
                            self.listen_port_text = dpg.add_text("Listen Port: --")
                            self.storage_text = dpg.add_text("Storage: Downloads")
                            self.lpd_text = dpg.add_text("LAN Discovery: --")
                            self.health_text = dpg.add_text("Swarm Health: Active")

                            dpg.add_spacer(height=5)
                            dpg.add_separator()
                            dpg.add_text("TRANSFER LIMITS", color=(180, 160, 255))
                            dpg.add_text("0 = Unlimited", color=(150, 150, 150))

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

                            with dpg.group(horizontal=True):
                                dpg.add_button(
                                    label=" Apply Limits ",
                                    callback=self._on_apply_limits_clicked,
                                )
                                dpg.add_button(
                                    label=" Unlimited ",
                                    callback=self._on_unlimited_limits_clicked,
                                )

                            self.limit_status_text = dpg.add_text(
                                "Limits: Down Unlimited | Up Unlimited",
                                color=(170, 170, 170),
                            )


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
                dpg.add_button(
                    label=" Remove from SalixTorrent ",
                    callback=lambda: self._confirm_remove_torrent(False),
                )
                dpg.add_button(
                    label=" Remove + Delete Data ",
                    callback=lambda: self._confirm_remove_torrent(True),
                )
                dpg.add_button(
                    label=" Cancel ",
                    callback=lambda: dpg.hide_item(self.remove_torrent_modal),
                )

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

            dpg.add_separator()

            remove_item = dpg.add_menu_item(
                label="Remove Torrent...",
                user_data=info_hash,
                callback=lambda s, a, u: self._context_remove(u),
            )

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
            "start": start_item,
            "pause": pause_item,
            "resume": resume_item,
            "stop": stop_item,
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
        dpg.configure_item(menu["start"], enabled=can_start)
        dpg.configure_item(menu["pause"], enabled=can_pause)
        dpg.configure_item(menu["resume"], enabled=can_resume)
        dpg.configure_item(menu["stop"], enabled=can_stop)
        dpg.configure_item(menu["remove"], enabled=True)

    def _refresh_context_menu_states(self):
        for info_hash in self.torrent_order:
            self._refresh_context_menu_state(info_hash)

    def _reset_inspector(self):
        dpg.set_value(self.title_text, "Torrent: Waiting for selection...")
        dpg.set_value(self.status_text, "Status: Idle")
        dpg.set_value(self.progress_bar, 0.0)
        dpg.set_value(self.progress_label, "0.0% Complete (0 / 0 Pieces)")
        dpg.set_value(self.speed_text, "Download Speed: 0.0 KB/s")
        dpg.set_value(self.upload_speed_text, "Upload Speed: 0.0 KB/s")
        dpg.set_value(self.downloaded_text, "Downloaded: 0.0 MB / 0.0 MB")
        dpg.set_value(self.uploaded_text, "Uploaded: 0.0 MB")
        dpg.set_value(self.peers_text, "Connected Peers: 0")
        dpg.set_value(self.state_text, "Session State: Idle")
        dpg.set_value(self.listen_port_text, "Listen Port: --")
        dpg.set_value(self.storage_text, "Storage: Downloads")
        dpg.set_value(self.lpd_text, "LAN Discovery: --")
        dpg.set_value(self.health_text, "Swarm Health: Active")
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
        speed_str = f"{down_kbps:.1f} / {up_kbps:.1f} KB/s"
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

    def _select_torrent(self, info_hash: str):
        self.active_info_hash = info_hash
        self._limit_controls_hash = ""
        self.manager.set_selected_torrent(info_hash)

        for h, row in self.torrent_rows.items():
            dpg.set_value(row["name"], h == info_hash)

        if info_hash in self.latest_stats:
            self._render_inspector(self.latest_stats[info_hash])

    def _render_inspector(self, msg: dict):
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
                    "Fast resume restored — "
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
                    f"{msg.get('wanted_total_pieces', 0)} Wanted Pieces) — "
                    f"{total_prog * 100:.2f}% of full torrent"
                ),
            )
        else:
            prog = msg["progress"]
            dpg.set_value(self.progress_bar, prog)

            suffix = " — Seeding" if state == "Seeding" else ""
            dpg.set_value(
                self.progress_label,
                (
                    f"{prog * 100:.2f}% Complete "
                    f"({msg['completed_pieces']} / {msg['total_pieces']} Pieces){suffix}"
                ),
            )

        dpg.set_value(
            self.speed_text,
            f"Download Speed: {msg.get('speed_kbps', 0.0):,.1f} KB/s",
        )
        dpg.set_value(
            self.upload_speed_text,
            f"Upload Speed: {msg.get('upload_speed_kbps', 0.0):,.1f} KB/s",
        )
        dl_mb = msg["downloaded_bytes"] / (1024 * 1024)
        up_mb = msg.get("uploaded_bytes", 0) / (1024 * 1024)
        tot_mb = msg["total_bytes"] / (1024 * 1024)
        dpg.set_value(
            self.downloaded_text,
            f"Downloaded: {dl_mb:,.1f} MB / {tot_mb:,.1f} MB",
        )
        dpg.set_value(self.uploaded_text, f"Uploaded: {up_mb:,.1f} MB")
        dpg.set_value(
            self.peers_text,
            f"Connected Peers: {msg['connected_peers']}",
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

        listen_port = msg.get("listen_port", 0)
        dpg.set_value(
            self.listen_port_text,
            f"Listen Port: {listen_port if listen_port else '--'}",
        )

        storage_mode = msg.get("storage_mode", "Download")
        if storage_mode == "External Seed":
            dpg.set_value(self.storage_text, "Storage: External Seed (read-only)")
        else:
            dpg.set_value(self.storage_text, "Storage: Downloads")

        local_count = int(msg.get("local_peers_discovered", 0))
        if msg.get("local_discovery_enabled"):
            dpg.set_value(
                self.lpd_text,
                f"LAN Discovery: Active ({local_count} peer(s) found)",
            )
        else:
            dpg.set_value(self.lpd_text, "LAN Discovery: --")

        error_message = str(msg.get("error_message") or "")
        if error_message:
            dpg.set_value(self.health_text, f"Notice: {error_message}")
        else:
            dpg.set_value(self.health_text, "Swarm Health: Active")

        self.peer_view.render(msg)
        self.piece_view.render(msg)
        self.file_view.render(msg)
        self.source_view.render(msg)
        self.speed_view.render(msg)

    def update(self, delta_time: float):
        while not self.ui_queue.empty():
            try:
                msg = self.ui_queue.get_nowait()
                if msg.get("type") == "TRANSFER_STATS":
                    h = msg["info_hash"]
                    if h in self._removed_info_hashes:
                        continue

                    self.latest_stats[h] = msg

                    if not self.active_info_hash:
                        self.active_info_hash = h
                        self.manager.set_selected_torrent(h)

                    self._update_table_row(msg)

                    if self.active_info_hash == h:
                        self._render_inspector(msg)

                elif msg.get("type") == "TORRENT_REMOVED":
                    self._handle_torrent_removed(msg)
            except queue.Empty:
                break
