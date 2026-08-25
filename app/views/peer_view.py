# app/views/peer_view.py

import dearpygui.dearpygui as dpg


class PeerView:
    """Detailed live peer table for the currently selected torrent."""

    def __init__(self):
        self.summary_text = None
        self.table_id = None
        self._row_ids = []

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=285, border=True):
            self.summary_text = dpg.add_text(
                "Peers: select a torrent to inspect its connections",
                color=(100, 180, 255),
            )
            dpg.add_text(
                "Flags: I = we are interested | i = peer interested | "
                "C = peer chokes us | c = we choke peer",
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
                height=215,
            ) as self.table_id:
                dpg.add_table_column(
                    label="Address",
                    width_stretch=True,
                    init_width_or_weight=0.18,
                )
                dpg.add_table_column(
                    label="Client",
                    width_stretch=True,
                    init_width_or_weight=0.16,
                )
                dpg.add_table_column(
                    label="Source",
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                dpg.add_table_column(
                    label="Direction",
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                dpg.add_table_column(
                    label="Pieces",
                    width_fixed=True,
                    init_width_or_weight=75,
                )
                dpg.add_table_column(
                    label="Down",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="Up",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="State",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                dpg.add_table_column(
                    label="Flags",
                    width_fixed=True,
                    init_width_or_weight=70,
                )
                dpg.add_table_column(
                    label="Age",
                    width_fixed=True,
                    init_width_or_weight=70,
                )

    @staticmethod
    def _format_age(seconds: float) -> str:
        try:
            total_seconds = max(0, int(seconds))
        except (TypeError, ValueError):
            total_seconds = 0

        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_progress(value) -> str:
        if value is None:
            return "--"
        try:
            return f"{max(0.0, min(1.0, float(value))) * 100:.1f}%"
        except (TypeError, ValueError):
            return "--"

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
                "Peers: select a torrent to inspect its connections",
            )

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
            return

        peers = list(snapshot.get("peers") or [])
        connected = int(snapshot.get("connected_peers", len(peers)) or 0)
        local_found = int(snapshot.get("local_peers_discovered", 0) or 0)
        state_label = snapshot.get("state_label", snapshot.get("state", "Idle"))

        if connected:
            summary = (
                f"Peers: {connected} connected | LAN discoveries: {local_found} | "
                f"Torrent state: {state_label}"
            )
        else:
            summary = (
                f"Peers: 0 connected | LAN discoveries: {local_found} | "
                f"Torrent state: {state_label} — waiting for peer connections"
            )

        dpg.set_value(self.summary_text, summary)
        self._clear_rows()

        for peer in peers:
            with dpg.table_row(parent=self.table_id) as row_id:
                dpg.add_text(str(peer.get("address", "?")))
                dpg.add_text(str(peer.get("client", "Unknown")))
                dpg.add_text(str(peer.get("source", "Unknown")))
                dpg.add_text(str(peer.get("direction", "--")))
                dpg.add_text(self._format_progress(peer.get("progress")))
                dpg.add_text(
                    f"{float(peer.get('download_speed_kbps', 0.0) or 0.0):,.1f} KB/s"
                )
                dpg.add_text(
                    f"{float(peer.get('upload_speed_kbps', 0.0) or 0.0):,.1f} KB/s"
                )
                dpg.add_text(str(peer.get("state", "Connected")))
                dpg.add_text(str(peer.get("flags", "--")))
                dpg.add_text(self._format_age(peer.get("connected_seconds", 0.0)))

            self._row_ids.append(row_id)
