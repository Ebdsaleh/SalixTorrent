# app/views/file_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg


class FileView:
    """Live per-file progress for single-file and multi-file torrents."""

    STATE_COLORS = {
        "Complete": (100, 180, 255),
        "Downloading": (0, 255, 128),
        "Requested": (255, 200, 100),
        "Partial": (180, 160, 255),
        "Missing": (155, 155, 160),
    }

    def __init__(self):
        self.summary_text = None
        self.storage_text = None
        self.note_text = None
        self.table_id = None
        self._rows = {}
        self._current_info_hash = ""

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            self.summary_text = dpg.add_text(
                "Files: select a torrent to inspect payload files",
                color=(100, 180, 255),
            )
            self.storage_text = dpg.add_text(
                "Storage Root: --",
                color=(180, 180, 180),
            )
            self.note_text = dpg.add_text(
                "Per-file progress counts SHA-1 verified bytes only.",
                color=(150, 150, 150),
            )
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
                dpg.add_table_column(
                    label="File",
                    width_stretch=True,
                    init_width_or_weight=0.50,
                )
                dpg.add_table_column(
                    label="Size",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="Progress",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                dpg.add_table_column(
                    label="Pieces",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                dpg.add_table_column(
                    label="State",
                    width_fixed=True,
                    init_width_or_weight=115,
                )

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

    def _clear_rows(self):
        for row in self._rows.values():
            row_id = row.get("row")
            if row_id and dpg.does_item_exist(row_id):
                dpg.delete_item(row_id)
        self._rows.clear()

    def reset(self):
        self._clear_rows()
        self._current_info_hash = ""

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
                "Per-file progress counts SHA-1 verified bytes only.",
            )

    def _create_row(self, record: dict):
        index = int(record.get("index", 0) or 0)
        state = str(record.get("state", "Missing"))
        color = self.STATE_COLORS.get(state, self.STATE_COLORS["Missing"])

        with dpg.table_row(parent=self.table_id) as row_id:
            path_cell = dpg.add_text(str(record.get("path", "")))
            size_cell = dpg.add_text(self._format_size(record.get("length", 0)))
            progress_cell = dpg.add_text("0.0%")
            pieces_cell = dpg.add_text(str(record.get("piece_span", "--")))
            state_cell = dpg.add_text(state, color=color)

        self._rows[index] = {
            "row": row_id,
            "path": path_cell,
            "size": size_cell,
            "progress": progress_cell,
            "pieces": pieces_cell,
            "state": state_cell,
        }
        return self._rows[index]

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
            return

        file_view = snapshot.get("file_view") or {}
        info_hash = str(snapshot.get("info_hash") or "")

        if info_hash != self._current_info_hash:
            self._clear_rows()
            self._current_info_hash = info_hash

        file_count = int(file_view.get("file_count", 0) or 0)
        displayed_count = int(file_view.get("displayed_count", 0) or 0)
        total_bytes = int(file_view.get("total_bytes", 0) or 0)
        verified_bytes = int(file_view.get("verified_bytes", 0) or 0)
        progress = 1.0 if total_bytes == 0 else max(
            0.0,
            min(1.0, verified_bytes / total_bytes),
        )
        kind = "multi-file" if file_view.get("is_multi_file") else "single-file"
        storage_mode = str(file_view.get("storage_mode", "Download"))

        dpg.set_value(
            self.summary_text,
            (
                f"Files: {file_count:,} ({kind}) | "
                f"Verified: {self._format_size(verified_bytes)} / {self._format_size(total_bytes)} "
                f"({progress * 100:.2f}%) | Storage: {storage_mode}"
            ),
        )
        dpg.set_value(
            self.storage_text,
            f"Storage Root: {file_view.get('backing_path') or '--'}",
        )

        if file_view.get("truncated"):
            note = (
                f"Showing {displayed_count:,} of {file_count:,} files around the current "
                "download position and active transfers. Per-file progress counts verified bytes."
            )
        else:
            note = "Per-file progress counts SHA-1 verified bytes only; active pieces are labelled separately."
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
            color = self.STATE_COLORS.get(state, self.STATE_COLORS["Missing"])

            dpg.set_value(row["path"], str(record.get("path", "")))
            dpg.set_value(row["size"], self._format_size(record.get("length", 0)))
            dpg.set_value(row["progress"], f"{progress_value * 100:.1f}%")
            dpg.set_value(row["pieces"], str(record.get("piece_span", "--")))
            dpg.set_value(row["state"], state)
            dpg.configure_item(row["state"], color=color)

        for index in list(self._rows):
            if index in visible_indices:
                continue
            row_id = self._rows[index].get("row")
            if row_id and dpg.does_item_exist(row_id):
                dpg.delete_item(row_id)
            self._rows.pop(index, None)
