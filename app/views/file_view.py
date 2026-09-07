# app/views/file_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg

from app.localization import tr, tr_value
from app.logic.torrent_manager import TorrentManager
from app.engine.table_hosts import DearPyGuiTableHost
from app.framework.interactions import CommandSet, CommandSpec
from app.framework.live_data import LiveTable, TableCell, TableColumnSpec, TableFrame, TableRow
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
        self._table: LiveTable | None = None
        self._menus: dict[int, dict] = {}
        self._current_info_hash = ""
        self._storage_mode = "Download"

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=-1, border=True) as container:
            self.summary_text = dpg.add_text(
                tr('view.file_view.files_select_a_torrent_to_inspect_payload', "Files: select a torrent to inspect payload files"),
                color=(100, 180, 255),
            )
            add_text_tooltip(self.summary_text, tr('view.file_view.files_view_shows_the_selected_torrent_s', "Files view\n\nShows the selected torrent's real payload files, SHA-1-verified progress and selective-download priorities. BitTorrent pieces can cross file boundaries, so file progress is derived from verified piece coverage rather than only file length on disk."))
            self.storage_text = dpg.add_text(
                tr('view.file_view.storage_root', "Storage Root: --"),
                color=(180, 180, 180),
            )
            add_help_tooltip(self.storage_text, "STORAGE_ROOT")
            self.note_text = dpg.add_text(
                tr('view.file_view.right_click_a_file_to_set_high', "Right-click a file to set High, Normal, Low, or Don't Download."),
                color=(150, 150, 150),
            )
            add_help_tooltip(self.note_text, "FILE_PRIORITY")
            dpg.add_separator()

            columns = (
                TableColumnSpec("file", tr('view.file_view.file', "File"), "stretch", 0.45),
                TableColumnSpec("size", tr('view.file_view.size', "Size"), "fixed", 95),
                TableColumnSpec("progress", tr('view.file_view.progress', "Progress"), "fixed", 90),
                TableColumnSpec("pieces", tr('view.file_view.pieces', "Pieces"), "fixed", 90),
                TableColumnSpec("priority", tr('view.file_view.priority', "Priority"), "fixed", 125),
                TableColumnSpec("state", tr('view.file_view.state', "State"), "fixed", 115),
            )
            self._table = LiveTable(DearPyGuiTableHost(), columns)
            binding = self._table.build(parent=container, height=-1)
            self.table_id = binding.table
            add_text_tooltip(binding.column_item("file"), tr('view.file_view.file_relative_payload_path_described_by_the', "File\n\nRelative payload path described by the torrent. Right-click a file row to change selective-download priority."))
            add_text_tooltip(binding.column_item("size"), tr('view.file_view.file_size_payload_bytes_assigned_to_this', "File size\n\nPayload bytes assigned to this file by the torrent metadata."))
            add_help_tooltip(binding.column_item("progress"), "FILE_PROGRESS")
            add_help_tooltip(binding.column_item("pieces"), "FILE_PIECES")
            add_help_tooltip(binding.column_item("priority"), "FILE_PRIORITY")
            add_help_tooltip(binding.column_item("state"), "FILE_STATE")

    @staticmethod
    def _format_size(byte_count: int) -> str:
        try:
            value = max(0, int(byte_count))
        except (TypeError, ValueError):
            value = 0
        gib, mib, kib = 1024 ** 3, 1024 ** 2, 1024
        if value >= gib:
            return f"{value / gib:.2f} GiB"
        if value >= mib:
            return f"{value / mib:.2f} MiB"
        if value >= kib:
            return f"{value / kib:.1f} KiB"
        return f"{value} B"

    def _destroy_menu(self, index: int) -> None:
        menu = self._menus.pop(index, None)
        if not menu:
            return
        for key in ("popup", "right_click_registry"):
            item = menu.get(key)
            if item and dpg.does_item_exist(item):
                dpg.delete_item(item)

    def _clear_rows(self):
        for index in tuple(self._menus):
            self._destroy_menu(index)
        if self._table is not None:
            self._table.clear()

    def reset(self):
        self._clear_rows()
        self._current_info_hash = ""
        self._storage_mode = "Download"
        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(self.summary_text, tr('view.file_view.files_select_a_torrent_to_inspect_payload', "Files: select a torrent to inspect payload files"))
        if self.storage_text and dpg.does_item_exist(self.storage_text):
            dpg.set_value(self.storage_text, tr('view.file_view.storage_root', "Storage Root: --"))
        if self.note_text and dpg.does_item_exist(self.note_text):
            dpg.set_value(self.note_text, tr('view.file_view.right_click_a_file_to_set_high', "Right-click a file to set High, Normal, Low, or Don't Download."))

    def _set_priority(self, file_index: int, priority: str):
        if not self._current_info_hash or self._storage_mode == "External Seed":
            return
        self.manager.set_file_priority(self._current_info_hash, int(file_index), priority)
        menu = self._menus.get(int(file_index))
        if menu:
            popup_id = menu.get("popup")
            if popup_id and dpg.does_item_exist(popup_id):
                dpg.hide_item(popup_id)

    def _priority_commands(self, priority: str) -> CommandSet:
        read_only = self._storage_mode == "External Seed"
        return CommandSet(
            CommandSpec(
                f"priority:{name}",
                tr_value(name),
                enabled=(not read_only and name != priority),
                checked=name == priority,
            )
            for name in self.PRIORITIES
        )

    def _refresh_priority_menu(self, index: int, priority: str):
        menu = self._menus.get(index)
        if not menu:
            return
        commands = self._priority_commands(priority)
        for command in commands.commands:
            item_id = menu.get("priority_items", {}).get(command.key)
            if not item_id or not dpg.does_item_exist(item_id):
                continue
            dpg.configure_item(
                item_id,
                label=(f"* {command.label}" if command.checked else command.label),
                enabled=command.enabled,
            )
        menu["commands"] = commands

    def _on_file_right_clicked(self, file_index: int, popup_id):
        menu = self._menus.get(int(file_index))
        if not menu:
            return
        self._refresh_priority_menu(file_index, menu.get("priority_value", "Normal"))
        dpg.configure_item(popup_id, show=True)

    def _dispatch_priority_command(self, file_index: int, command_key: str):
        menu = self._menus.get(file_index)
        if not menu:
            return
        commands: CommandSet = menu["commands"]
        def run(key: str):
            prefix, priority = key.split(":", 1)
            if prefix != "priority":
                raise ValueError(key)
            self._set_priority(file_index, priority)
        commands.dispatch(command_key, run)

    def _build_priority_menu(self, file_index: int, row_cells, priority: str):
        commands = self._priority_commands(priority)
        with dpg.window(popup=True, show=False, autosize=True, no_title_bar=True) as popup_id:
            priority_title = dpg.add_text(tr('view.file_view.file_priority', "File Priority"), color=(180, 160, 255))
            add_help_tooltip(priority_title, "FILE_PRIORITY")
            dpg.add_separator()
            priority_items = {}
            for command in commands.commands:
                priority_items[command.key] = dpg.add_menu_item(
                    label=command.label,
                    user_data=(file_index, command.key),
                    callback=lambda s, a, u: self._dispatch_priority_command(u[0], u[1]),
                )
                add_help_tooltip(priority_items[command.key], "FILE_PRIORITY")
        with dpg.item_handler_registry() as registry:
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                user_data=(file_index, popup_id),
                callback=lambda s, a, u: self._on_file_right_clicked(u[0], u[1]),
            )
        for cell in row_cells:
            dpg.bind_item_handler_registry(cell, registry)
        self._menus[file_index] = {
            "popup": popup_id,
            "right_click_registry": registry,
            "priority_items": priority_items,
            "priority_value": priority,
            "commands": commands,
        }
        self._refresh_priority_menu(file_index, priority)

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
            facts=(f"Path: {path}", f"Progress: {progress * 100:.1f}% verified", f"Piece span: {record.get('piece_span', '--')}", f"Priority: {priority}", f"State: {state}"),
            footer="Right-click this row to change file priority. 'Don't Download' can still receive a small amount of boundary data when a wanted file shares the same piece.",
        )

    def _row_for_record(self, record: dict) -> TableRow:
        index = int(record.get("index", 0) or 0)
        progress = max(0.0, min(1.0, float(record.get("progress", 0.0) or 0.0)))
        state = str(record.get("state", "Missing"))
        priority = str(record.get("priority", "Normal"))
        context = self._file_context_text(record)
        return TableRow(
            str(index),
            (
                TableCell(str(record.get("path", "")), tooltip=context),
                TableCell(self._format_size(record.get("length", 0)), tooltip=context),
                TableCell(
                    tr('view.file_view.0_0', "0.0%")
                    if progress == 0.0
                    else tr('view.file_view.value', '{value0:.1f}%', value0=progress * 100),
                    tooltip=context,
                ),
                TableCell(str(record.get("piece_span", "--")), tooltip=context),
                TableCell(tr_value(priority), foreground=self.PRIORITY_COLORS.get(priority, self.PRIORITY_COLORS["Normal"]), tooltip=context),
                TableCell(tr_value(state), foreground=self.STATE_COLORS.get(state, self.STATE_COLORS["Missing"]), tooltip=context),
            ),
        )

    def render(self, snapshot: dict):
        if self._table is None or not self._table.exists():
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
        progress = 1.0 if total_bytes == 0 else max(0.0, min(1.0, verified_bytes / total_bytes))
        kind = "multi-file" if file_view.get("is_multi_file") else "single-file"
        wanted_done = int(file_view.get("completed_wanted_pieces", 0) or 0)
        wanted_total = int(file_view.get("wanted_piece_count", 0) or 0)
        dpg.set_value(self.summary_text, tr('view.file_view.files_value_value_verified_value_value_value_wanted', 'Files: {file_count:,} ({kind}) | Verified: {value2} / {value3} ({value4:.2f}%) | Wanted pieces: {wanted_done:,}/{wanted_total:,}', file_count=file_count, kind=kind, value2=self._format_size(verified_bytes), value3=self._format_size(total_bytes), value4=progress * 100, wanted_done=wanted_done, wanted_total=wanted_total))
        dpg.set_value(self.storage_text, tr('view.file_view.storage_root_value', 'Storage Root: {value0}', value0=file_view.get('backing_path') or '--'))

        if self._storage_mode == "External Seed":
            note = tr("view.file_view.external_seed_priority_disabled", "External seed source is read-only; file priorities are disabled while seeding it.")
        elif file_view.get("truncated"):
            note = tr('view.file_view.showing_value_of_value_files_right_click_a_file', "Showing {displayed_count:,} of {file_count:,} files. Right-click a file to set priority. Don't Download skips pieces used only by skipped files.", displayed_count=displayed_count, file_count=file_count)
        else:
            note = tr("view.file_view.priority_boundary_note", "Right-click a file to set priority. Boundary pieces shared with a wanted file may still write a small amount into a skipped neighbouring file.")
        dpg.set_value(self.note_text, note)

        records = list(file_view.get("files") or [])
        rows = tuple(self._row_for_record(record) for record in records)
        incoming = {int(record.get("index", 0) or 0) for record in records}
        for index in tuple(self._menus):
            if index not in incoming:
                self._destroy_menu(index)
        self._table.render(TableFrame(rows))

        by_index = {int(record.get("index", 0) or 0): record for record in records}
        for index, record in by_index.items():
            priority = str(record.get("priority", "Normal"))
            binding = self._table.row_binding(str(index))
            if binding is not None and index not in self._menus:
                self._build_priority_menu(index, binding.cells, priority)
            menu = self._menus.get(index)
            if menu:
                menu["priority_value"] = priority
                self._refresh_priority_menu(index, priority)
