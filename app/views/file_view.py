# app/views/file_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg

from app.logic.torrent_manager import TorrentManager
from app.views.help_terms import add_help_tooltip, add_text_tooltip, contextual_text


class FileView:
    """Live per-file progress plus per-file download-priority controls."""

    PRIORITIES = ("High", "Normal", "Low", "Don't Download")

    STATE_COLORS = {
        "Complete": (100, 180, 255),
        "Downloading": (0, 255, 128),
        "Requested": (255, 200, 100),
        "Partial": (180, 160, 255),
        "Missing": (155, 155, 160),
        "Skipped": (120, 120, 125),
    }

    PRIORITY_COLORS = {
        "High": (255, 190, 90),
        "Normal": (190, 190, 195),
        "Low": (150, 170, 220),
        "Don't Download": (125, 125, 130),
    }

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.summary_text = None
        self.storage_text = None
        self.note_text = None
        self.table_id = None
        self._rows = {}
        self._current_info_hash = ""
        self._storage_mode = "Download"

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            self.summary_text = dpg.add_text(
                "Files: select a torrent to inspect payload files",
                color=(100, 180, 255),
            )
            add_text_tooltip(self.summary_text, "Files view\n\nShows the selected torrent's real payload files, SHA-1-verified progress and selective-download priorities. BitTorrent pieces can cross file boundaries, so file progress is derived from verified piece coverage rather than only file length on disk.")
            self.storage_text = dpg.add_text(
                "Storage Root: --",
                color=(180, 180, 180),
            )
            add_help_tooltip(self.storage_text, "STORAGE_ROOT")
            self.note_text = dpg.add_text(
                "Right-click a file to set High, Normal, Low, or Don't Download.",
                color=(150, 150, 150),
            )
            add_help_tooltip(self.note_text, "FILE_PRIORITY")
            dpg.add_separator()

            with dpg.table(
                header_row=True,
                resizable=True,
                policy=dpg.mvTable_SizingStretchProp,
                borders_outerH=True,
                borders_innerH=True,
                borders_innerV=True,
                scrollY=True,
                height=225,
            ) as self.table_id:
                file_col = dpg.add_table_column(
                    label="File",
                    width_stretch=True,
                    init_width_or_weight=0.45,
                )
                size_col = dpg.add_table_column(
                    label="Size",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                progress_col = dpg.add_table_column(
                    label="Progress",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                pieces_col = dpg.add_table_column(
                    label="Pieces",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                priority_col = dpg.add_table_column(
                    label="Priority",
                    width_fixed=True,
                    init_width_or_weight=125,
                )
                state_col = dpg.add_table_column(
                    label="State",
                    width_fixed=True,
                    init_width_or_weight=115,
                )
                add_text_tooltip(file_col, "File\n\nRelative payload path described by the torrent. Right-click a file row to change selective-download priority.")
                add_text_tooltip(size_col, "File size\n\nPayload bytes assigned to this file by the torrent metadata.")
                add_help_tooltip(progress_col, "FILE_PROGRESS")
                add_help_tooltip(pieces_col, "FILE_PIECES")
                add_help_tooltip(priority_col, "FILE_PRIORITY")
                add_help_tooltip(state_col, "FILE_STATE")

    @staticmethod
    def _format_size(byte_count: int) -> str:
        try:
            value = max(0, int(byte_count))
        except (TypeError, ValueError):
            value = 0

        gib = 1024 * 1024 * 1024
        mib = 1024 * 1024
        kib = 1024

        if value >= gib:
            return f"{value / gib:.2f} GiB"
        if value >= mib:
            return f"{value / mib:.2f} MiB"
        if value >= kib:
            return f"{value / kib:.1f} KiB"
        return f"{value} B"

    def _delete_row(self, index: int):
        row = self._rows.pop(index, None)
        if not row:
            return

        row_id = row.get("row")
        if row_id and dpg.does_item_exist(row_id):
            dpg.delete_item(row_id)

        for key in ("popup", "right_click_registry"):
            item = row.get(key)
            if item and dpg.does_item_exist(item):
                dpg.delete_item(item)

    def _clear_rows(self):
        for index in list(self._rows):
            self._delete_row(index)

    def reset(self):
        self._clear_rows()
        self._current_info_hash = ""
        self._storage_mode = "Download"

        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                "Files: select a torrent to inspect payload files",
            )
        if self.storage_text and dpg.does_item_exist(self.storage_text):
            dpg.set_value(self.storage_text, "Storage Root: --")
        if self.note_text and dpg.does_item_exist(self.note_text):
            dpg.set_value(
                self.note_text,
                "Right-click a file to set High, Normal, Low, or Don't Download.",
            )

    def _set_priority(self, file_index: int, priority: str):
        if not self._current_info_hash or self._storage_mode == "External Seed":
            return

        self.manager.set_file_priority(
            self._current_info_hash,
            int(file_index),
            priority,
        )

        row = self._rows.get(int(file_index))
        if row:
            popup_id = row.get("popup")
            if popup_id and dpg.does_item_exist(popup_id):
                dpg.hide_item(popup_id)

    def _refresh_priority_menu(self, row: dict, priority: str):
        read_only = self._storage_mode == "External Seed"
        for name, item_id in row.get("priority_items", {}).items():
            if not dpg.does_item_exist(item_id):
                continue
            dpg.configure_item(
                item_id,
                label=(f"* {name}" if name == priority else name),
                enabled=(not read_only and name != priority),
            )

    def _on_file_right_clicked(self, file_index: int, popup_id):
        row = self._rows.get(int(file_index))
        if not row:
            return
        self._refresh_priority_menu(row, row.get("priority_value", "Normal"))
        dpg.configure_item(popup_id, show=True)

    def _build_priority_menu(self, file_index: int, row_cells):
        with dpg.window(
            popup=True,
            show=False,
            autosize=True,
            no_title_bar=True,
        ) as popup_id:
            priority_title = dpg.add_text("File Priority", color=(180, 160, 255))
            add_help_tooltip(priority_title, "FILE_PRIORITY")
            dpg.add_separator()
            priority_items = {}
            for priority in self.PRIORITIES:
                priority_items[priority] = dpg.add_menu_item(
                    label=priority,
                    user_data=(file_index, priority),
                    callback=lambda s, a, u: self._set_priority(u[0], u[1]),
                )
                add_help_tooltip(priority_items[priority], "FILE_PRIORITY")

        with dpg.item_handler_registry() as right_click_registry:
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                user_data=(file_index, popup_id),
                callback=lambda s, a, u: self._on_file_right_clicked(u[0], u[1]),
            )

        for cell in row_cells:
            dpg.bind_item_handler_registry(cell, right_click_registry)

        return popup_id, right_click_registry, priority_items

    @staticmethod
    def _file_context_text(record: dict) -> str:
        path = str(record.get("path", "")) or "--"
        priority = str(record.get("priority", "Normal"))
        state = str(record.get("state", "Missing"))
        try:
            progress = max(0.0, min(1.0, float(record.get("progress", 0.0) or 0.0)))
        except (TypeError, ValueError):
            progress = 0.0
        return contextual_text(
            "Torrent payload file",
            "This is one file described by the selected torrent. Its progress is based on verified torrent-piece coverage rather than only the file's physical length on disk.",
            facts=(
                f"Path: {path}",
                f"Progress: {progress * 100:.1f}% verified",
                f"Piece span: {record.get('piece_span', '--')}",
                f"Priority: {priority}",
                f"State: {state}",
            ),
            footer="Right-click this row to change file priority. 'Don't Download' can still receive a small amount of boundary data when a wanted file shares the same piece.",
        )

    def _create_row(self, record: dict):
        index = int(record.get("index", 0) or 0)
        state = str(record.get("state", "Missing"))
        priority = str(record.get("priority", "Normal"))
        state_color = self.STATE_COLORS.get(state, self.STATE_COLORS["Missing"])
        priority_color = self.PRIORITY_COLORS.get(
            priority,
            self.PRIORITY_COLORS["Normal"],
        )

        with dpg.table_row(parent=self.table_id) as row_id:
            path_cell = dpg.add_text(str(record.get("path", "")))
            size_cell = dpg.add_text(self._format_size(record.get("length", 0)))
            progress_cell = dpg.add_text("0.0%")
            pieces_cell = dpg.add_text(str(record.get("piece_span", "--")))
            priority_cell = dpg.add_text(priority, color=priority_color)
            state_cell = dpg.add_text(state, color=state_color)

        cells = (
            path_cell,
            size_cell,
            progress_cell,
            pieces_cell,
            priority_cell,
            state_cell,
        )
        row_context = self._file_context_text(record)
        path_tip = add_text_tooltip(path_cell, row_context, wrap=500)
        progress_tip = add_text_tooltip(progress_cell, row_context, wrap=500)
        pieces_tip = add_text_tooltip(pieces_cell, row_context, wrap=500)
        priority_tip = add_text_tooltip(priority_cell, row_context, wrap=500)
        state_tip = add_text_tooltip(state_cell, row_context, wrap=500)
        popup_id, registry, priority_items = self._build_priority_menu(index, cells)

        self._rows[index] = {
            "row": row_id,
            "path": path_cell,
            "size": size_cell,
            "progress": progress_cell,
            "pieces": pieces_cell,
            "priority": priority_cell,
            "state": state_cell,
            "popup": popup_id,
            "right_click_registry": registry,
            "priority_items": priority_items,
            "priority_value": priority,
            "tooltip_items": tuple(
                item for item in (path_tip, progress_tip, pieces_tip, priority_tip, state_tip) if item
            ),
        }
        self._refresh_priority_menu(self._rows[index], priority)
        return self._rows[index]

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
            return

        file_view = snapshot.get("file_view") or {}
        info_hash = str(snapshot.get("info_hash") or "")

        if info_hash != self._current_info_hash:
            self._clear_rows()
            self._current_info_hash = info_hash

        self._storage_mode = str(file_view.get("storage_mode", "Download"))

        file_count = int(file_view.get("file_count", 0) or 0)
        displayed_count = int(file_view.get("displayed_count", 0) or 0)
        total_bytes = int(file_view.get("total_bytes", 0) or 0)
        verified_bytes = int(file_view.get("verified_bytes", 0) or 0)
        progress = 1.0 if total_bytes == 0 else max(
            0.0,
            min(1.0, verified_bytes / total_bytes),
        )
        kind = "multi-file" if file_view.get("is_multi_file") else "single-file"

        wanted_done = int(file_view.get("completed_wanted_pieces", 0) or 0)
        wanted_total = int(file_view.get("wanted_piece_count", 0) or 0)
        dpg.set_value(
            self.summary_text,
            (
                f"Files: {file_count:,} ({kind}) | "
                f"Verified: {self._format_size(verified_bytes)} / {self._format_size(total_bytes)} "
                f"({progress * 100:.2f}%) | Wanted pieces: {wanted_done:,}/{wanted_total:,}"
            ),
        )
        dpg.set_value(
            self.storage_text,
            f"Storage Root: {file_view.get('backing_path') or '--'}",
        )

        if self._storage_mode == "External Seed":
            note = (
                "External seed source is read-only; file priorities are disabled while seeding it."
            )
        elif file_view.get("truncated"):
            note = (
                f"Showing {displayed_count:,} of {file_count:,} files. Right-click a file to set priority. "
                "Don't Download skips pieces used only by skipped files."
            )
        else:
            note = (
                "Right-click a file to set priority. Boundary pieces shared with a wanted file may still "
                "write a small amount into a skipped neighbouring file."
            )
        dpg.set_value(self.note_text, note)

        visible_indices = set()
        for record in list(file_view.get("files") or []):
            index = int(record.get("index", 0) or 0)
            visible_indices.add(index)
            row = self._rows.get(index) or self._create_row(record)

            progress_value = max(
                0.0,
                min(1.0, float(record.get("progress", 0.0) or 0.0)),
            )
            state = str(record.get("state", "Missing"))
            priority = str(record.get("priority", "Normal"))
            state_color = self.STATE_COLORS.get(state, self.STATE_COLORS["Missing"])
            priority_color = self.PRIORITY_COLORS.get(
                priority,
                self.PRIORITY_COLORS["Normal"],
            )

            dpg.set_value(row["path"], str(record.get("path", "")))
            dpg.set_value(row["size"], self._format_size(record.get("length", 0)))
            dpg.set_value(row["progress"], f"{progress_value * 100:.1f}%")
            dpg.set_value(row["pieces"], str(record.get("piece_span", "--")))
            dpg.set_value(row["priority"], priority)
            dpg.configure_item(row["priority"], color=priority_color)
            dpg.set_value(row["state"], state)
            dpg.configure_item(row["state"], color=state_color)
            row["priority_value"] = priority
            self._refresh_priority_menu(row, priority)
            context_text = self._file_context_text(record)
            for tooltip_item in row.get("tooltip_items", ()):
                if dpg.does_item_exist(tooltip_item):
                    dpg.set_value(tooltip_item, context_text)

        for index in list(self._rows):
            if index not in visible_indices:
                self._delete_row(index)


