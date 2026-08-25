# app/views/source_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg


class SourceView:
    """Live peer-discovery source telemetry for the selected torrent."""

    STATUS_COLORS = {
        "Active": (0, 255, 128),
        "No Peers": (100, 180, 255),
        "Announcing": (180, 160, 255),
        "Waiting": (155, 155, 160),
        "Timeout": (255, 200, 100),
        "Error": (255, 105, 105),
        "Unsupported": (255, 105, 105),
        "Cancelled": (155, 155, 160),
        "Disabled": (155, 155, 160),
    }

    def __init__(self):
        self.summary_text = None
        self.note_text = None
        self.table_id = None
        self._row_ids = []

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            self.summary_text = dpg.add_text(
                "Sources: select a torrent to inspect peer discovery",
                color=(100, 180, 255),
            )
            self.note_text = dpg.add_text(
                "Active = valid response | No Peers = valid tracker response with zero peers | "
                "Waiting = not queried yet",
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
                height=235,
            ) as self.table_id:
                dpg.add_table_column(
                    label="Source",
                    width_stretch=True,
                    init_width_or_weight=0.38,
                )
                dpg.add_table_column(
                    label="Type",
                    width_fixed=True,
                    init_width_or_weight=65,
                )
                dpg.add_table_column(
                    label="Status",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="Peers",
                    width_fixed=True,
                    init_width_or_weight=65,
                )
                dpg.add_table_column(
                    label="Swarm S/L",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="Response",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                dpg.add_table_column(
                    label="Last Update",
                    width_fixed=True,
                    init_width_or_weight=90,
                )
                dpg.add_table_column(
                    label="Detail",
                    width_stretch=True,
                    init_width_or_weight=0.22,
                )

    @staticmethod
    def _format_age(seconds) -> str:
        if seconds is None:
            return "Never"
        try:
            total = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "Never"

        if total < 60:
            return f"{total}s ago"
        minutes, secs = divmod(total, 60)
        if minutes < 60:
            return f"{minutes}m {secs:02d}s ago"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m ago"

    @staticmethod
    def _format_response(value) -> str:
        if value is None:
            return "--"
        try:
            milliseconds = max(0.0, float(value))
        except (TypeError, ValueError):
            return "--"

        if milliseconds >= 1000.0:
            return f"{milliseconds / 1000.0:.2f}s"
        return f"{milliseconds:.0f}ms"

    @staticmethod
    def _format_swarm(source: dict) -> str:
        seeders = source.get("seeders")
        leechers = source.get("leechers")
        if seeders is None and leechers is None:
            return "--"

        try:
            seeders_text = str(max(0, int(seeders or 0)))
        except (TypeError, ValueError):
            seeders_text = "?"
        try:
            leechers_text = str(max(0, int(leechers or 0)))
        except (TypeError, ValueError):
            leechers_text = "?"
        return f"{seeders_text} / {leechers_text}"

    @staticmethod
    def _detail(source: dict) -> str:
        error = str(source.get("last_error") or "").strip()
        if error:
            return error

        explicit = str(source.get("detail") or "").strip()
        if explicit:
            return explicit

        parts = []
        event = str(source.get("last_event") or "").strip()
        if event:
            parts.append(f"event {event}")

        interval = source.get("interval")
        if interval is not None:
            try:
                parts.append(f"interval {max(0, int(interval))}s")
            except (TypeError, ValueError):
                pass

        query_count = source.get("query_count")
        try:
            count = max(0, int(query_count or 0))
        except (TypeError, ValueError):
            count = 0
        if count:
            parts.append(f"announces {count}")

        return " | ".join(parts) if parts else "--"

    def _clear_rows(self):
        for row_id in self._row_ids:
            if dpg.does_item_exist(row_id):
                dpg.delete_item(row_id)
        self._row_ids.clear()

    def reset(self):
        self._clear_rows()
        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                "Sources: select a torrent to inspect peer discovery",
            )

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
            return

        sources_view = snapshot.get("sources_view") or {}
        sources = list(sources_view.get("sources") or [])
        tracker_count = int(sources_view.get("tracker_count", 0) or 0)
        active_count = int(sources_view.get("active_count", 0) or 0)
        problem_count = int(sources_view.get("problem_count", 0) or 0)
        tracker_peers = int(sources_view.get("tracker_peers_last_seen", 0) or 0)
        lan_peers = int(sources_view.get("lan_peers_seen", 0) or 0)

        if sources:
            summary = (
                f"Sources: {tracker_count} tracker(s) + LAN | "
                f"Responding: {active_count} | Problems: {problem_count} | "
                f"Tracker peers last reported: {tracker_peers} | LAN peers seen: {lan_peers}"
            )
        else:
            summary = "Sources: no peer-discovery telemetry available"
        dpg.set_value(self.summary_text, summary)

        self._clear_rows()

        for source in sources:
            status = str(source.get("status", "Waiting"))
            color = self.STATUS_COLORS.get(status, (180, 180, 180))
            try:
                peers = max(0, int(source.get("peers", 0) or 0))
            except (TypeError, ValueError):
                peers = 0

            with dpg.table_row(parent=self.table_id) as row_id:
                dpg.add_text(str(source.get("source", "Unknown")))
                dpg.add_text(str(source.get("type", "--")))
                dpg.add_text(status, color=color)
                dpg.add_text(str(peers))
                dpg.add_text(self._format_swarm(source))
                dpg.add_text(self._format_response(source.get("response_ms")))
                dpg.add_text(self._format_age(source.get("last_update_seconds")))
                dpg.add_text(self._detail(source))

            self._row_ids.append(row_id)
