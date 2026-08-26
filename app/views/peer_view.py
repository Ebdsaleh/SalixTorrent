# app/views/peer_view.py

import dearpygui.dearpygui as dpg

from app.views.help_terms import add_help_tooltip, add_text_tooltip
from app.views.transfer_rate import format_transfer_rate, normalize_transfer_rate_unit


class PeerView:
    """Detailed live peer table for the currently selected torrent."""

    def __init__(self):
        self.summary_text = None
        self.table_id = None
        self._row_ids = []
        self._rate_unit = "Auto"

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=285, border=True):
            self.summary_text = dpg.add_text(
                "Peers: select a torrent to inspect its connections",
                color=(100, 180, 255),
            )
            add_help_tooltip(self.summary_text, "CONNECTED_PEERS")
            flags_help = dpg.add_text(
                "Flags: I = we are interested | i = peer interested | "
                "C = peer chokes us | c = we choke peer",
                color=(150, 150, 150),
            )
            add_help_tooltip(flags_help, "PEER_FLAGS")
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
                address_col = dpg.add_table_column(
                    label="Address",
                    width_stretch=True,
                    init_width_or_weight=0.18,
                )
                client_col = dpg.add_table_column(
                    label="Client",
                    width_stretch=True,
                    init_width_or_weight=0.16,
                )
                source_col = dpg.add_table_column(
                    label="Source",
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                direction_col = dpg.add_table_column(
                    label="Direction",
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                pieces_col = dpg.add_table_column(
                    label="Pieces",
                    width_fixed=True,
                    init_width_or_weight=75,
                )
                down_col = dpg.add_table_column(
                    label="Down",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                up_col = dpg.add_table_column(
                    label="Up",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                state_col = dpg.add_table_column(
                    label="State",
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                flags_col = dpg.add_table_column(
                    label="Flags",
                    width_fixed=True,
                    init_width_or_weight=70,
                )
                age_col = dpg.add_table_column(
                    label="Age",
                    width_fixed=True,
                    init_width_or_weight=70,
                )
                add_help_tooltip(address_col, "PEER_ADDRESS")
                add_help_tooltip(client_col, "PEER_CLIENT")
                add_help_tooltip(source_col, "PEER_SOURCE")
                add_help_tooltip(direction_col, "PEER_DIRECTION")
                add_help_tooltip(pieces_col, "PEER_PROGRESS")
                add_help_tooltip(down_col, "TRANSFER_RATE")
                add_help_tooltip(up_col, "TRANSFER_RATE")
                add_help_tooltip(state_col, "PEER_STATE")
                add_help_tooltip(flags_col, "PEER_FLAGS")
                add_help_tooltip(age_col, "PEER_AGE")

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

    def set_rate_unit(self, unit: object):
        self._rate_unit = normalize_transfer_rate_unit(unit)

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
                address_item = dpg.add_text(str(peer.get("address", "?")))
                client_item = dpg.add_text(str(peer.get("client", "Unknown")))
                add_text_tooltip(
                    address_item,
                    f"Peer address\n\nRemote endpoint for this live connection: {peer.get('address', '?')}\n\nThis is a network endpoint, not a user identity. BitTorrent peers can disconnect and reconnect on different ports.",
                )
                add_text_tooltip(
                    client_item,
                    f"Peer client\n\nThe remote peer identifies itself as: {peer.get('client', 'Unknown')}\n\nClient identification is decoded from self-reported BitTorrent peer/extension metadata and should be treated as informative rather than cryptographically authenticated.",
                )
                source_name = str(peer.get("source", "Unknown"))
                source_item = dpg.add_text(source_name)
                source_term = {
                    "Tracker": "TRACKER",
                    "DHT": "DHT",
                    "PEX": "PEX",
                    "LAN": "LPD",
                }.get(source_name)
                if source_term:
                    add_help_tooltip(source_item, source_term)
                direction_item = dpg.add_text(str(peer.get("direction", "--")))
                progress_item = dpg.add_text(self._format_progress(peer.get("progress")))
                add_help_tooltip(direction_item, "PEER_DIRECTION")
                add_help_tooltip(progress_item, "PEER_PROGRESS")
                down_item = dpg.add_text(
                    format_transfer_rate(
                        peer.get("download_speed_kbps", 0.0),
                        self._rate_unit,
                    )
                )
                up_item = dpg.add_text(
                    format_transfer_rate(
                        peer.get("upload_speed_kbps", 0.0),
                        self._rate_unit,
                    )
                )
                add_help_tooltip(down_item, "TRANSFER_RATE")
                add_help_tooltip(up_item, "TRANSFER_RATE")
                state_item = dpg.add_text(str(peer.get("state", "Connected")))
                flags_item = dpg.add_text(str(peer.get("flags", "--")))
                age_item = dpg.add_text(self._format_age(peer.get("connected_seconds", 0.0)))
                add_help_tooltip(state_item, "PEER_STATE")
                add_help_tooltip(flags_item, "PEER_FLAGS")
                add_help_tooltip(age_item, "PEER_AGE")

            self._row_ids.append(row_id)


