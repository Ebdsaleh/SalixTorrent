# app/views/speed_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg


class SpeedView:
    """Rolling aggregate download/upload history for the selected torrent."""

    WINDOW_OPTIONS = {
        "30 seconds": 30.0,
        "1 minute": 60.0,
        "2 minutes": 120.0,
    }

    def __init__(self):
        self.summary_text = None
        self.stats_text = None
        self.limit_text = None
        self.window_combo = None
        self.plot_id = None
        self.x_axis = None
        self.y_axis = None
        self.download_series = None
        self.upload_series = None
        self.download_limit_series = None
        self.upload_limit_series = None
        self._latest_snapshot = None

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            with dpg.group(horizontal=True):
                self.summary_text = dpg.add_text(
                    "Speed: select a torrent to inspect transfer history",
                    color=(100, 180, 255),
                )
                dpg.add_spacer(width=20)
                dpg.add_text("Window", color=(160, 160, 160))
                self.window_combo = dpg.add_combo(
                    items=list(self.WINDOW_OPTIONS.keys()),
                    default_value="1 minute",
                    width=115,
                    callback=self._on_window_changed,
                )

            self.stats_text = dpg.add_text(
                "Average: Down 0.0 KB/s | Up 0.0 KB/s   Peak: Down 0.0 KB/s | Up 0.0 KB/s",
                color=(170, 170, 170),
            )
            self.limit_text = dpg.add_text(
                "Limits: Down Unlimited | Up Unlimited",
                color=(170, 170, 170),
            )
            dpg.add_separator()

            with dpg.plot(height=230, width=-1) as self.plot_id:
                dpg.add_plot_legend()
                self.x_axis = dpg.add_plot_axis(
                    dpg.mvXAxis,
                    label="Seconds ago",
                )
                self.y_axis = dpg.add_plot_axis(
                    dpg.mvYAxis,
                    label="KB/s",
                )

                self.download_series = dpg.add_line_series(
                    [],
                    [],
                    label="Download",
                    parent=self.y_axis,
                )
                self.upload_series = dpg.add_line_series(
                    [],
                    [],
                    label="Upload",
                    parent=self.y_axis,
                )
                self.download_limit_series = dpg.add_line_series(
                    [],
                    [],
                    label="Down Limit",
                    parent=self.y_axis,
                )
                self.upload_limit_series = dpg.add_line_series(
                    [],
                    [],
                    label="Up Limit",
                    parent=self.y_axis,
                )

            dpg.add_text(
                "Rolling session history sampled every 0.5 seconds. History resets when SalixTorrent restarts.",
                color=(140, 140, 145),
            )

    @staticmethod
    def _format_rate(kbps: float) -> str:
        try:
            value = max(0.0, float(kbps or 0.0))
        except (TypeError, ValueError):
            value = 0.0

        if value >= 1024.0:
            return f"{value / 1024.0:,.2f} MB/s"
        return f"{value:,.1f} KB/s"

    def _window_seconds(self) -> float:
        if not self.window_combo or not dpg.does_item_exist(self.window_combo):
            return 60.0
        return self.WINDOW_OPTIONS.get(dpg.get_value(self.window_combo), 60.0)

    def _on_window_changed(self, sender=None, app_data=None, user_data=None):
        if self._latest_snapshot:
            self._render_graph(self._latest_snapshot)

    def reset(self):
        self._latest_snapshot = None
        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                "Speed: select a torrent to inspect transfer history",
            )
        if self.stats_text and dpg.does_item_exist(self.stats_text):
            dpg.set_value(
                self.stats_text,
                "Average: Down 0.0 KB/s | Up 0.0 KB/s   Peak: Down 0.0 KB/s | Up 0.0 KB/s",
            )
        if self.limit_text and dpg.does_item_exist(self.limit_text):
            dpg.set_value(self.limit_text, "Limits: Down Unlimited | Up Unlimited")

        for series in (
            self.download_series,
            self.upload_series,
            self.download_limit_series,
            self.upload_limit_series,
        ):
            if series and dpg.does_item_exist(series):
                dpg.set_value(series, [[], []])

    def render(self, snapshot: dict):
        if not self.plot_id or not dpg.does_item_exist(self.plot_id):
            return

        self._latest_snapshot = snapshot
        speed_view = snapshot.get("speed_view") or {}

        current_down = float(speed_view.get("current_download_kbps", 0.0) or 0.0)
        current_up = float(speed_view.get("current_upload_kbps", 0.0) or 0.0)
        average_down = float(speed_view.get("average_download_kbps", 0.0) or 0.0)
        average_up = float(speed_view.get("average_upload_kbps", 0.0) or 0.0)
        peak_down = float(speed_view.get("peak_download_kbps", 0.0) or 0.0)
        peak_up = float(speed_view.get("peak_upload_kbps", 0.0) or 0.0)

        dpg.set_value(
            self.summary_text,
            (
                f"Current: Down {self._format_rate(current_down)} | "
                f"Up {self._format_rate(current_up)}"
            ),
        )
        dpg.set_value(
            self.stats_text,
            (
                f"2-minute average: Down {self._format_rate(average_down)} | "
                f"Up {self._format_rate(average_up)}   "
                f"Peak: Down {self._format_rate(peak_down)} | "
                f"Up {self._format_rate(peak_up)}"
            ),
        )

        down_limit = float(speed_view.get("download_limit_kbps", 0.0) or 0.0)
        up_limit = float(speed_view.get("upload_limit_kbps", 0.0) or 0.0)
        global_down = float(speed_view.get("global_download_limit_kbps", 0.0) or 0.0)
        global_up = float(speed_view.get("global_upload_limit_kbps", 0.0) or 0.0)
        dpg.set_value(
            self.limit_text,
            (
                "Per-torrent: Down "
                + (self._format_rate(down_limit) if down_limit > 0 else "Unlimited")
                + " | Up "
                + (self._format_rate(up_limit) if up_limit > 0 else "Unlimited")
                + "    Global: Down "
                + (self._format_rate(global_down) if global_down > 0 else "Unlimited")
                + " | Up "
                + (self._format_rate(global_up) if global_up > 0 else "Unlimited")
            ),
        )

        self._render_graph(snapshot)

    def _render_graph(self, snapshot: dict):
        speed_view = snapshot.get("speed_view") or {}
        samples = list(speed_view.get("samples") or [])
        window_seconds = self._window_seconds()

        filtered = []
        for sample in samples:
            try:
                age = max(0.0, float(sample.get("age_seconds", 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
            if age <= window_seconds:
                filtered.append((
                    age,
                    max(0.0, float(sample.get("download_kbps", 0.0) or 0.0)),
                    max(0.0, float(sample.get("upload_kbps", 0.0) or 0.0)),
                ))

        # Backend samples arrive oldest -> newest. Negating age produces an
        # intuitive left-to-right timeline from -window seconds to now (0).
        x_values = [-item[0] for item in filtered]
        download_values = [item[1] for item in filtered]
        upload_values = [item[2] for item in filtered]

        dpg.set_value(self.download_series, [x_values, download_values])
        dpg.set_value(self.upload_series, [x_values, upload_values])

        down_limit = max(0.0, float(speed_view.get("download_limit_kbps", 0.0) or 0.0))
        up_limit = max(0.0, float(speed_view.get("upload_limit_kbps", 0.0) or 0.0))

        if down_limit > 0:
            dpg.set_value(
                self.download_limit_series,
                [[-window_seconds, 0.0], [down_limit, down_limit]],
            )
        else:
            dpg.set_value(self.download_limit_series, [[], []])

        if up_limit > 0:
            dpg.set_value(
                self.upload_limit_series,
                [[-window_seconds, 0.0], [up_limit, up_limit]],
            )
        else:
            dpg.set_value(self.upload_limit_series, [[], []])

        dpg.set_axis_limits(self.x_axis, -window_seconds, 0.0)

        candidates = download_values + upload_values
        if down_limit > 0:
            candidates.append(down_limit)
        if up_limit > 0:
            candidates.append(up_limit)
        peak = max(candidates) if candidates else 0.0
        y_max = max(128.0, peak * 1.15)
        dpg.set_axis_limits(self.y_axis, 0.0, y_max)
