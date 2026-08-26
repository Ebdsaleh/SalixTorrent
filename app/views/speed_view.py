# app/views/speed_view.py

from __future__ import annotations

import dearpygui.dearpygui as dpg

from app.views.help_terms import add_help_tooltip, add_text_tooltip
from app.views.transfer_rate import (
    choose_plot_unit,
    format_transfer_rate,
    normalize_transfer_rate_unit,
    transfer_rate_value,
)


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
        self._rate_unit = "Auto"

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=315, border=True):
            with dpg.group(horizontal=True):
                self.summary_text = dpg.add_text(
                    "Speed: select a torrent to inspect transfer history",
                    color=(100, 180, 255),
                )
                add_help_tooltip(self.summary_text, "TRANSFER_RATE")
                dpg.add_spacer(width=20)
                window_label = dpg.add_text("Window", color=(160, 160, 160))
                add_help_tooltip(window_label, "SPEED_WINDOW")
                self.window_combo = dpg.add_combo(
                    items=list(self.WINDOW_OPTIONS.keys()),
                    default_value="1 minute",
                    width=115,
                    callback=self._on_window_changed,
                )
                add_help_tooltip(self.window_combo, "SPEED_WINDOW")

            self.stats_text = dpg.add_text(
                "Average: Down 0.0 KB/s | Up 0.0 KB/s   Peak: Down 0.0 KB/s | Up 0.0 KB/s",
                color=(170, 170, 170),
            )
            add_help_tooltip(self.stats_text, "AVERAGE_PEAK")
            self.limit_text = dpg.add_text(
                "Limits: Down Unlimited | Up Unlimited",
                color=(170, 170, 170),
            )
            add_help_tooltip(self.limit_text, "TRANSFER_LIMITS")
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

            add_text_tooltip(self.download_series, "Download history\n\nMeasured payload download rate for the selected torrent across the visible time window.")
            add_text_tooltip(self.upload_series, "Upload history\n\nMeasured payload upload rate for the selected torrent across the visible time window. Upload can occur while downloading as soon as verified pieces are available.")
            add_text_tooltip(self.download_limit_series, "Download limit line\n\nReference line showing the selected torrent's configured download ceiling when one is active. The global shared limit is reported in the text summary above.")
            add_text_tooltip(self.upload_limit_series, "Upload limit line\n\nReference line showing the selected torrent's configured upload ceiling when one is active. The global shared limit is reported in the text summary above.")
            add_help_tooltip(self.plot_id, "SPEED_HISTORY")
            add_text_tooltip(self.x_axis, "Time axis\n\nThe graph runs from older samples on the left toward the current moment at 0 seconds on the right.")
            add_help_tooltip(self.y_axis, "TRANSFER_RATE")
            history_note = dpg.add_text(
                "Rolling session history sampled every 0.5 seconds. History resets when SalixTorrent restarts.",
                color=(140, 140, 145),
            )
            add_help_tooltip(history_note, "SPEED_HISTORY")

    def set_rate_unit(self, unit: object):
        normalized = normalize_transfer_rate_unit(unit)
        if normalized == self._rate_unit:
            return
        self._rate_unit = normalized
        if self._latest_snapshot:
            self.render(self._latest_snapshot)

    def _format_rate(self, kib_per_second: object) -> str:
        return format_transfer_rate(kib_per_second, self._rate_unit)

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
        raw_download_values = [item[1] for item in filtered]
        raw_upload_values = [item[2] for item in filtered]

        down_limit_raw = max(0.0, float(speed_view.get("download_limit_kbps", 0.0) or 0.0))
        up_limit_raw = max(0.0, float(speed_view.get("upload_limit_kbps", 0.0) or 0.0))

        # A plot needs one consistent Y-axis unit. In Auto mode choose that unit
        # from the largest visible sample/limit, while text readouts may still
        # independently switch between KB/s and MB/s for readability.
        plot_unit = choose_plot_unit(
            raw_download_values + raw_upload_values + [down_limit_raw, up_limit_raw],
            self._rate_unit,
        )
        download_values = [transfer_rate_value(v, plot_unit) for v in raw_download_values]
        upload_values = [transfer_rate_value(v, plot_unit) for v in raw_upload_values]
        down_limit = transfer_rate_value(down_limit_raw, plot_unit) if down_limit_raw > 0 else 0.0
        up_limit = transfer_rate_value(up_limit_raw, plot_unit) if up_limit_raw > 0 else 0.0

        dpg.configure_item(self.y_axis, label=plot_unit)
        dpg.set_value(self.download_series, [x_values, download_values])
        dpg.set_value(self.upload_series, [x_values, upload_values])

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
        minimum_scale = 0.125 if plot_unit in {"MB/s", "Mbps"} else 128.0
        y_max = max(minimum_scale, peak * 1.15)
        dpg.set_axis_limits(self.y_axis, 0.0, y_max)


