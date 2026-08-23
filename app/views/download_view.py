# app/views/download_view.py

import os
import queue
import tkinter as tk
from tkinter import filedialog
import dearpygui.dearpygui as dpg
from app.logic.torrent_manager import TorrentManager


class DownloadView:
    def __init__(self, ui_queue: queue.Queue):
        self.ui_queue = ui_queue
        self.manager = TorrentManager.get_instance()
        self.active_info_hash: str = ""
        self.torrent_rows = {}
        self.latest_stats = {}
        self._limit_controls_hash: str = ""

    def build_view(self, parent_tag: str | int = "primary_window"):
        with dpg.group(parent=parent_tag):
            # Top Controls
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=" + Open Torrent ",
                    callback=self._open_native_file_dialog
                )
                dpg.add_spacer(width=10)
                dpg.add_button(
                    label=" Start / Resume ",
                    callback=self._on_resume_clicked
                )
                dpg.add_button(
                    label=" Pause ",
                    callback=self._on_pause_clicked
                )
                dpg.add_button(
                    label=" Stop ",
                    callback=self._on_stop_clicked
                )

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
                    tag="torrent_queue_table"
                ):
                    dpg.add_table_column(label="Name", width_stretch=True, init_width_or_weight=0.4)
                    dpg.add_table_column(label="Size", width_fixed=True, init_width_or_weight=90)
                    dpg.add_table_column(label="Progress", width_fixed=True, init_width_or_weight=120)
                    dpg.add_table_column(label="Status", width_fixed=True, init_width_or_weight=150)
                    dpg.add_table_column(label="Down / Up", width_fixed=True, init_width_or_weight=135)

            dpg.add_spacer(height=10)

            # Inspector
            with dpg.child_window(height=115, border=True):
                self.title_text = dpg.add_text("Torrent: Waiting for selection...", color=(0, 255, 128))
                self.status_text = dpg.add_text("Status: Idle", color=(180, 180, 180))
                dpg.add_spacer(height=5)
                
                self.progress_bar = dpg.add_progress_bar(default_value=0.0, width=-1, height=22)
                self.progress_label = dpg.add_text("0.0% Complete (0 / 0 Pieces)", color=(200, 200, 200))

            dpg.add_spacer(height=10)

            # Telemetry Metrics
            with dpg.group(horizontal=True):
                with dpg.child_window(width=520, height=245, border=True):
                    dpg.add_text("TRANSFER METRICS", color=(100, 180, 255))
                    dpg.add_separator()
                    self.speed_text = dpg.add_text("Download Speed: 0.0 KB/s")
                    self.upload_speed_text = dpg.add_text("Upload Speed: 0.0 KB/s")
                    self.downloaded_text = dpg.add_text("Downloaded: 0.0 MB / 0.0 MB")
                    self.uploaded_text = dpg.add_text("Uploaded: 0.0 MB")
                    self.peers_text = dpg.add_text("Connected Peers: 0")

                with dpg.child_window(width=-1, height=245, border=True):
                    dpg.add_text("SWARM STATUS", color=(255, 200, 100))
                    dpg.add_separator()
                    self.state_text = dpg.add_text("Session State: Idle")
                    self.client_id_text = dpg.add_text("Client ID: Salix_T 1.0")
                    self.listen_port_text = dpg.add_text("Listen Port: --")
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

    def _open_native_file_dialog(self):
        """Native Windows file picker (instant, zero DPG selection bugs)."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Select Torrent File",
            filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")]
        )
        root.destroy()

        if file_path and os.path.exists(file_path):
            session = self.manager.add_torrent(file_path)
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
                    callback=lambda s, a, u: self._select_torrent(u)
                )
                size_cell = dpg.add_text(size_str)
                prog_cell = dpg.add_text(prog_str)
                status_cell = dpg.add_text(state_label)
                speed_cell = dpg.add_text(speed_str)
                self.torrent_rows[h] = (name_cell, size_cell, prog_cell, status_cell, speed_cell)
        else:
            name_cell, size_cell, prog_cell, status_cell, speed_cell = self.torrent_rows[h]
            dpg.set_value(size_cell, size_str)
            dpg.set_value(prog_cell, prog_str)
            dpg.set_value(status_cell, state_label)
            dpg.set_value(speed_cell, speed_str)
            dpg.set_value(name_cell, (self.active_info_hash == h))

    def _select_torrent(self, info_hash: str):
        self.active_info_hash = info_hash
        self._limit_controls_hash = ""

        for h, (name_cell, *_) in self.torrent_rows.items():
            dpg.set_value(name_cell, (h == info_hash))
        
        if info_hash in self.latest_stats:
            self._render_inspector(self.latest_stats[info_hash])

    def _render_inspector(self, msg: dict):
        dpg.set_value(self.title_text, f"Torrent: {msg['torrent_name']}")

        state = msg["state"]
        state_label = msg.get("state_label", state)
        dpg.set_value(
            self.status_text,
            f"Status: {state_label} ({msg['connected_peers']} peers)"
        )
        dpg.set_value(self.state_text, f"Session State: {state_label}")

        # During a payload verification pass, the main progress bar shows the
        # *checking operation* rather than download completion. Download
        # completion remains visible in the transfer table and byte metrics.
        checking_progress = msg.get("checking_progress", 0.0)
        paused_while_checking = (
            state == "Paused"
            and "Checking" in state_label
        )

        if state == "Checking" or paused_while_checking:
            dpg.set_value(self.progress_bar, checking_progress)

            checked_pieces = msg.get("checked_pieces", 0)
            check_total_pieces = msg.get("check_total_pieces", 0)
            dpg.set_value(
                self.progress_label,
                (
                    f"{checking_progress * 100:.1f}% Checked "
                    f"({checked_pieces} / {check_total_pieces} Pieces Scanned)"
                )
            )
        elif state == "Fast Resume":
            prog = msg["progress"]
            dpg.set_value(self.progress_bar, prog)
            dpg.set_value(
                self.progress_label,
                (
                    f"Fast resume restored — "
                    f"{msg['completed_pieces']} / {msg['total_pieces']} Pieces Verified"
                )
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
                )
            )

        dpg.set_value(self.speed_text, f"Download Speed: {msg.get('speed_kbps', 0.0):,.1f} KB/s")
        dpg.set_value(self.upload_speed_text, f"Upload Speed: {msg.get('upload_speed_kbps', 0.0):,.1f} KB/s")
        dl_mb = msg["downloaded_bytes"] / (1024 * 1024)
        up_mb = msg.get("uploaded_bytes", 0) / (1024 * 1024)
        tot_mb = msg["total_bytes"] / (1024 * 1024)
        dpg.set_value(self.downloaded_text, f"Downloaded: {dl_mb:,.1f} MB / {tot_mb:,.1f} MB")
        dpg.set_value(self.uploaded_text, f"Uploaded: {up_mb:,.1f} MB")
        dpg.set_value(self.peers_text, f"Connected Peers: {msg['connected_peers']}")

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
            f"Listen Port: {listen_port if listen_port else '--'}"
        )

    def update(self, delta_time: float):
        while not self.ui_queue.empty():
            try:
                msg = self.ui_queue.get_nowait()
                if msg.get("type") == "TRANSFER_STATS":
                    h = msg["info_hash"]
                    self.latest_stats[h] = msg

                    if not self.active_info_hash:
                        self.active_info_hash = h

                    self._update_table_row(msg)

                    if self.active_info_hash == h:
                        self._render_inspector(msg)
            except queue.Empty:
                break
