# app/views/piece_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg

from app.engine.state_grid_hosts import DearPyGuiStateGridHost
from app.engine.table_hosts import DearPyGuiTableHost
from app.framework.live_data import (
    LiveTable,
    StateGrid,
    StateGridCell,
    StateGridFrame,
    TableCell,
    TableColumnSpec,
    TableFrame,
    TableRow,
)
from app.localization import tr

from app.views.help_terms import add_help_tooltip, add_text_tooltip, help_text


class PieceView:
    """Compact torrent piece map plus a focused detailed piece table."""

    MAP_HEIGHT = 92

    MAP_COLORS = {
        "verified": (60, 155, 235, 255),
        "downloading": (0, 255, 128, 255),
        "requested": (255, 200, 100, 255),
        "mixed": (180, 160, 255, 255),
        "missing": (58, 58, 64, 255),
        "unavailable": (180, 75, 75, 255),
    }

    def __init__(self):
        self.summary_text = None
        self.scheduler_text = None
        self.disk_text = None
        self.map_info_text = None
        self.map_drawlist = None
        self.table_id = None
        self.state_grid = None
        self.live_table = None

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=-1, border=True) as content:
            self.summary_text = dpg.add_text(
                tr('view.piece_view.pieces_select_a_torrent_to_inspect_piece', "Pieces: select a torrent to inspect piece state"),
                color=(100, 180, 255),
            )
            add_help_tooltip(self.summary_text, "PIECE")
            self.scheduler_text = dpg.add_text(
                tr('view.piece_view.scheduler_rarest_first_pipeline_adaptive_endgame_standby', "Scheduler: Rarest-first | Pipeline: adaptive | Endgame: Standby"),
                color=(155, 155, 160),
            )
            add_help_tooltip(self.scheduler_text, "REQUEST_SCHEDULER")
            self.disk_text = dpg.add_text(
                tr('view.piece_view.disk_i_o_writer_idle_buffer_0', "Disk I/O: writer idle | buffer 0 B | recent-piece cache 0 B"),
                color=(150, 150, 150),
            )
            add_help_tooltip(self.disk_text, "DISK_IO_PIPELINE")
            map_legend = dpg.add_text(
                tr('view.piece_view.map_verified_downloading_requested_mixed_missing_no', "Map: Verified | Downloading | Requested | Mixed | Missing | No known source"),
                color=(150, 150, 150),
            )
            add_help_tooltip(map_legend, "PIECE_STATE")
            self.map_info_text = dpg.add_text(
                tr('view.piece_view.piece_map_waiting_for_torrent_telemetry', "Piece map waiting for torrent telemetry"),
                color=(150, 150, 150),
            )
            add_help_tooltip(self.map_info_text, "PIECE_MAP")
            dpg.add_separator()

            self.state_grid = StateGrid(DearPyGuiStateGridHost())
            grid_binding = self.state_grid.build(parent=content, height=self.MAP_HEIGHT)
            self.map_drawlist = grid_binding.grid
            add_help_tooltip(self.map_drawlist, "PIECE_MAP")

            dpg.add_separator()
            details_heading = dpg.add_text(
                tr('view.piece_view.details_active_pieces_and_the_next_incomplete', "DETAILS - active pieces and the next incomplete range"),
                color=(180, 160, 255),
            )
            add_text_tooltip(details_heading, tr('view.piece_view.focused_piece_details_to_keep_the_interface', "Focused piece details\n\nTo keep the interface responsive on torrents with thousands of pieces, SalixTorrent shows active/requested pieces plus useful nearby incomplete context rather than continuously rendering every piece as a table row."))

            columns = (
                TableColumnSpec("piece", tr('view.piece_view.piece', "Piece"), "fixed", 75),
                TableColumnSpec("size", tr('view.piece_view.size', "Size"), "fixed", 85),
                TableColumnSpec("progress", tr('view.piece_view.progress', "Progress"), "fixed", 90),
                TableColumnSpec("blocks", tr('view.piece_view.blocks', "Blocks"), "stretch", 0.28),
                TableColumnSpec("availability", tr('view.piece_view.availability', "Availability"), "fixed", 95),
                TableColumnSpec("state", tr('view.piece_view.state', "State"), "fixed", 110),
            )
            self.live_table = LiveTable(DearPyGuiTableHost(), columns)
            table_binding = self.live_table.build(parent=content, height=-1)
            self.table_id = table_binding.table
            add_help_tooltip(table_binding.column_item("piece"), "PIECE")
            add_help_tooltip(table_binding.column_item("size"), "PIECE_SIZE")
            add_text_tooltip(table_binding.column_item("progress"), tr('view.piece_view.piece_progress_how_much_of_this_piece', "Piece progress\n\nHow much of this piece's block payload has arrived. A piece at 100% is not trusted until its SHA-1 hash passes verification."))
            add_help_tooltip(table_binding.column_item("blocks"), "BLOCK")
            add_help_tooltip(table_binding.column_item("availability"), "PIECE_AVAILABILITY")
            add_help_tooltip(table_binding.column_item("state"), "PIECE_STATE")

    @staticmethod
    def _format_size(byte_count: int) -> str:
        try:
            value = max(0, int(byte_count))
        except (TypeError, ValueError):
            value = 0

        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.2f} MiB"
        if value >= 1024:
            return f"{value / 1024:.1f} KiB"
        return f"{value} B"

    @staticmethod
    def _format_blocks(piece: dict) -> str:
        received = int(piece.get("received_blocks", 0) or 0)
        requested = int(piece.get("requested_blocks", 0) or 0)
        total = int(piece.get("total_blocks", 0) or 0)

        if requested > 0:
            return f"{received}/{total} received (+{requested} requested)"
        return f"{received}/{total} received"

    def reset(self):
        if self.live_table is not None:
            self.live_table.clear()
        if self.state_grid is not None:
            self.state_grid.clear()

        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                tr('view.piece_view.pieces_select_a_torrent_to_inspect_piece', "Pieces: select a torrent to inspect piece state"),
            )
        if self.scheduler_text and dpg.does_item_exist(self.scheduler_text):
            dpg.set_value(
                self.scheduler_text,
                tr('view.piece_view.scheduler_rarest_first_pipeline_adaptive_endgame_standby', "Scheduler: Rarest-first | Pipeline: adaptive | Endgame: Standby"),
            )
        if self.disk_text and dpg.does_item_exist(self.disk_text):
            dpg.set_value(
                self.disk_text,
                tr('view.piece_view.disk_i_o_writer_idle_buffer_0', "Disk I/O: writer idle | buffer 0 B | recent-piece cache 0 B"),
            )
        if self.map_info_text and dpg.does_item_exist(self.map_info_text):
            dpg.set_value(
                self.map_info_text,
                tr('view.piece_view.piece_map_waiting_for_torrent_telemetry', "Piece map waiting for torrent telemetry"),
            )

    def _piece_row(self, piece: dict) -> TableRow:
        progress = max(0.0, min(1.0, float(piece.get("progress", 0.0) or 0.0)))
        availability_count = int(piece.get("availability", 0) or 0)
        index = int(piece.get("index", 0) or 0)
        return TableRow(
            str(index),
            (
                TableCell(str(index), tooltip=help_text("PIECE")),
                TableCell(self._format_size(piece.get("length", 0)), tooltip=help_text("PIECE_SIZE")),
                TableCell(tr('view.piece_view.value', '{value0:.1f}%', value0=progress * 100), tooltip=tr('view.piece_view.piece_progress_how_much_of_this_piece', "Piece progress\n\nHow much of this piece's block payload has arrived. A piece at 100% is not trusted until its SHA-1 hash passes verification.")),
                TableCell(self._format_blocks(piece), tooltip=help_text("BLOCK")),
                TableCell(str(availability_count), tooltip=help_text("PIECE_AVAILABILITY")),
                TableCell(str(piece.get("state", "Missing")), tooltip=help_text("PIECE_STATE")),
            ),
        )

    def render(self, snapshot: dict):
        if self.live_table is None or not self.live_table.exists():
            return
        if self.state_grid is None or not self.state_grid.exists():
            return

        piece_view = snapshot.get("piece_view") or {}
        total = int(piece_view.get("total", 0) or 0)
        verified = int(piece_view.get("verified", 0) or 0)
        downloading = int(piece_view.get("downloading", 0) or 0)
        requested = int(piece_view.get("requested", 0) or 0)
        missing = int(piece_view.get("missing", 0) or 0)
        availability = float(piece_view.get("swarm_availability", 0.0) or 0.0)

        dpg.set_value(
            self.summary_text,
            (
                tr('view.piece_view.pieces_value_value_verified_value_downloading_value_requested', 'Pieces: {verified:,} / {total:,} verified | {downloading:,} downloading | {requested:,} requested | {missing:,} missing | Availability: {availability:.2f}', verified=verified, total=total, downloading=downloading, requested=requested, missing=missing, availability=availability)
            ),
        )

        endgame = bool(snapshot.get("endgame_active", piece_view.get("endgame_active", False)))
        remaining_blocks = int(snapshot.get("remaining_wanted_blocks", piece_view.get("remaining_wanted_blocks", 0)) or 0)
        outstanding = int(snapshot.get("outstanding_download_requests", piece_view.get("outstanding_wire_requests", 0)) or 0)
        duplicates = int(snapshot.get("duplicate_download_requests", piece_view.get("duplicate_wire_requests", 0)) or 0)
        pipeline_min = int(snapshot.get("request_pipeline_min", 0) or 0)
        pipeline_max = int(snapshot.get("request_pipeline_max", 0) or 0)
        timeout_seconds = float(snapshot.get("request_timeout_seconds", 0.0) or 0.0)
        endgame_label = "ACTIVE" if endgame else "Standby"
        pipeline_label = (
            f"adaptive {pipeline_min}-{pipeline_max}/peer"
            if pipeline_min and pipeline_max else "adaptive"
        )
        timeout_label = f"{timeout_seconds:g}s" if timeout_seconds else "--"
        dpg.set_value(
            self.scheduler_text,
            (
                tr('view.piece_view.scheduler_rarest_first_pipeline_value_timeout_value_endgame', 'Scheduler: Rarest-first | Pipeline: {pipeline_label} | Timeout: {timeout_label} | Endgame: {endgame_label} | Remaining blocks: {remaining_blocks:,} | Outstanding: {outstanding:,} ({duplicates:,} duplicate)', pipeline_label=pipeline_label, timeout_label=timeout_label, endgame_label=endgame_label, remaining_blocks=remaining_blocks, outstanding=outstanding, duplicates=duplicates)
            ),
        )

        disk = snapshot.get("disk_io") or piece_view.get("disk_io") or {}
        writer_label = "active" if disk.get("writer_active") else "idle"
        pending_bytes = int(disk.get("pending_bytes", 0) or 0)
        buffer_limit = int(disk.get("buffer_limit_bytes", 0) or 0)
        pending_writes = int(disk.get("pending_writes", 0) or 0)
        cache_bytes = int(disk.get("cache_bytes", 0) or 0)
        cache_limit = int(disk.get("cache_limit_bytes", 0) or 0)
        cache_hits = int(disk.get("cache_hits", 0) or 0)
        cache_misses = int(disk.get("cache_misses", 0) or 0)
        average_ms = float(disk.get("write_latency_average_ms", 0.0) or 0.0)
        pressure_events = int(disk.get("backpressure_events", 0) or 0)
        disk_error = str(disk.get("error") or "")
        disk_label = (
            tr('view.piece_view.disk_i_o_writer_value_buffer_value_value_value', 'Disk I/O: writer {writer_label} | buffer {value1} / {value2} ({pending_writes} pending) | avg write {average_ms:.2f} ms | backpressure {pressure_events} | cache {value6} / {value7} ({cache_hits} hit / {cache_misses} miss)', writer_label=writer_label, value1=self._format_size(pending_bytes), value2=self._format_size(buffer_limit), pending_writes=pending_writes, average_ms=average_ms, pressure_events=pressure_events, value6=self._format_size(cache_bytes), value7=self._format_size(cache_limit), cache_hits=cache_hits, cache_misses=cache_misses)
        )
        if disk_error:
            disk_label += f" | ERROR: {disk_error}"
        if self.disk_text and dpg.does_item_exist(self.disk_text):
            dpg.set_value(self.disk_text, disk_label)

        cell_count = len(piece_view.get("map_cells") or [])
        pieces_per_cell = int(piece_view.get("pieces_per_map_cell", 1) or 1)
        if pieces_per_cell <= 1:
            map_info = tr('view.piece_view.piece_map_value_cells_one_cell_per_piece', 'Piece Map: {cell_count:,} cells - one cell per piece', cell_count=cell_count)
        else:
            map_info = (
                tr('view.piece_view.piece_map_value_cells_up_to_value_pieces_per', 'Piece Map: {cell_count:,} cells - up to {pieces_per_cell:,} pieces per cell (large torrents are compacted for performance)', cell_count=cell_count, pieces_per_cell=pieces_per_cell)
            )
        dpg.set_value(self.map_info_text, map_info)

        map_cells = []
        for index, cell in enumerate(list(piece_view.get("map_cells") or [])):
            state = str(cell.get("state", "missing"))
            fill = self.MAP_COLORS.get(state, self.MAP_COLORS["missing"])
            map_cells.append(StateGridCell(str(index), fill))
        self.state_grid.render(StateGridFrame(map_cells))
        self.live_table.render(
            TableFrame(self._piece_row(piece) for piece in list(piece_view.get("details") or []))
        )
