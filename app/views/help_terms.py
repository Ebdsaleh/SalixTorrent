# app/views/help_terms.py

from __future__ import annotations

import dearpygui.dearpygui as dpg


# One glossary powers hover help and can later power the planned Help Topics /
# encyclopedia window. Keeping the text centralized prevents tooltips and
# long-form help from drifting into contradictory wording.
HELP_TERMS = {
    "DHT": (
        "DHT — Distributed Hash Table",
        "A decentralized BitTorrent peer-discovery network. It can find peers "
        "for public torrents without requiring a central tracker. Private "
        "torrents do not use DHT.",
    ),
    "PEX": (
        "PEX — Peer Exchange",
        "A BitTorrent extension where connected peers tell one another about "
        "other peers they know. SalixTorrent uses BEP-10/11 PEX for public "
        "torrents.",
    ),
    "LPD": (
        "LPD — Local Peer Discovery",
        "Local Peer Discovery finds compatible peers on the same local network "
        "using multicast, so nearby computers can discover one another without "
        "depending on an Internet tracker.",
    ),
    "LAN": (
        "LAN — Local Area Network",
        "Your local network, such as computers connected to the same home or "
        "office router. SalixTorrent can use LAN discovery for nearby peers.",
    ),
    "UPNP": (
        "UPnP — Universal Plug and Play",
        "A router protocol SalixTorrent can use to request an automatic incoming "
        "port mapping. If your router does not expose UPnP, torrents can still "
        "download through outbound peer connections.",
    ),
    "NATPMP": (
        "NAT-PMP — NAT Port Mapping Protocol",
        "An automatic router port-mapping protocol used as a fallback when UPnP "
        "is unavailable. A timeout usually means the router does not support or "
        "permit NAT-PMP.",
    ),
    "BEP": (
        "BEP — BitTorrent Enhancement Proposal",
        "A numbered specification describing a BitTorrent protocol or extension. "
        "For example, BEP-5 defines DHT and BEP-14 defines Local Peer Discovery.",
    ),
    "TCP": (
        "TCP — Transmission Control Protocol",
        "The reliable connection-oriented transport normally used for BitTorrent "
        "peer data connections.",
    ),
    "UDP": (
        "UDP — User Datagram Protocol",
        "A lightweight datagram transport used by protocols such as DHT, UDP "
        "trackers and some router-discovery mechanisms.",
    ),
    "HTTP_TRACKER": (
        "HTTP Tracker",
        "A BitTorrent tracker contacted with an HTTP announce request. The tracker "
        "returns peer addresses and optional swarm statistics. Torrent payload "
        "data does not pass through the tracker; peers exchange the data directly.",
    ),
    "HTTPS_TRACKER": (
        "HTTPS Tracker",
        "A BitTorrent tracker contacted with an encrypted HTTPS announce request. "
        "It returns peer addresses and optional swarm statistics. Torrent payload "
        "data is still transferred directly between peers, not through the tracker.",
    ),
    "UDP_TRACKER": (
        "UDP Tracker",
        "A BitTorrent tracker using the compact UDP tracker protocol. It usually "
        "has less protocol overhead than HTTP. The tracker only helps peers find "
        "one another; torrent payload data is transferred directly between peers.",
    ),
    "ETA": (
        "ETA — Estimated Time of Arrival",
        "An estimate of how long the currently wanted data will take to finish at "
        "the recent download rate. It naturally changes as transfer speed changes.",
    ),
    "SHARE_RATIO": (
        "Share Ratio",
        "Uploaded data divided by downloaded data. A ratio of 1.0 means you have "
        "uploaded roughly as much data as you downloaded.",
    ),
    "AVAILABILITY": (
        "Swarm Availability",
        "An estimate of how many complete copies of the torrent are represented "
        "by the pieces currently advertised by connected peers. Below 1.0 can "
        "mean the swarm presently lacks enough pieces to complete the torrent.",
    ),
    "SEEDS_LEECHERS": (
        "Seeds / Leechers",
        "A seed has the complete torrent and uploads it. A leecher (or downloading "
        "peer) is still obtaining some of the torrent. Tracker counts are an "
        "estimate and may differ from currently connected peers.",
    ),
    "INFO_HASH": (
        "Info Hash",
        "The SHA-1 identifier of a BitTorrent v1 torrent's exact bencoded info "
        "dictionary. Peers use it to identify the swarm, and magnet links contain it.",
    ),
    "PIECE": (
        "Torrent Pieces",
        "A torrent payload is divided into fixed-size pieces. Each piece has a "
        "cryptographic hash and is only treated as trusted after verification.",
    ),
    "TRACKER": (
        "Tracker",
        "A server that introduces peers participating in the same torrent. The "
        "tracker coordinates discovery; the actual file data is transferred "
        "directly between peers.",
    ),
    "SOURCE_PEERS": (
        "Peers Reported by This Source",
        "The number shown here belongs to this discovery source, not necessarily "
        "the number of peers currently connected to SalixTorrent. Different "
        "sources may discover the same peer, and some discovered peers may be "
        "offline, unreachable, duplicated, or already connected.",
    ),
    "SWARM_SL": (
        "Swarm S/L — Seeds / Leechers",
        "Tracker-reported swarm counts. S is the number of seeds and L is the "
        "number of leechers reported by that tracker. '--' means this discovery "
        "source does not provide those counts.",
    ),
    "SOURCE_RESPONSE": (
        "Discovery Response Time",
        "How long the latest tracker request took to complete. A lower value is a "
        "faster response, but response time does not measure peer download speed. "
        "'--' means the source does not use a comparable request/response timing.",
    ),
    "SOURCE_LAST_UPDATE": (
        "Last Discovery Update",
        "How long ago SalixTorrent last received or recorded activity from this "
        "discovery source. 'Never' means there has not yet been a result to report.",
    ),
    "SOURCE_DETAIL": (
        "Discovery Detail",
        "Protocol-specific diagnostic information for this source, such as tracker "
        "announce intervals, DHT node activity, PEX message counts, or the Local "
        "Peer Discovery multicast endpoint.",
    ),
    "LISTEN_PORT": (
        "BitTorrent Listen Port",
        "The TCP port on which SalixTorrent accepts incoming peer connections. "
        "Automatic or manual router port mapping can make this reachable from "
        "outside your local network.",
    ),
    "PORT_MAPPING": (
        "Incoming Port Mapping",
        "A router rule forwarding an Internet-facing port to SalixTorrent on this "
        "computer. Being unmapped is not fatal, but it can reduce the number of "
        "peers able to initiate connections to you.",
    ),
    "PRIVATE_TORRENT": (
        "Private Torrent",
        "A torrent marked private restricts peer discovery to its configured "
        "trackers. SalixTorrent disables DHT, PEX and Local Peer Discovery for it.",
    ),
    "TRANSFER_RATE": (
        "Transfer Rate Units",
        "Controls how live upload/download speeds are displayed. KB/s and MB/s "
        "show bytes per second; kbps and Mbps show bits per second. This changes "
        "presentation only and does not change bandwidth limits or network speed.",
    ),
    "DISCOVERY": (
        "Peer Discovery",
        "SalixTorrent can learn about peers from trackers, DHT (Distributed Hash "
        "Table), PEX (Peer Exchange), and LPD/LAN (Local Peer Discovery). Private "
        "torrents intentionally restrict these discovery methods.",
    ),
    "PEER_FLAGS": (
        "Peer Protocol Flags",
        "I = SalixTorrent is interested in data from the peer; i = the peer is "
        "interested in our data; C = the peer is choking us; c = we are choking "
        "the peer. Choking is BitTorrent flow control, not an error condition.",
    ),
}


def help_text(term: str) -> str:
    entry = HELP_TERMS.get(str(term or "").upper())
    if not entry:
        return ""
    title, body = entry
    return f"{title}\n\n{body}"


def add_text_tooltip(item, text: str, wrap: int = 430):
    """Attach arbitrary explanatory text to a Dear PyGui item."""
    if not item or not str(text or "").strip():
        return None
    try:
        with dpg.tooltip(parent=item):
            return dpg.add_text(str(text), wrap=wrap)
    except Exception:
        # Hover help must never be able to prevent a view from building.
        return None


def add_help_tooltip(item, term: str, wrap: int = 430):
    """Attach a consistent glossary tooltip to an existing DPG item."""
    return add_text_tooltip(item, help_text(term), wrap=wrap)
