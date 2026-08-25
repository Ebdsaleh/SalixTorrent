# app/views/create_torrent_view.py

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.logic.torrent_creator import (
    TorrentCreationCancelled,
    TorrentCreationProgress,
    TorrentCreator,
)
from app.logic.torrent_file import FALLBACK_TRACKERS
from app.logic.torrent_manager import TorrentManager


class CreateTorrentView:
    PIECE_SIZE_OPTIONS = {
        "Auto": None,
        "256 KiB": 256 * 1024,
        "512 KiB": 512 * 1024,
        "1 MiB": 1 * 1024 * 1024,
        "2 MiB": 2 * 1024 * 1024,
        "4 MiB": 4 * 1024 * 1024,
        "8 MiB": 8 * 1024 * 1024,
        "16 MiB": 16 * 1024 * 1024,
    }

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.source_path = ""
        self.output_path = ""
        self._created_source_path = ""
        self._created_torrent_path = ""
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._output_was_user_chosen = False

    @staticmethod
    def _native_root():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        return root

    def build_view(self, parent_tag: str | int = "primary_window"):
        with dpg.group(parent=parent_tag):
            dpg.add_text("CREATE TORRENT", color=(0, 255, 128))
            dpg.add_text(
                "Create a shareable BitTorrent v1 .torrent from a file, archive, or folder.",
                color=(170, 170, 170),
            )
            dpg.add_spacer(height=8)

            with dpg.child_window(height=155, border=True):
                dpg.add_text("SOURCE", color=(100, 180, 255))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    self.select_file_button = dpg.add_button(
                        label=" Select File / Archive ",
                        callback=self._select_file_source,
                    )
                    self.select_folder_button = dpg.add_button(
                        label=" Select Folder ",
                        callback=self._select_folder_source,
                    )
                self.source_text = dpg.add_text("No source selected", wrap=1000)
                self.source_summary = dpg.add_text(
                    "Files such as .zip, .7z and .iso are normal single-file torrents.",
                    color=(160, 160, 160),
                    wrap=1000,
                )

            dpg.add_spacer(height=8)

            with dpg.child_window(height=155, border=True):
                dpg.add_text("OUTPUT", color=(100, 180, 255))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    self.choose_output_button = dpg.add_button(
                        label=" Choose Save Location ",
                        callback=self._choose_output,
                    )
                    self.output_text = dpg.add_text("No output selected", wrap=830)

                with dpg.group(horizontal=True):
                    dpg.add_text("Piece Size")
                    self.piece_size_combo = dpg.add_combo(
                        items=list(self.PIECE_SIZE_OPTIONS.keys()),
                        default_value="Auto",
                        width=130,
                    )
                    self.private_checkbox = dpg.add_checkbox(
                        label="Private torrent",
                        default_value=False,
                    )

                self.comment_input = dpg.add_input_text(
                    label="Comment",
                    hint="Optional comment stored in the .torrent metadata",
                    width=-1,
                )

            dpg.add_spacer(height=8)

            with dpg.child_window(height=175, border=True):
                dpg.add_text("TRACKERS", color=(255, 200, 100))
                dpg.add_text(
                    "One tracker URL per line. Blank lines and lines beginning with # are ignored.",
                    color=(160, 160, 160),
                )
                self.trackers_input = dpg.add_input_text(
                    multiline=True,
                    width=-1,
                    height=105,
                    default_value="\n".join(FALLBACK_TRACKERS),
                )

            dpg.add_spacer(height=8)

            with dpg.child_window(height=145, border=True):
                dpg.add_text("CREATION PROGRESS", color=(180, 160, 255))
                dpg.add_separator()
                self.progress_bar = dpg.add_progress_bar(
                    default_value=0.0,
                    width=-1,
                    height=22,
                )
                self.status_text = dpg.add_text("Ready")
                self.detail_text = dpg.add_text("", wrap=1000)

                with dpg.group(horizontal=True):
                    self.create_button = dpg.add_button(
                        label=" Create Torrent ",
                        callback=self._start_creation,
                    )
                    self.cancel_button = dpg.add_button(
                        label=" Cancel ",
                        callback=self._cancel_creation,
                        enabled=False,
                    )
                    self.start_seeding_button = dpg.add_button(
                        label=" Start Seeding ",
                        callback=self._start_seeding_created_torrent,
                        enabled=False,
                        show=False,
                    )

    def _set_source(self, path: str):
        if not path:
            return

        self.source_path = os.path.abspath(path)
        self._created_source_path = ""
        self._created_torrent_path = ""
        if hasattr(self, "start_seeding_button"):
            dpg.configure_item(self.start_seeding_button, enabled=False, show=False)
        dpg.set_value(self.source_text, self.source_path)

        if os.path.isfile(self.source_path):
            size = os.path.getsize(self.source_path)
            dpg.set_value(
                self.source_summary,
                f"Single-file torrent source — {size / (1024 * 1024):,.2f} MiB",
            )
            default_output = f"{self.source_path}.torrent"
        else:
            dpg.set_value(
                self.source_summary,
                "Folder selected — files are scanned and hashed in the background when creation starts.",
            )
            default_output = os.path.join(
                os.path.dirname(self.source_path),
                f"{os.path.basename(self.source_path.rstrip(os.sep))}.torrent",
            )

        if not self._output_was_user_chosen:
            self.output_path = default_output
            dpg.set_value(self.output_text, self.output_path)

        dpg.set_value(self.status_text, "Ready")
        dpg.set_value(self.detail_text, "")
        dpg.set_value(self.progress_bar, 0.0)

    def _select_file_source(self):
        root = self._native_root()
        try:
            path = filedialog.askopenfilename(
                title="Select File or Archive to Torrent",
                filetypes=[("All Files", "*.*")],
            )
        finally:
            root.destroy()
        self._set_source(path)

    def _select_folder_source(self):
        root = self._native_root()
        try:
            path = filedialog.askdirectory(
                title="Select Folder to Torrent",
                mustexist=True,
            )
        finally:
            root.destroy()
        self._set_source(path)

    def _choose_output(self):
        initial_dir = os.path.dirname(self.output_path or self.source_path) or os.getcwd()
        initial_file = os.path.basename(self.output_path) if self.output_path else "new.torrent"

        root = self._native_root()
        try:
            path = filedialog.asksaveasfilename(
                title="Save Torrent File",
                initialdir=initial_dir,
                initialfile=initial_file,
                defaultextension=".torrent",
                filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")],
            )
        finally:
            root.destroy()

        if path:
            if not path.lower().endswith(".torrent"):
                path += ".torrent"
            self.output_path = os.path.abspath(path)
            self._output_was_user_chosen = True
            dpg.set_value(self.output_text, self.output_path)

    def _trackers(self):
        raw = dpg.get_value(self.trackers_input) or ""
        return raw.splitlines()


    def _set_creation_controls_busy(self, busy: bool):
        enabled = not busy
        for item in (
            self.select_file_button,
            self.select_folder_button,
            self.choose_output_button,
            self.piece_size_combo,
            self.private_checkbox,
            self.comment_input,
            self.trackers_input,
        ):
            dpg.configure_item(item, enabled=enabled)
        dpg.configure_item(self.create_button, enabled=enabled)
        dpg.configure_item(self.cancel_button, enabled=busy)

    def _start_creation(self):
        if self._worker and self._worker.is_alive():
            return

        if not self.source_path or not os.path.exists(self.source_path):
            dpg.set_value(self.status_text, "Select a valid source first.")
            return

        if not self.output_path:
            dpg.set_value(self.status_text, "Choose where to save the .torrent file.")
            return

        piece_label = dpg.get_value(self.piece_size_combo) or "Auto"
        piece_length = self.PIECE_SIZE_OPTIONS.get(piece_label)
        comment = dpg.get_value(self.comment_input) or ""
        private = bool(dpg.get_value(self.private_checkbox))
        trackers = self._trackers()

        source_path = self.source_path
        output_path = self.output_path
        self._cancel_event = threading.Event()
        self._created_source_path = ""
        self._created_torrent_path = ""
        dpg.configure_item(self.start_seeding_button, enabled=False, show=False)
        self._set_creation_controls_busy(True)
        dpg.set_value(self.progress_bar, 0.0)
        dpg.set_value(self.status_text, "Starting...")
        dpg.set_value(self.detail_text, "")

        def on_progress(progress: TorrentCreationProgress):
            self._events.put(("progress", progress))

        def worker():
            try:
                result = TorrentCreator.create(
                    source_path=source_path,
                    output_path=output_path,
                    trackers=trackers,
                    piece_length=piece_length,
                    comment=comment,
                    private=private,
                    cancel_event=self._cancel_event,
                    progress_callback=on_progress,
                )
                self._events.put(("complete", result))
            except TorrentCreationCancelled:
                self._events.put(("cancelled", None))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        self._worker = threading.Thread(
            target=worker,
            daemon=True,
            name="SalixTorrentCreator",
        )
        self._worker.start()

    def _start_seeding_created_torrent(self):
        if not self._created_torrent_path or not self._created_source_path:
            return

        try:
            session = self.manager.add_seed_torrent(
                self._created_torrent_path,
                self._created_source_path,
            )
            info_hash = session.torrent.hex_info_hash
            self.manager.set_selected_torrent(info_hash)
            self.manager.start_torrent(info_hash)

            dpg.set_value(
                self.status_text,
                "Added to Active Transfers — verifying source for seeding",
            )
            dpg.set_value(
                self.detail_text,
                (
                    f"Source is seeded in place (no copy to downloads):\n"
                    f"{self._created_source_path}"
                ),
            )
            dpg.configure_item(self.start_seeding_button, enabled=False)

            # Switch to the transfer queue so Checking -> Seeding is visible.
            from app.engine.gui_engine import GuiEngine
            GuiEngine.get_instance().switch_scene("DownloadView")

        except Exception as exc:
            dpg.set_value(self.status_text, "Could not start seeding")
            dpg.set_value(self.detail_text, str(exc))

    def _cancel_creation(self):
        if self._cancel_event:
            self._cancel_event.set()
            dpg.set_value(self.status_text, "Cancelling...")
            dpg.configure_item(self.cancel_button, enabled=False)

    @staticmethod
    def _piece_size_text(piece_length: int) -> str:
        if piece_length >= 1024 * 1024:
            return f"{piece_length / (1024 * 1024):g} MiB"
        return f"{piece_length / 1024:g} KiB"

    def _handle_progress(self, progress: TorrentCreationProgress):
        dpg.set_value(self.progress_bar, progress.fraction)

        if progress.phase == "Hashing":
            dpg.set_value(
                self.status_text,
                f"Hashing {progress.fraction * 100:.1f}%",
            )
            mib_done = progress.bytes_hashed / (1024 * 1024)
            mib_total = progress.total_bytes / (1024 * 1024)
            current = f" — {progress.current_file}" if progress.current_file else ""
            dpg.set_value(
                self.detail_text,
                (
                    f"{mib_done:,.1f} / {mib_total:,.1f} MiB hashed | "
                    f"{progress.pieces_hashed:,} pieces{current}"
                ),
            )
        else:
            dpg.set_value(self.status_text, progress.phase)

    def update(self, delta_time: float):
        del delta_time

        while True:
            try:
                event_type, payload = self._events.get_nowait()
            except queue.Empty:
                break

            if event_type == "progress":
                self._handle_progress(payload)

            elif event_type == "complete":
                result = payload
                self.output_path = result.output_path
                self._created_source_path = os.path.abspath(self.source_path)
                self._created_torrent_path = os.path.abspath(result.output_path)
                dpg.set_value(self.output_text, result.output_path)
                dpg.set_value(self.progress_bar, 1.0)
                dpg.set_value(self.status_text, "Torrent created successfully")
                mode = "folder / multi-file" if result.is_multi_file else "single-file"
                skipped = (
                    f" | {result.skipped_symlinks} symlink(s) skipped"
                    if result.skipped_symlinks
                    else ""
                )
                dpg.set_value(
                    self.detail_text,
                    (
                        f"{result.torrent_name} | {mode} | "
                        f"{result.file_count:,} file(s) | "
                        f"{result.total_bytes / (1024 * 1024):,.2f} MiB | "
                        f"{result.piece_count:,} pieces @ "
                        f"{self._piece_size_text(result.piece_length)} | "
                        f"Info Hash: {result.info_hash}{skipped}\n"
                        f"Saved: {result.output_path}"
                    ),
                )
                self._set_creation_controls_busy(False)
                dpg.configure_item(
                    self.start_seeding_button,
                    enabled=True,
                    show=True,
                )

            elif event_type == "cancelled":
                dpg.set_value(self.status_text, "Creation cancelled")
                dpg.set_value(self.detail_text, "No .torrent file was replaced.")
                self._set_creation_controls_busy(False)

            elif event_type == "error":
                dpg.set_value(self.status_text, "Creation failed")
                dpg.set_value(self.detail_text, str(payload))
                self._set_creation_controls_busy(False)


