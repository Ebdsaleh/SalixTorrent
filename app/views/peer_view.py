# app/views/peer_view.py

import dearpygui.dearpygui as dpg

from app.localization import tr, tr_value

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
        with dpg.child_window(parent=parent_tag, height=-1, border=True):
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

            with dpg.table(
                header_row=True,
                resizable=True,
                policy=dpg.mvTable_SizingStretchProp,
                borders_outerH=True,
                borders_innerH=True,
                borders_innerV=True,
                scrollY=True,
                height=-1,
            ) as self.table_id:
                address_col = dpg.add_table_column(
                    label=tr('view.peer_view.address', "Address"),
                    width_stretch=True,
                    init_width_or_weight=0.18,
                )
                client_col = dpg.add_table_column(
                    label=tr('view.peer_view.client', "Client"),
                    width_stretch=True,
                    init_width_or_weight=0.16,
                )
                source_col = dpg.add_table_column(
                    label=tr('view.peer_view.source', "Source"),
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                direction_col = dpg.add_table_column(
                    label=tr('view.peer_view.direction', "Direction"),
                    width_fixed=True,
                    init_width_or_weight=85,
                )
                transport_col = dpg.add_table_column(
                    label=tr('view.peer_view.transport', "Transport"),
                    width_fixed=True,
                    init_width_or_weight=105,
                )
                pieces_col = dpg.add_table_column(
                    label=tr('view.peer_view.pieces', "Pieces"),
                    width_fixed=True,
                    init_width_or_weight=75,
                )
                down_col = dpg.add_table_column(
                    label=tr('view.peer_view.down', "Down"),
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                up_col = dpg.add_table_column(
                    label=tr('view.peer_view.up', "Up"),
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                state_col = dpg.add_table_column(
                    label=tr('view.peer_view.state', "State"),
                    width_fixed=True,
                    init_width_or_weight=95,
                )
                flags_col = dpg.add_table_column(
                    label=tr('view.peer_view.flags', "Flags"),
                    width_fixed=True,
                    init_width_or_weight=70,
                )
                age_col = dpg.add_table_column(
                    label=tr('view.peer_view.age', "Age"),
                    width_fixed=True,
                    init_width_or_weight=70,
                )
                add_help_tooltip(address_col, "PEER_ADDRESS")
                add_help_tooltip(client_col, "PEER_CLIENT")
                add_help_tooltip(source_col, "PEER_SOURCE")
                add_help_tooltip(direction_col, "PEER_DIRECTION")
                add_help_tooltip(transport_col, "TRANSPORT_SECURITY")
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
                tr('view.peer_view.peers_select_a_torrent_to_inspect_its', "Peers: select a torrent to inspect its connections"),
            )

    def render(self, snapshot: dict):
        if not self.table_id or not dpg.does_item_exist(self.table_id):
            return

        peers = list(snapshot.get("peers") or [])
        connected = int(snapshot.get("connected_peers", len(peers)) or 0)
        local_found = int(snapshot.get("local_peers_discovered", 0) or 0)
        state_label = snapshot.get("state_label", snapshot.get("state", "Idle"))
        encrypted = int(snapshot.get("encrypted_peer_count", 0) or 0)
        plaintext = int(snapshot.get("plaintext_peer_count", 0) or 0)
        policy = str(snapshot.get("encryption_policy") or "Prefer Encryption")
        ipv4_count = int(snapshot.get("ipv4_peer_count", 0) or 0)
        ipv6_count = int(snapshot.get("ipv6_peer_count", 0) or 0)

        if connected:
            summary = (
                tr('view.peer_view.peers_value_connected_ipv4_value_ipv6_value_mse_rc4', 'Peers: {connected} connected | IPv4: {ipv4_count} | IPv6: {ipv6_count} | MSE/RC4: {encrypted} | Plaintext: {plaintext} | Policy: {policy} | Torrent state: {state_label}', connected=connected, ipv4_count=ipv4_count, ipv6_count=ipv6_count, encrypted=encrypted, plaintext=plaintext, policy=policy, state_label=state_label)
            )
        else:
            summary = (
                tr('view.peer_view.peers_0_connected_ipv4_0_ipv6_0_mse_rc4', 'Peers: 0 connected | IPv4: 0 | IPv6: 0 | MSE/RC4: 0 | Plaintext: 0 | Policy: {policy} | Torrent state: {state_label} - waiting for peer connections', policy=policy, state_label=state_label)
            )

        dpg.set_value(self.summary_text, summary)
        self._clear_rows()

        for peer in peers:
            with dpg.table_row(parent=self.table_id) as row_id:
                address_item = dpg.add_text(str(peer.get("address", "?")))
                client_item = dpg.add_text(str(peer.get("client", "Unknown")))
                add_text_tooltip(
                    address_item,
                    tr('view.peer_view.peer_address_remote_endpoint_for_this_live_connection', 'Peer address\n\nRemote endpoint for this live connection: {get}\n\nThis is a network endpoint, not a user identity. BitTorrent peers can disconnect and reconnect on different ports.', get=peer.get('address', '?')),
                )
                add_text_tooltip(
                    client_item,
                    tr('view.peer_view.peer_client_the_remote_peer_identifies_itself_as', 'Peer client\n\nThe remote peer identifies itself as: {get}\n\nClient identification is decoded from self-reported BitTorrent peer/extension metadata and should be treated as informative rather than cryptographically authenticated.', get=peer.get('client', 'Unknown')),
                )
                source_name = str(peer.get("source", "Unknown"))
                source_item = dpg.add_text(tr_value(source_name))
                source_term = {
                    "Tracker": "TRACKER",
                    "DHT": "DHT",
                    "PEX": "PEX",
                    "LAN": "LPD",
                }.get(source_name)
                if source_term:
                    add_help_tooltip(source_item, source_term)
                direction_item = dpg.add_text(tr_value(peer.get("direction", "--")))
                transport_item = dpg.add_text(tr_value(peer.get("transport_security", "Plaintext")))
                progress_item = dpg.add_text(self._format_progress(peer.get("progress")))
                add_help_tooltip(direction_item, "PEER_DIRECTION")
                add_help_tooltip(transport_item, "TRANSPORT_SECURITY")
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
