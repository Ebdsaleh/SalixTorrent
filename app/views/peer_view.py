# app/views/peer_view.py

import dearpygui.dearpygui as dpg

from app.engine.table_hosts import DearPyGuiTableHost
from app.framework.live_data import LiveTable, TableCell, TableColumnSpec, TableFrame, TableRow
from app.localization import tr, tr_value
from app.views.help_terms import add_help_tooltip, help_text
from app.views.transfer_rate import format_transfer_rate, normalize_transfer_rate_unit


class PeerView:
    """Detailed live peer table for the currently selected torrent."""

    def __init__(self):
        self.summary_text = None
        self.table_id = None
        self.live_table = None
        self._rate_unit = "Auto"

    def build_view(self, parent_tag):
        with dpg.child_window(parent=parent_tag, height=-1, border=True) as content:
            self.summary_text = dpg.add_text(
                tr('view.peer_view.peers_select_a_torrent_to_inspect_its', "Peers: select a torrent to inspect its connections"),
                color=(100, 180, 255),
            )
            add_help_tooltip(self.summary_text, "CONNECTED_PEERS")
            flags_help = dpg.add_text(
                tr('view.peer_view.flags_i_we_are_interested_i_peer', "Flags: I = we are interested | i = peer interested | "
                "C = peer chokes us | c = we choke peer"),
                color=(150, 150, 150),
            )
            add_help_tooltip(flags_help, "PEER_FLAGS")
            dpg.add_separator()

            columns = (
                TableColumnSpec("address", tr('view.peer_view.address', "Address"), "stretch", 0.18),
                TableColumnSpec("client", tr('view.peer_view.client', "Client"), "stretch", 0.16),
                TableColumnSpec("source", tr('view.peer_view.source', "Source"), "fixed", 85),
                TableColumnSpec("direction", tr('view.peer_view.direction', "Direction"), "fixed", 85),
                TableColumnSpec("transport", tr('view.peer_view.transport', "Transport"), "fixed", 105),
                TableColumnSpec("pieces", tr('view.peer_view.pieces', "Pieces"), "fixed", 75),
                TableColumnSpec("down", tr('view.peer_view.down', "Down"), "fixed", 95),
                TableColumnSpec("up", tr('view.peer_view.up', "Up"), "fixed", 95),
                TableColumnSpec("state", tr('view.peer_view.state', "State"), "fixed", 95),
                TableColumnSpec("flags", tr('view.peer_view.flags', "Flags"), "fixed", 70),
                TableColumnSpec("age", tr('view.peer_view.age', "Age"), "fixed", 70),
            )
            self.live_table = LiveTable(DearPyGuiTableHost(), columns)
            binding = self.live_table.build(parent=content, height=-1)
            self.table_id = binding.table
            for key, term in (
                ("address", "PEER_ADDRESS"),
                ("client", "PEER_CLIENT"),
                ("source", "PEER_SOURCE"),
                ("direction", "PEER_DIRECTION"),
                ("transport", "TRANSPORT_SECURITY"),
                ("pieces", "PEER_PROGRESS"),
                ("down", "TRANSFER_RATE"),
                ("up", "TRANSFER_RATE"),
                ("state", "PEER_STATE"),
                ("flags", "PEER_FLAGS"),
                ("age", "PEER_AGE"),
            ):
                add_help_tooltip(binding.column_item(key), term)

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

    def reset(self):
        if self.live_table is not None:
            self.live_table.clear()
        if self.summary_text and dpg.does_item_exist(self.summary_text):
            dpg.set_value(
                self.summary_text,
                tr('view.peer_view.peers_select_a_torrent_to_inspect_its', "Peers: select a torrent to inspect its connections"),
            )

    def _peer_row(self, peer: dict, index: int) -> TableRow:
        source_name = str(peer.get("source", "Unknown"))
        source_term = {
            "Tracker": "TRACKER",
            "DHT": "DHT",
            "PEX": "PEX",
            "LAN": "LPD",
        }.get(source_name, "PEER_SOURCE")
        key = str(peer.get("connection_id") or f"{peer.get('address', '?')}:{index}")
        return TableRow(
            key,
            (
                TableCell(
                    peer.get("address", "?"),
                    tooltip=tr('view.peer_view.peer_address_remote_endpoint_for_this_live_connection', 'Peer address\n\nRemote endpoint for this live connection: {get}\n\nThis is a network endpoint, not a user identity. BitTorrent peers can disconnect and reconnect on different ports.', get=peer.get('address', '?')),
                ),
                TableCell(
                    peer.get("client", "Unknown"),
                    tooltip=tr('view.peer_view.peer_client_the_remote_peer_identifies_itself_as', 'Peer client\n\nThe remote peer identifies itself as: {get}\n\nClient identification is decoded from self-reported BitTorrent peer/extension metadata and should be treated as informative rather than cryptographically authenticated.', get=peer.get('client', 'Unknown')),
                ),
                TableCell(tr_value(source_name), tooltip=help_text(source_term)),
                TableCell(tr_value(peer.get("direction", "--")), tooltip=help_text("PEER_DIRECTION")),
                TableCell(tr_value(peer.get("transport_security", "Plaintext")), tooltip=help_text("TRANSPORT_SECURITY")),
                TableCell(self._format_progress(peer.get("progress")), tooltip=help_text("PEER_PROGRESS")),
                TableCell(format_transfer_rate(peer.get("download_speed_kbps", 0.0), self._rate_unit), tooltip=help_text("TRANSFER_RATE")),
                TableCell(format_transfer_rate(peer.get("upload_speed_kbps", 0.0), self._rate_unit), tooltip=help_text("TRANSFER_RATE")),
                TableCell(str(peer.get("state", "Connected")), tooltip=help_text("PEER_STATE")),
                TableCell(str(peer.get("flags", "--")), tooltip=help_text("PEER_FLAGS")),
                TableCell(self._format_age(peer.get("connected_seconds", 0.0)), tooltip=help_text("PEER_AGE")),
            ),
        )

    def render(self, snapshot: dict):
        if self.live_table is None or not self.live_table.exists():
            return

        peers = list(snapshot.get("peers") or [])
        connected = int(snapshot.get("connected_peers", len(peers)) or 0)
        state_label = snapshot.get("state_label", snapshot.get("state", "Idle"))
        encrypted = int(snapshot.get("encrypted_peer_count", 0) or 0)
        plaintext = int(snapshot.get("plaintext_peer_count", 0) or 0)
        policy = str(snapshot.get("encryption_policy") or "Prefer Encryption")
        ipv4_count = int(snapshot.get("ipv4_peer_count", 0) or 0)
        ipv6_count = int(snapshot.get("ipv6_peer_count", 0) or 0)

        if connected:
            summary = tr('view.peer_view.peers_value_connected_ipv4_value_ipv6_value_mse_rc4', 'Peers: {connected} connected | IPv4: {ipv4_count} | IPv6: {ipv6_count} | MSE/RC4: {encrypted} | Plaintext: {plaintext} | Policy: {policy} | Torrent state: {state_label}', connected=connected, ipv4_count=ipv4_count, ipv6_count=ipv6_count, encrypted=encrypted, plaintext=plaintext, policy=policy, state_label=state_label)
        else:
            summary = tr('view.peer_view.peers_0_connected_ipv4_0_ipv6_0_mse_rc4', 'Peers: 0 connected | IPv4: 0 | IPv6: 0 | MSE/RC4: 0 | Plaintext: 0 | Policy: {policy} | Torrent state: {state_label} - waiting for peer connections', policy=policy, state_label=state_label)

        dpg.set_value(self.summary_text, summary)
        self.live_table.render(TableFrame(self._peer_row(peer, index) for index, peer in enumerate(peers)))
