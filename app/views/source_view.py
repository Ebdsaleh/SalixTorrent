# app/views/source_view.py

from __future__ import annotations

import urllib.parse

import dearpygui.dearpygui as dpg

from app.views.help_terms import add_help_tooltip, add_text_tooltip


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

    STATUS_EXPLANATIONS = {
        "Active": (
            "This discovery source is working and has produced usable peer-"
            "discovery information."
        ),
        "No Peers": (
            "The source responded successfully, but its latest result contained "
            "no peer addresses. This is not an error; other discovery sources may "
            "still find peers."
        ),
        "Announcing": (
            "SalixTorrent is currently contacting this source and waiting for its "
            "reply."
        ),
        "Waiting": (
            "This source is available but has not produced a result yet. It may be "
            "queried later as the session continues."
        ),
        "Timeout": (
            "Warning only for this discovery source: it did not answer within the allowed "
            "time. The torrent itself can remain healthy while SalixTorrent continues using "
            "other trackers, DHT, PEX, or Local Peer Discovery."
        ),
        "Error": (
            "The latest attempt to use this source failed. The Detail column and "
            "this tooltip may contain the reason."
        ),
        "Unsupported": (
            "SalixTorrent does not currently support the protocol used by this "
            "source."
        ),
        "Cancelled": "The most recent operation for this source was cancelled.",
        "Disabled": (
            "This discovery method is currently disabled by torrent privacy rules "
            "or by your Preferences."
        ),
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
                "Discovery sources are independent. Waiting is neutral; Timeout is a warning for that "
                "source, not a torrent failure, while other trackers/DHT/PEX/LAN continue.",
                color=(150, 150, 150),
                wrap=1200,
            )
            add_help_tooltip(self.note_text, "DISCOVERY")
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
                    label="Discovery",
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
                    label="Scrape S/L/C",
                    width_fixed=True,
                    init_width_or_weight=125,
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
    def _format_scrape(source: dict) -> str:
        if str(source.get("type") or "").upper() not in {"HTTP", "HTTPS", "UDP"}:
            return "--"
        status = str(source.get("scrape_status") or "Waiting")
        if status != "Active":
            return status
        values = []
        for key in ("scrape_seeders", "scrape_leechers", "scrape_completed"):
            value = source.get(key)
            try:
                values.append(str(max(0, int(value))))
            except (TypeError, ValueError):
                values.append("?")
        return " / ".join(values)

    @classmethod
    def _scrape_tooltip(cls, source: dict) -> str:
        source_type = str(source.get("type") or "").upper()
        if source_type not in {"HTTP", "HTTPS", "UDP"}:
            return "Tracker scrape statistics are available only for tracker sources."
        status = str(source.get("scrape_status") or "Waiting")
        lines = [
            "Tracker Scrape - Seeds / Leechers / Completed",
            "",
            "Scrape asks a tracker for swarm statistics without announcing a peer or changing swarm participation.",
            "",
            f"Status: {status}",
        ]
        if status == "Active":
            lines.extend([
                f"Seeds: {source.get('scrape_seeders', '--')}",
                f"Leechers: {source.get('scrape_leechers', '--')}",
                f"Completed downloads: {source.get('scrape_completed', '--')}",
                f"Last scrape: {cls._format_age(source.get('scrape_last_update_seconds'))}",
                f"Scrape response: {cls._format_response(source.get('scrape_response_ms'))}",
                f"Protocol: {source.get('scrape_protocol') or '--'}",
                f"Batch size: {int(source.get('scrape_batch_size', 0) or 0)} torrent(s)",
            ])
        error = str(source.get("scrape_last_error") or "").strip()
        if error:
            lines.append(f"Detail: {error}")
        endpoint = str(source.get("scrape_endpoint") or "").strip()
        if endpoint:
            lines.append(f"Endpoint: {endpoint}")
        return "\n".join(lines)

    @staticmethod
    def _detail(source: dict) -> str:
        error = str(source.get("last_error") or "").strip()
        if error:
            return error

        explicit = str(source.get("detail") or "").strip()
        if explicit:
            return explicit

        parts = []
        try:
            ipv4_peers = max(0, int(source.get("ipv4_peers", 0) or 0))
            ipv6_peers = max(0, int(source.get("ipv6_peers", 0) or 0))
        except (TypeError, ValueError):
            ipv4_peers = ipv6_peers = 0
        if ipv4_peers or ipv6_peers:
            parts.append(f"IPv4 {ipv4_peers} | IPv6 {ipv6_peers}")
        announce_families = [
            str(value) for value in source.get("announce_families", []) if value
        ]
        if announce_families:
            parts.append(f"announced via {' + '.join(announce_families)}")
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

        scrape_status = str(source.get("scrape_status") or "")
        if scrape_status:
            if scrape_status == "Active":
                parts.append(
                    "scrape "
                    f"{source.get('scrape_seeders', '?')}/"
                    f"{source.get('scrape_leechers', '?')}/"
                    f"{source.get('scrape_completed', '?')} "
                    f"batch {int(source.get('scrape_batch_size', 0) or 0)}"
                )
            elif scrape_status != "Waiting":
                parts.append(f"scrape {scrape_status.lower()}")

        return " | ".join(parts) if parts else "--"

    @staticmethod
    def _type_help_term(source_type: str) -> str:
        return {
            "HTTP": "HTTP_TRACKER",
            "HTTPS": "HTTPS_TRACKER",
            "UDP": "UDP_TRACKER",
            "DHT": "DHT",
            "PEX": "PEX",
            "LAN": "LPD",
        }.get(str(source_type or "").upper(), "DISCOVERY")

    @classmethod
    def _status_tooltip(cls, source: dict) -> str:
        status = str(source.get("status") or "Waiting")
        text = cls.STATUS_EXPLANATIONS.get(
            status,
            "This is the current state reported by this peer-discovery source.",
        )
        detail = str(source.get("last_error") or source.get("detail") or "").strip()
        if detail and detail.lower() not in text.lower():
            return f"{status}\n\n{text}\n\nLatest detail: {detail}"
        return f"{status}\n\n{text}"

    @classmethod
    def _source_tooltip(cls, source: dict) -> str:
        """Build user-facing help for the exact source under the mouse."""
        source_name = str(source.get("source") or "Unknown")
        source_type = str(source.get("type") or "--").upper()
        status = str(source.get("status") or "Waiting")
        peers = max(0, int(source.get("peers", 0) or 0))
        age = cls._format_age(source.get("last_update_seconds"))
        response = cls._format_response(source.get("response_ms"))
        swarm = cls._format_swarm(source)
        detail = cls._detail(source)

        if source_type in {"HTTP", "HTTPS", "UDP"}:
            parsed = urllib.parse.urlparse(source_name)
            host = parsed.hostname or source_name
            protocol_name = {
                "HTTP": "HTTP",
                "HTTPS": "HTTPS",
                "UDP": "UDP",
            }[source_type]
            transport_note = {
                "HTTP": "using a normal HTTP announce request",
                "HTTPS": "using an encrypted HTTPS announce request",
                "UDP": "using the compact UDP tracker protocol",
            }[source_type]
            lines = [
                f"{protocol_name} Tracker - {host}",
                "",
                "This server helps SalixTorrent discover other peers participating "
                "in this torrent. SalixTorrent announces to it " + transport_note + ".",
                "",
                "The torrent's file data does NOT pass through this tracker. Once "
                "peers are discovered, the data is exchanged directly peer-to-peer.",
                "",
                f"Announce status: {status}",
                f"Peers returned by latest announce: {peers}",
                f"Tracker-reported seeds / leechers: {swarm}",
                f"Latest response time: {response}",
                f"Last update: {age}",
                f"Scrape S/L/C: {cls._format_scrape(source)}",
                f"Scrape age: {cls._format_age(source.get('scrape_last_update_seconds'))}",
            ]
            interval = source.get("interval")
            if interval is not None:
                try:
                    lines.append(f"Requested announce interval: {max(0, int(interval))}s")
                except (TypeError, ValueError):
                    pass
            if detail != "--":
                lines.append(f"Latest detail: {detail}")
            lines.extend(["", f"Address: {source_name}"])
            return "\n".join(lines)

        if source_type == "DHT":
            return "\n".join([
                "DHT - Distributed Hash Table",
                "",
                "This is BitTorrent's decentralized peer-discovery network. Instead "
                "of asking one tracker server, SalixTorrent asks DHT nodes for peers "
                "associated with this torrent's info hash.",
                "",
                "DHT is used only for public torrents; private torrents deliberately "
                "disable it.",
                "",
                f"Current status: {status}",
                f"Peers learned through DHT: {peers}",
                f"Last DHT activity: {age}",
                f"Protocol detail: {detail}",
            ])

        if source_type == "PEX":
            return "\n".join([
                "PEX - Peer Exchange",
                "",
                "Connected BitTorrent peers can tell SalixTorrent about other peers "
                "they already know. This grows the peer pool without requiring every "
                "new peer to come from a tracker or DHT lookup.",
                "",
                "PEX is used only for public torrents; private torrents deliberately "
                "disable it.",
                "",
                f"Current status: {status}",
                f"Unique peers learned through PEX: {peers}",
                f"Last PEX activity: {age}",
                f"Protocol detail: {detail}",
            ])

        if source_type == "LAN":
            return "\n".join([
                "LPD - Local Peer Discovery",
                "",
                "SalixTorrent uses local-network multicast to find compatible peers "
                "on the same LAN. This is useful when two computers behind the same "
                "router are participating in the same torrent.",
                "",
                "LPD does not search the wider Internet and is disabled for private "
                "torrents.",
                "",
                f"Current status: {status}",
                f"Local peers discovered: {peers}",
                f"Last LAN activity: {age}",
                f"Protocol detail: {detail}",
            ])

        return "\n".join([
            f"Peer Discovery Source - {source_name}",
            "",
            "This entry represents one way SalixTorrent can learn about peers for "
            "the selected torrent.",
            "",
            f"Type: {source_type}",
            f"Current status: {status}",
            f"Peers reported: {peers}",
            f"Last update: {age}",
            f"Detail: {detail}",
        ])

    @staticmethod
    def _peers_tooltip(source: dict) -> str:
        source_type = str(source.get("type") or "--").upper()
        peers = max(0, int(source.get("peers", 0) or 0))
        wording = {
            "HTTP": "returned by this tracker in its latest result",
            "HTTPS": "returned by this tracker in its latest result",
            "UDP": "returned by this tracker in its latest result",
            "DHT": "learned through DHT during this session",
            "PEX": "learned through Peer Exchange during this session",
            "LAN": "learned through Local Peer Discovery during this session",
        }.get(source_type, "reported by this discovery source")
        return (
            f"Peers from this source: {peers}\n\n"
            f"These are peer addresses {wording}. This is not necessarily the same "
            "as the number currently connected: discovered peers can be duplicated, "
            "offline, unreachable, rejected, or already connected."
        )

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
        pending_count = int(sources_view.get("pending_count", 0) or 0)
        warning_count = int(sources_view.get("warning_count", 0) or 0)
        error_count = int(sources_view.get("error_count", 0) or 0)
        tracker_peers = int(sources_view.get("tracker_peers_last_seen", 0) or 0)
        dht_peers = int(sources_view.get("dht_peers_seen", 0) or 0)
        pex_peers = int(sources_view.get("pex_peers_seen", 0) or 0)
        lan_peers = int(sources_view.get("lan_peers_seen", 0) or 0)
        scrape_active = int(sources_view.get("scrape_active_count", 0) or 0)
        scrape_pending = int(sources_view.get("scrape_pending_count", 0) or 0)
        scrape_warnings = int(sources_view.get("scrape_warning_count", 0) or 0)
        scrape_errors = int(sources_view.get("scrape_error_count", 0) or 0)

        if sources:
            summary = (
                f"Sources: {tracker_count} tracker(s) + DHT + PEX + LAN | "
                f"Responding: {active_count} | Pending: {pending_count} | "
                f"Warnings: {warning_count} | Errors: {error_count} | "
                f"Scrape A/P/W/E: {scrape_active}/{scrape_pending}/{scrape_warnings}/{scrape_errors} | "
                f"Peers seen - Tracker {tracker_peers} | DHT {dht_peers} | "
                f"PEX {pex_peers} | LAN {lan_peers}"
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
                source_name = str(source.get("source", "Unknown"))
                source_type = str(source.get("type", "--"))

                # Every cell gets help for what is actually under the mouse. In
                # particular, the Source column is dynamic: a tracker URL explains
                # that exact tracker and its current state rather than merely showing
                # a generic definition for the neighbouring Type column.
                source_name_item = dpg.add_text(source_name)
                add_text_tooltip(
                    source_name_item,
                    self._source_tooltip(source),
                    wrap=520,
                )

                source_type_item = dpg.add_text(source_type)
                add_help_tooltip(
                    source_type_item,
                    self._type_help_term(source_type),
                )

                status_item = dpg.add_text(status, color=color)
                add_text_tooltip(status_item, self._status_tooltip(source), wrap=460)

                peers_item = dpg.add_text(str(peers))
                add_text_tooltip(peers_item, self._peers_tooltip(source), wrap=460)

                swarm_item = dpg.add_text(self._format_swarm(source))
                add_help_tooltip(swarm_item, "SWARM_SL")

                scrape_item = dpg.add_text(self._format_scrape(source))
                add_text_tooltip(scrape_item, self._scrape_tooltip(source), wrap=520)

                response_item = dpg.add_text(
                    self._format_response(source.get("response_ms"))
                )
                add_help_tooltip(response_item, "SOURCE_RESPONSE")

                age_item = dpg.add_text(
                    self._format_age(source.get("last_update_seconds"))
                )
                add_help_tooltip(age_item, "SOURCE_LAST_UPDATE")

                detail_item = dpg.add_text(self._detail(source))
                add_help_tooltip(detail_item, "SOURCE_DETAIL")

            self._row_ids.append(row_id)
