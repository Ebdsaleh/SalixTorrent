# app/views/piece_view.py

from __future__ import annotations

import math

import dearpygui.dearpygui as dpg

from app.views.help_terms import add_help_tooltip, add_text_tooltip


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
        self.map_info_text = None
        self.map_drawlist = None
        self.table_id = None
        self._row_ids = []

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            self.summary_text = dpg.add_text(
                "Pieces: select a torrent to inspect piece state",
                color=(100, 180, 255),
            )
            add_help_tooltip(self.summary_text, "PIECE")
            map_legend = dpg.add_text(
                "Map: Verified | Downloading | Requested | Mixed | Missing | No known source",
                color=(150, 150, 150),
            )
            add_help_tooltip(map_legend, "PIECE_STATE")
            self.map_info_text = dpg.add_text(
                "Piece map waiting for torrent telemetry",
                color=(150, 150, 150),
            )
            add_help_tooltip(self.map_info_text, "PIECE_MAP")
            dpg.add_separator()

            self.map_drawlist = dpg.add_drawlist(
                width=-1,
                height=self.MAP_HEIGHT,
            )
            add_help_tooltip(self.map_drawlist, "PIECE_MAP")

            dpg.add_separator()
            details_heading = dpg.add_text(
                "DETAILS — active pieces and the next incomplete range",
                color=(180, 160, 255),
            )
            add_text_tooltip(details_heading, "Focused piece details\n\nTo keep the interface responsive on torrents with thousands of pieces, SalixTorrent shows active/requested pieces plus useful nearby incomplete context rather than continuously rendering every piece as a table row.")

            with dpg.table(
                header_row=True,
                resizable=True,
                policy=dpg.mvTable_SizingStretchProp,
                borders_outerH=True,
                borders_innerH=True,
                borders_innerV=True,
                scrollY=True,
                height=120,
            ) as self.table_id:
                piece_col = dpg.add_table_column(
                    label="Piece",
                    width_fixed=True,
                    init_width_or_weight=75,
                )
                size_col = dpg.add_table_column(
                    label="Size",
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                progress_col = dpg.add_table_column(
                    label="Progress",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                blocks_col = dpg.add_table_column(
                    label="Blocks",
                    width_stretch=True,
                    init_width_or_weight=0.28,
                )
                availability_col = dpg.add_table_column(
                    label="Availability",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                state_col = dpg.add_table_column(
                    label="State",
                    width_fixed=True,
                    init_width_or_weight=110,
                )
                add_help_tooltip(piece_col, "PIECE")
                add_help_tooltip(size_col, "PIECE_SIZE")
                add_text_tooltip(progress_col, "Piece progress\n\nHow much of this piece's block payload has arrived. A piece at 100% is not trusted until its SHA-1 hash passes verification.")
                add_help_tooltip(blocks_col, "BLOCK")
                add_help_tooltip(availability_col, "PIECE_AVAILABILITY")
                add_help_tooltip(state_col, "PIECE_STATE")

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

    def _clear_rows(self):
        for row_id in self._row_ids:
            if dpg.does_item_exist(row_id):
                dpg.delete_item(row_id)
        self._row_ids.clear()

    def _clear_map(self):
        if self.map_drawlist and dpg.does_item_exist(self.map_drawlist):
            dpg.delete_item(self.map_drawlist, children_only=True)

    def reset(self):
        self._clear_rows()
        self._clear_map()

        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                "Pieces: select a torrent to inspect piece state",
            )
        if self.map_info_text and dpg.does_item_exist(self.map_info_text):
            dpg.set_value(
                self.map_info_text,
                "Piece map waiting for torrent telemetry",
            )

    def _render_map(self, piece_view: dict):
        if not self.map_drawlist or not dpg.does_item_exist(self.map_drawlist):
            return

        cells = list(piece_view.get("map_cells") or [])
        self._clear_map()

        if not cells:
            return

        try:
            rect_size = dpg.get_item_rect_size(self.map_drawlist)
            width = float(rect_size[0]) if rect_size else 0.0
        except Exception:
            width = 0.0

        if width < 100:
            width = 1000.0

        # Keep cells wide enough to remain legible. Large torrents are already
        # bucketed by the backend, so this usually becomes a compact 6–8 row map.
        columns = max(24, min(128, int(width // 7)))
        rows = max(1, math.ceil(len(cells) / columns))
        cell_width = width / columns
        cell_height = self.MAP_HEIGHT / rows

        for index, cell in enumerate(cells):
            row = index // columns
            column = index % columns

            x1 = column * cell_width
            y1 = row * cell_height
            x2 = x1 + max(1.0, cell_width - 1.0)
            y2 = y1 + max(1.0, cell_height - 1.0)

            state = str(cell.get("state", "missing"))
            fill = self.MAP_COLORS.get(state, self.MAP_COLORS["missing"])

            dpg.draw_rectangle(
                (x1, y1),
                (x2, y2),
                color=(35, 35, 40, 255),
                fill=fill,
                thickness=1.0,
                parent=self.map_drawlist,
            )

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
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
                f"Pieces: {verified:,} / {total:,} verified | "
                f"{downloading:,} downloading | {requested:,} requested | "
                f"{missing:,} missing | Availability: {availability:.2f}"
            ),
        )

        cell_count = len(piece_view.get("map_cells") or [])
        pieces_per_cell = int(piece_view.get("pieces_per_map_cell", 1) or 1)
        if pieces_per_cell <= 1:
            map_info = f"Piece Map: {cell_count:,} cells — one cell per piece"
        else:
            map_info = (
                f"Piece Map: {cell_count:,} cells — up to {pieces_per_cell:,} pieces per cell "
                "(large torrents are compacted for performance)"
            )
        dpg.set_value(self.map_info_text, map_info)

        self._render_map(piece_view)
        self._clear_rows()

        for piece in list(piece_view.get("details") or []):
            progress = max(0.0, min(1.0, float(piece.get("progress", 0.0) or 0.0)))
            availability_count = int(piece.get("availability", 0) or 0)

            with dpg.table_row(parent=self.table_id) as row_id:
                dpg.add_text(str(int(piece.get("index", 0) or 0)))
                dpg.add_text(self._format_size(piece.get("length", 0)))
                dpg.add_text(f"{progress * 100:.1f}%")
                dpg.add_text(self._format_blocks(piece))
                dpg.add_text(str(availability_count))
                dpg.add_text(str(piece.get("state", "Missing")))

            self._row_ids.append(row_id)


