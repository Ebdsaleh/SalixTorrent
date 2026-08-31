# app/views/help_topics_view.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import dearpygui.dearpygui as dpg

from app.engine.responsive_layout import ResponsiveLayout, clamp, split_widths
from app.views.help_terms import HELP_TERMS, add_text_tooltip


@dataclass(frozen=True)
class HelpTopic:
    key: str
    title: str
    summary: str
    sections: Tuple[Tuple[str, str], ...]
    related_terms: Tuple[str, ...] = ()


HELP_TOPICS: Tuple[HelpTopic, ...] = (
    HelpTopic(
        key="basics",
        title="BitTorrent Basics",
        summary=(
            "A practical introduction to torrents, swarms, peers, pieces, trackers, "
            "and the difference between the .torrent metadata and the payload data."
        ),
        sections=(
            (
                "What BitTorrent does",
                "BitTorrent distributes a payload by allowing many computers to exchange "
                "different verified pieces of the same data. A torrent does not normally "
                "come from one central download server. Instead, SalixTorrent joins a swarm "
                "of peers that can both receive and provide pieces.",
            ),
            (
                "The .torrent file",
                "A .torrent file is metadata. It describes the payload name, file tree, piece "
                "size, piece hashes, trackers and other properties. Opening a .torrent does "
                "not mean the payload is already present; SalixTorrent still has to discover "
                "peers and obtain the wanted pieces unless the data already exists locally.",
            ),
            (
                "The swarm",
                "Every participant using the same info hash belongs to the same logical swarm. "
                "Seeds have the complete payload. Leechers are still obtaining some of it. "
                "A client may download from several peers and upload verified pieces to other "
                "peers at the same time.",
            ),
            (
                "Why pieces are verified",
                "The payload is divided into pieces. Each piece has a cryptographic SHA-1 hash "
                "in a BitTorrent v1 torrent. SalixTorrent trusts a piece only after its bytes "
                "match the expected hash. This is why a transfer can safely combine data from "
                "many unrelated peers.",
            ),
        ),
        related_terms=(
            "TRACKER",
            "SEEDS_LEECHERS",
            "CONNECTED_PEERS",
            "PIECE",
            "INFO_HASH",
            "SWARM_HEALTH",
        ),
    ),
    HelpTopic(
        key="torrents_magnets",
        title="Torrents & Magnet Links",
        summary=(
            "How .torrent files and magnet links identify the same swarm, and how SalixTorrent "
            "turns a magnet into normal torrent metadata."
        ),
        sections=(
            (
                ".torrent files",
                "A .torrent contains the metainfo needed to understand the payload immediately. "
                "It can include tracker URLs, file names, piece length, piece hashes, comments, "
                "creation information and the private-torrent flag.",
            ),
            (
                "Magnet links",
                "A magnet link can begin with only the torrent's info hash and optional display "
                "name or trackers. SalixTorrent discovers compatible peers and uses BEP-9 metadata "
                "exchange to retrieve the missing info dictionary. The received metadata is not "
                "accepted until its SHA-1 hash matches the magnet's btih value.",
            ),
            (
                "After metadata is resolved",
                "Once a magnet has been resolved, SalixTorrent caches a normal .torrent-style "
                "metainfo file in its application data and creates an ordinary persistent torrent "
                "session. From that point onward, checking, downloading, file priorities, fast "
                "resume and seeding use the same engine as a torrent opened from disk.",
            ),
            (
                "Info hash identity",
                "For BitTorrent v1, the info hash is the SHA-1 digest of the exact bencoded info "
                "dictionary. Two peers must agree on this value to participate in the same swarm.",
            ),
        ),
        related_terms=("MAGNET_LINK", "BEP9", "INFO_HASH", "TORRENT_PATH", "OPEN_MAGNET"),
    ),
    HelpTopic(
        key="transfers",
        title="Downloads & Uploads",
        summary=(
            "How SalixTorrent downloads and uploads simultaneously, measures transfer rates, "
            "and applies per-torrent and global bandwidth limits."
        ),
        sections=(
            (
                "Downloading and uploading are simultaneous",
                "A BitTorrent peer connection is bidirectional. While SalixTorrent is receiving "
                "missing pieces from a peer, that same connection can also carry requests for "
                "pieces SalixTorrent has already verified. This is why mature torrent clients "
                "normally show upload activity before a download reaches 100%.",
            ),
            (
                "Verified data only",
                "SalixTorrent serves only pieces that have completed SHA-1 verification. Partially "
                "received or hash-failed data is never advertised as trustworthy payload.",
            ),
            (
                "Transfer rates",
                "The Down and Up values are current measured payload rates. Display units can be "
                "Automatic, KB/s, MB/s, kbps or Mbps. Changing the display unit changes only how "
                "the number is presented; it does not alter the limiter or network traffic.",
            ),
            (
                "Upload proof and idle seeds",
                "A seed does not transmit continuously merely because it is in Seeding state. "
                "Uploaded This Session, Upload Requests and Last Upload provide direct evidence of "
                "piece-serving activity even when the instantaneous upload rate has returned to zero.",
            ),
            (
                "Bandwidth limits",
                "Per-torrent limits constrain one transfer. Global limits are shared by all active "
                "torrents together. A value of 0 means unlimited. The Speed view visualizes recent "
                "rates and any configured limit lines.",
            ),
        ),
        related_terms=(
            "TRANSFER_RATE",
            "DOWNLOADED",
            "UPLOADED",
            "UPLOADED_SESSION",
            "UPLOAD_REQUESTS",
            "LAST_UPLOAD",
            "TRANSFER_LIMITS",
            "GLOBAL_BANDWIDTH",
            "SHARE_RATIO",
            "SPEED_HISTORY",
        ),
    ),
    HelpTopic(
        key="peers_swarms",
        title="Peers & Swarms",
        summary=(
            "What peers, seeds, leechers, choking, interest, client identifiers and swarm "
            "availability mean in the live Peers view."
        ),
        sections=(
            (
                "Peers, seeds and leechers",
                "A peer is another BitTorrent participant. A seed has every piece. A leecher still "
                "needs at least part of the payload. Tracker seed/leecher counts describe the wider "
                "tracker-reported swarm and can differ from the peers SalixTorrent is connected to.",
            ),
            (
                "Peer direction",
                "Outgoing means SalixTorrent initiated the TCP connection; Incoming means the remote "
                "peer connected to SalixTorrent. Direction does not make the connection one-way. "
                "Both sides can upload and download over either connection direction.",
            ),
            (
                "Choking and interest",
                "BitTorrent peers signal whether they are interested in data and whether the other "
                "side is currently allowed to request it. The Peers view exposes these protocol "
                "states through its flags so advanced users can see why a connection may be idle.",
            ),
            (
                "Client identity",
                "Many clients encode a recognizable client/version signature in the peer ID or "
                "extension handshake. SalixTorrent decodes known formats conservatively. These "
                "identifiers are self-reported and are useful telemetry, not cryptographic proof.",
            ),
        ),
        related_terms=(
            "PEER_ADDRESS",
            "PEER_CLIENT",
            "PEER_SOURCE",
            "PEER_DIRECTION",
            "PEER_FLAGS",
            "AVAILABILITY",
            "SEEDS_LEECHERS",
        ),
    ),
    HelpTopic(
        key="pieces_verification",
        title="Pieces & Verification",
        summary=(
            "How torrent payloads are divided into pieces and blocks, how hash checking works, "
            "and how to read SalixTorrent's Pieces view."
        ),
        sections=(
            (
                "Pieces and blocks",
                "The torrent metadata defines fixed-size pieces, except usually the final piece. "
                "Network requests divide those pieces into smaller blocks. Receiving every block "
                "completes the bytes for a piece, but verification is still required before that "
                "piece is considered trusted.",
            ),
            (
                "SHA-1 verification",
                "For BitTorrent v1, SalixTorrent calculates SHA-1 over the completed piece and "
                "compares it with the hash stored in the torrent metadata. A mismatch discards the "
                "untrusted piece so it can be downloaded again from the swarm.",
            ),
            (
                "Piece map states",
                "Verified means trusted and complete. Downloading means blocks are arriving. "
                "Requested means work has been assigned but little or no data has arrived yet. "
                "Missing means it is wanted and not complete. No known source means none of the "
                "currently known peer bitfields advertise that needed piece.",
            ),
            (
                "Rarest-first scheduling",
                "SalixTorrent maintains piece availability incrementally from BITFIELD, HAVE, "
                "and peer-disconnect events. High-priority files are considered before Normal, "
                "then Low. Within the same priority level, the least-available piece this peer "
                "can provide is preferred. Equal-rarity pieces are chosen randomly so clients "
                "do not all converge on the same deterministic piece order.",
            ),
            (
                "Bounded request pipelines",
                "An unchoked peer can have several 16 KiB block requests outstanding at once, "
                "which avoids wasting round-trip time between blocks. SalixTorrent adapts the "
                "pipeline depth from measured peer throughput but clamps it to a strict per-peer "
                "minimum/maximum. Request ownership is indexed by peer, so choke/disconnect and "
                "timeout cleanup touches only that peer's small pipeline rather than scanning "
                "every piece in the torrent.",
            ),
            (
                "Timeout and reassignment",
                "The timeout clock begins only after a REQUEST frame is actually sent, not while "
                "the request is waiting behind a bandwidth limiter. A stalled request is released "
                "for immediate reassignment; if the old peer is still connected SalixTorrent also "
                "sends CANCEL so a late response does not waste bandwidth.",
            ),
            (
                "Endgame completion",
                "When 32 or fewer wanted blocks remain, SalixTorrent enters Endgame Mode. It still "
                "assigns every unrequested block first. Only when the remaining tail is already "
                "outstanding can an old lingering block be requested from another peer, with at "
                "most three owners per block. The first valid PIECE is accepted and targeted CANCEL "
                "messages retire the other duplicate requests. Received CANCEL messages are also "
                "honoured for uploads that have not yet been sent.",
            ),
            (
                "Bounded asynchronous disk writes",
                "After a piece passes SHA-1 verification, SalixTorrent reserves capacity in a "
                "64 MiB byte-bounded write-behind buffer and one sleeping disk worker persists it "
                "outside the asyncio event loop. If storage falls behind, only the coroutine that "
                "needs more buffer space waits; networking and the UI continue running. Completion "
                "is announced only after queued verified pieces have reached storage.",
            ),
            (
                "Recent-piece cache and seeding",
                "Recently persisted pieces are retained in a bounded 32 MiB LRU cache. Upload "
                "requests can therefore reuse hot data without a read-after-write disk operation. "
                "Pieces still waiting in the write buffer are pinned separately and are immediately "
                "uploadable from memory. Both structures are bounded and are discarded when the "
                "session disk pipeline shuts down.",
            ),
            (
                "Disk telemetry and failure behaviour",
                "The Pieces view and Diagnostics expose pending bytes/writes, write latency, cache "
                "hits/misses and backpressure without scanning the payload. A filesystem write "
                "failure is fail-closed: buffered reservations are released, unpersisted pieces are "
                "not written into fast-resume metadata, and the torrent enters an Error state rather "
                "than pretending data was safely stored.",
            ),
            (
                "Force Recheck",
                "Force Recheck invalidates fast-resume assumptions and hashes the existing payload "
                "again without deleting it. This is useful after files were changed externally or "
                "when you want to verify the current disk contents against the torrent metadata.",
            ),
        ),
        related_terms=("PIECE", "BLOCK", "PIECE_STATE", "PIECE_AVAILABILITY", "RAREST_FIRST", "RANDOM_TIE_BREAKING", "REQUEST_SCHEDULER", "REQUEST_PIPELINE", "OUTSTANDING_REQUEST", "REQUEST_TIMEOUT", "ENDGAME_MODE", "CANCEL_MESSAGE", "DISK_IO_PIPELINE", "DISK_WRITE_BUFFER", "DISK_BACKPRESSURE", "RECENT_PIECE_CACHE", "DISK_TELEMETRY", "FILE_PRIORITY", "FORCE_RECHECK", "FAST_RESUME"),
    ),
    HelpTopic(
        key="trackers_discovery",
        title="Trackers & Discovery",
        summary=(
            "How SalixTorrent finds peers through trackers and how to interpret the live Sources "
            "table without confusing discovered peers with connected peers."
        ),
        sections=(
            (
                "Trackers introduce peers",
                "A tracker is a rendezvous server. SalixTorrent announces the torrent's info hash "
                "and receives peer endpoints in return. The actual payload does not flow through "
                "the tracker; data is transferred directly between BitTorrent peers.",
            ),
            (
                "HTTP, HTTPS and UDP trackers",
                "HTTP and HTTPS trackers use web-style announce requests. UDP trackers use the "
                "compact UDP tracker protocol. The transport differs, but the discovery purpose is "
                "the same.",
            ),
            (
                "Tracker scrape statistics",
                "Scrape is separate from announce: it asks a tracker for swarm metadata without "
                "announcing SalixTorrent as a peer or altering swarm participation. SalixTorrent "
                "implements BEP-48 HTTP scrape and BEP-15 UDP scrape. S/L/C means current complete "
                "peers (seeds), current incomplete peers (leechers), and the tracker's cumulative "
                "completed-download count. These values belong to that tracker and should not be "
                "treated as a mathematically global swarm total.",
            ),
            (
                "Efficient scrape batching",
                "A single application-wide coordinator groups active torrents that share a tracker. "
                "HTTP uses bounded repeated-info_hash batches and UDP carries many info hashes under "
                "one tracker connection. Results are cached into Sources telemetry; opening or "
                "redrawing the UI does not itself generate scrape traffic.",
            ),
            (
                "Sources table",
                "Peers is the count reported or learned through that discovery source, not the "
                "number currently connected. Response is tracker request latency. Swarm S/L is the "
                "tracker's seed/leecher estimate. Last Update and Detail expose protocol-specific "
                "diagnostics such as announce intervals and timeouts.",
            ),
            (
                "Source severity: Waiting, Timeout and Error",
                "Waiting is neutral: the source has not produced a result yet. Timeout is an amber "
                "warning that one source did not answer before its deadline, not a torrent-level "
                "failure. Error is red because that source's latest attempt failed for a concrete "
                "reason. Public torrents can continue through other trackers, DHT, PEX and Local "
                "Peer Discovery, and existing peer connections do not depend on a tracker staying online.",
            ),
        ),
        related_terms=(
            "TRACKER",
            "HTTP_TRACKER",
            "HTTPS_TRACKER",
            "UDP_TRACKER",
            "TRACKER_SCRAPE",
            "SCRAPE_BATCHING",
            "SCRAPE_COMPLETED",
            "SOURCE_PEERS",
            "SOURCE_RESPONSE",
            "SOURCE_LAST_UPDATE",
            "SOURCE_WAITING",
            "TRACKER_TIMEOUT",
        ),
    ),
    HelpTopic(
        key="dht_pex_lpd",
        title="DHT / PEX / LPD",
        summary=(
            "The decentralized and peer-assisted discovery systems that let public torrents find "
            "peers without depending entirely on tracker servers."
        ),
        sections=(
            (
                "DHT - Distributed Hash Table",
                "SalixTorrent participates in IPv4 BEP-5 DHT and IPv6 BEP-32 DHT as separate "
                "address-family spaces sharing one scheduler/transaction layer. With Any interface "
                "selected it can keep one UDP socket per available family; a specific IPv4 or IPv6 "
                "bind constrains DHT to that family. Steady-state queries request the matching BEP-32 n4 or n6 node form to avoid unnecessary UDP payload.",
            ),
            (
                "PEX - Peer Exchange",
                "BEP-10 extension negotiation allows connected peers to advertise BEP-11 ut_pex. "
                "SalixTorrent sends and receives both IPv4 compact added/dropped endpoints and the "
                "IPv6 added6/dropped6 forms, so peer-assisted discovery remains dual-stack.",
            ),
            (
                "LPD - Local Peer Discovery",
                "BEP-14 Local Peer Discovery uses IPv4 multicast on the local network. It is useful "
                "when two nearby machines participate in the same torrent. Under an explicit IPv6-"
                "only bind SalixTorrent disables LPD instead of silently sending multicast through "
                "an unrelated IPv4 route.",
            ),
            (
                "Private torrents",
                "Private torrents deliberately disable DHT, PEX and LPD so their swarm discovery "
                "remains controlled by the trackers embedded in the torrent. SalixTorrent also "
                "avoids injecting public fallback trackers into private trackerless metadata.",
            ),
        ),
        related_terms=("DHT", "BEP32", "IPV6", "DUAL_STACK", "PEX", "LPD", "BEP", "DISCOVERY", "PRIVATE_TORRENT"),
    ),
    HelpTopic(
        key="networking",
        title="Networking & Port Mapping",
        summary=(
            "Listen ports, incoming connections, UPnP, NAT-PMP, local/external endpoints and what "
            "an Unmapped connectivity state actually means."
        ),
        sections=(
            (
                "The BitTorrent listen port",
                "SalixTorrent opens explicit IPv4 and IPv6 TCP listeners on the configured numeric "
                "port when Any interface is selected and the platform supports both families. A "
                "specific address bind opens only that family. DHT may use the same numeric port "
                "over UDP because TCP and UDP are separate transports.",
            ),
            (
                "IPv4 NAT versus IPv6 reachability",
                "Home IPv4 commonly uses NAT, so unsolicited inbound IPv4 connections may require a "
                "router port-forward. Globally routed IPv6 normally does not need NAT translation: "
                "reachability instead depends on the IPv6 route and host/router firewall policy. "
                "SalixTorrent therefore treats IPv6 Direct separately from IPv4 port mapping.",
            ),
            (
                "UPnP and NAT-PMP",
                "SalixTorrent uses UPnP and NAT-PMP for IPv4 NAT mappings only. A specifically selected "
                "IPv6 address never triggers an unrelated IPv4 mapping attempt, preserving binding and "
                "Interface Lock semantics. IPv4 mapping diagnostics still preserve protocol stages and "
                "fault codes, including permanent-lease fallback where required.",
            ),
            (
                "Reading the diagnosis",
                "Discovery failures mean SalixTorrent could not find a compatible mapping service. A "
                "gateway refusal means the router answered but denied the request. A port conflict means "
                "the requested external port is already mapped elsewhere. Preferences, General and "
                "Diagnostics preserve these distinctions and suggest a next action without continuously "
                "polling the router.",
            ),
            (
                "Mapped versus Incoming Confirmed",
                "Mapped means the router accepted a mapping request. Incoming Confirmed is stronger "
                "evidence: SalixTorrent has actually observed a remote peer complete an incoming "
                "BitTorrent handshake on that torrent's listen socket. The General view also shows "
                "the exact listener endpoint and active/this-session inbound peer counts. If a router "
                "reports a private, Shared/CGNAT, or other non-global external address, SalixTorrent "
                "labels that as a clue that an upstream NAT may still exist rather than claiming the "
                "Internet path is proven reachable.",
            ),
            (
                "Manual forwarding, double NAT and CGNAT",
                "When automatic mapping is unavailable, manually forwarding the torrent's TCP listen "
                "port to this computer can restore inbound peer reachability; forwarding the same UDP "
                "port can also help DHT. If two routers perform NAT, both layers may need configuration. "
                "With ISP CGNAT, a local router rule may not be enough because the provider controls an "
                "additional upstream translation layer.",
            ),
            (
                "Binding a specific network path",
                "Preferences can bind torrent networking to one local IPv4 or IPv6 address, including a "
                "VPN address. Peer TCP, listeners, HTTP/UDP trackers, DHT and magnet metadata retrieval "
                "stay in that address family. Interface Lock monitors that exact address and fails closed "
                "if it disappears. BEP-14 LPD is deliberately unavailable under IPv6-only binding.",
            ),
            (
                "Tracker and peer IPv6 forms",
                "HTTP trackers may return the compact peers6 field, UDP trackers can resolve/contact an "
                "IPv6 tracker and return 18-byte compact peer endpoints, and PEX carries IPv6 peers in "
                "added6/dropped6. SalixTorrent normalizes all of these into the same family-aware peer "
                "endpoint model while displaying IPv6 address:port pairs with brackets.",
            ),
        ),
        related_terms=("LISTEN_PORT", "LISTENER_ENDPOINT", "INCOMING_CONNECTIONS", "PORT_MAPPING", "MAPPING_METHOD_STATUS", "MAPPING_DIAGNOSIS", "CONNECTIVITY_ACTION", "MAPPING_LEASE", "UPNP", "NATPMP", "MANUAL_PORT_FORWARD", "CGNAT", "DOUBLE_NAT", "LOCAL_ENDPOINT", "EXTERNAL_ENDPOINT", "EXTERNAL_ADDRESS_SCOPE", "NETWORK_BINDING", "INTERFACE_LOCK", "VPN", "IPV6", "DUAL_STACK", "BEP32", "TCP", "UDP"),
    ),
    HelpTopic(
        key="queue_priorities",
        title="Queue & Priorities",
        summary=(
            "How torrent queue position, High/Normal/Low priority, active download slots and file "
            "priorities influence scheduling."
        ),
        sections=(
            (
                "Torrent queue order",
                "Move Up and Move Down change the real queue position. Within the same torrent "
                "priority, earlier queue entries are eligible for download slots first.",
            ),
            (
                "Torrent priority",
                "High, Normal and Low priority determine scheduling preference before queue order. "
                "Changing the visual table sort does not alter this scheduler order.",
            ),
            (
                "Active download slots",
                "The slot limit controls how many torrents may actively download at once. Extra "
                "eligible torrents wait in Queued state. Seeders do not consume download slots. "
                "A slot value of 0 means unlimited.",
            ),
            (
                "File priority and selective downloading",
                "Files inside a multi-file torrent can be High, Normal, Low or Don't Download. "
                "Because a torrent piece can span file boundaries, a small amount of data belonging "
                "to a skipped file may still be necessary to verify a wanted neighboring file.",
            ),
        ),
        related_terms=("QUEUE_ORDER", "QUEUE_PRIORITY", "ACTIVE_DL_SLOTS", "FILE_PRIORITY", "QUEUE_STATUS_FILTER"),
    ),
    HelpTopic(
        key="storage_resume",
        title="Storage & Fast Resume",
        summary=(
            "Where payloads and metadata are stored, how external seed sources differ from normal "
            "downloads, and how fast resume avoids unnecessary full rechecks."
        ),
        sections=(
            (
                "Download storage",
                "Normal downloads write payload data beneath the torrent's assigned storage path. "
                "Existing torrents remember their own paths even if the global default download "
                "directory changes later.",
            ),
            (
                "External seed storage",
                "A torrent created from an existing file or folder can seed directly from that "
                "original source. SalixTorrent treats it as read-only external seed storage and does "
                "not create an unnecessary duplicate copy in the downloads directory.",
            ),
            (
                "Fast resume",
                "After verified progress is known, SalixTorrent stores compact resume information. "
                "On a later launch it can validate the expected storage fingerprint and restore "
                "verified state quickly instead of hashing every piece again.",
            ),
            (
                "When a recheck is needed",
                "If payload files change outside SalixTorrent, resume fingerprints may no longer be "
                "trusted. A proper piece recheck verifies the actual bytes again and marks only "
                "matching pieces complete.",
            ),
        ),
        related_terms=("STORAGE_MODE", "STORAGE_PATH", "FAST_RESUME", "FORCE_RECHECK", "DEFAULT_DOWNLOAD_DIR", "TORRENT_PATH"),
    ),
    HelpTopic(
        key="privacy",
        title="Privacy",
        summary=(
            "Peer transport encryption, interface/VPN binding, Interface Lock, display masking, "
            "and the privacy limits inherent to direct BitTorrent networking."
        ),
        sections=(
            (
                "Peer transport encryption (MSE/PE)",
                "Prefer Encryption is SalixTorrent's default: it tries MSE/RC4 first and opens a fresh "
                "plaintext connection only when the peer does not support MSE. Require Encryption "
                "never falls back. MSE/PE obscures the BitTorrent peer stream, but it is a legacy "
                "protocol rather than modern authenticated encryption and cannot guarantee that an ISP "
                "cannot classify or block BitTorrent traffic.",
            ),
            (
                "Network binding and Interface Lock",
                "Selecting a specific Network Interface / VPN address already source-binds SalixTorrent's "
                "peer sockets, incoming listener, trackers, DHT, LPD and magnet metadata traffic to that "
                "address. Interface Lock is an additional active kill switch: if the selected address "
                "disappears, the torrent enters Error and its torrent networking is closed immediately.",
            ),
            (
                "Peer IP masking",
                "Mask Peer IP Addresses is disabled by default and changes only what SalixTorrent draws "
                "on screen. It can make screenshots less revealing, but it does not alter the real peer "
                "connection or hide network endpoints from peers, trackers, a VPN provider or an ISP.",
            ),
            (
                "Private torrents and discovery",
                "A torrent with private=1 requests tracker-controlled swarm discovery. SalixTorrent "
                "disables public DHT, PEX and Local Peer Discovery for those torrents and does not "
                "inject public fallback trackers when no tracker is supplied.",
            ),
            (
                "Peer visibility",
                "Direct BitTorrent peers normally learn one another's network endpoint because a direct "
                "connection requires an address and port. Peer transport encryption does not turn "
                "BitTorrent into an anonymity system.",
            ),
            (
                "Trackers, metadata and payload",
                "Trackers coordinate discovery and normally do not relay torrent payload bytes. DHT, "
                "LPD and PEX exchange discovery information when enabled, while magnet metadata and "
                "torrent payload travel directly between compatible peers.",
            ),
        ),
        related_terms=(
            "MSE", "PE", "RC4", "PEER_ENCRYPTION_POLICY", "TRANSPORT_SECURITY",
            "NETWORK_BINDING", "INTERFACE_LOCK", "VPN", "IP_MASKING",
            "PRIVATE_TORRENT", "DHT", "PEX", "LPD", "TRACKER", "PEER_ADDRESS",
        ),
    ),
    HelpTopic(
        key="torrent_creation",
        title="Torrent Creation",
        summary=(
            "Creating standards-compatible BitTorrent v1 metadata from a file or folder and becoming "
            "the initial seed without copying the source."
        ),
        sections=(
            (
                "Choosing a source",
                "A single file creates a single-file torrent. A folder creates a multi-file torrent "
                "that preserves relative paths. Directory symlinks are deliberately not followed so "
                "unexpected data outside the chosen source is not included.",
            ),
            (
                "Piece size and hashing",
                "SalixTorrent reads the source and produces SHA-1 hashes for each BitTorrent v1 "
                "piece. Auto piece size balances metadata size and verification granularity. The "
                "source is monitored so changing data is not silently published with inconsistent "
                "hashes.",
            ),
            (
                "Trackers, comments and privacy",
                "Tracker URLs become peer-discovery metadata. Comments and creation information are "
                "descriptive. Marking a torrent private changes how compatible clients should perform "
                "peer discovery and causes SalixTorrent to disable DHT, PEX and LPD for that torrent.",
            ),
            (
                "Start Seeding",
                "After creation, Start Seeding verifies the original source against the new torrent "
                "and then serves it in place as read-only external seed storage. The creator does not "
                "need a redundant second copy under downloads/.",
            ),
        ),
        related_terms=("CREATE_TORRENT", "TORRENT_SOURCE_FILE", "TORRENT_SOURCE_FOLDER", "PIECE_SIZE", "TRACKER_LIST", "START_SEEDING", "PRIVATE_TORRENT"),
    ),
    HelpTopic(
        key="controls",
        title="SalixTorrent Controls",
        summary=(
            "A tour of the main application views, torrent context actions, filtering, diagnostics "
            "and the traditional desktop menu."
        ),
        sections=(
            (
                "Active Transfers",
                "The main view contains the torrent queue, lifecycle controls and selected-torrent "
                "detail tabs: General, Peers, Pieces, Files, Sources and Speed. Switching views does "
                "not pause networking.",
            ),
            (
                "Context actions",
                "Right-click a torrent row for Move Up/Down, priority, transfer-rate display units, "
                "Start/Pause/Resume/Stop, tracker update, Force Recheck, folder access, copy actions, "
                "Properties and safe removal choices.",
            ),
            (
                "Search, filter and sort",
                "The queue can be filtered by name and lifecycle status. Clicking supported table "
                "headers sorts the display only; Queue Order returns to scheduler order without "
                "changing the underlying torrent priorities.",
            ),
            (
                "Preferences and diagnostics",
                "Preferences controls storage defaults, networking/discovery, bandwidth, queue "
                "behavior and desktop integration. Help > Diagnostics produces a copyable runtime "
                "snapshot including connectivity state and application-data paths for troubleshooting.",
            ),
            (
                "Resizing and layout",
                "SalixTorrent uses event-driven responsive layout for its main workspaces and "
                "data-heavy dialogs. Tables, plots, help panes, tracker editors and diagnostic "
                "text use additional window space when available, while dialog action rows stay "
                "with the bottom of the resizable content. Layout work runs only when geometry "
                "changes rather than continuously in the render loop.",
            ),
        ),
        related_terms=(
            "ACTIVE_TRANSFERS_VIEW",
            "PREFERENCES_VIEW",
            "QUEUE_SEARCH",
            "QUEUE_STATUS_FILTER",
            "PROPERTIES",
            "DIAGNOSTICS",
            "RESPONSIVE_LAYOUT",
            "REMOVE_TORRENT",
        ),
    ),
    HelpTopic(
        key="glossary",
        title="Glossary A-Z",
        summary=(
            "An alphabetized index of the technical terms used throughout SalixTorrent. Select the "
            "Glossary A-Z tab on the left to browse individual definitions."
        ),
        sections=(
            (
                "One definition everywhere",
                "The glossary is generated from the same HELP_TERMS dictionary that powers the "
                "application's hover tooltips. This keeps the built-in manual and contextual help "
                "consistent instead of maintaining two unrelated sets of explanations.",
            ),
            (
                "Using the index",
                "Choose Glossary A-Z in the left panel, then select any term to read its full "
                "definition on the right. The search field filters both help topics and glossary "
                "entries, so acronyms such as DHT, PEX, LPD, UPnP and NAT-PMP are easy to locate.",
            ),
        ),
        related_terms=("BEP", "DHT", "PEX", "LPD", "UPNP", "NATPMP", "INFO_HASH", "FAST_RESUME"),
    ),
)


TOPIC_BY_KEY: Dict[str, HelpTopic] = {topic.key: topic for topic in HELP_TOPICS}

# Map glossary entries back to the most useful explanatory article. Terms not
# explicitly listed fall back to BitTorrent Basics or SalixTorrent Controls.
TERM_TOPIC_MAP: Dict[str, str] = {}
for _topic in HELP_TOPICS:
    for _term in _topic.related_terms:
        TERM_TOPIC_MAP.setdefault(_term, _topic.key)


class HelpTopicsView:
    """Old-school CHM-style built-in manual.

    A subject/index navigator lives on the left and the selected article or
    glossary definition lives on the right.  The view is intentionally a normal
    SalixTorrent scene rather than a modal so the application menu remains
    available while reading help.
    """

    def __init__(self):
        self.parent_tag = None
        self.search_input = None
        self.search_status = None
        self.left_tab_bar = None
        self.contents_tab = None
        self.glossary_tab = None
        self.content_body = None
        self.content_title = None
        self.content_summary = None
        self.content_sections = None
        self._topic_items: Dict[str, int] = {}
        self._term_items: Dict[str, int] = {}
        self._glossary_letter_groups: Dict[str, int] = {}
        self._term_letters: Dict[str, str] = {}
        self._current_topic = "basics"
        self._current_term = ""
        self.right_pane = None
        self._wrapped_content_items: List[int] = []
        self._last_wrap_width = 700
        self.layout = ResponsiveLayout.get_instance()
        self._layout_root = None
        self.left_pane = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_view(self, parent_tag: str):
        self.parent_tag = parent_tag

        dpg.add_text("SALIXTORRENT HELP TOPICS", color=(0, 255, 128), parent=parent_tag)
        dpg.add_text(
            "Built-in reference for BitTorrent concepts and SalixTorrent controls. "
            "Select a subject on the left; its explanation appears on the right.",
            color=(165, 165, 170),
            parent=parent_tag,
            wrap=1000,
        )
        dpg.add_spacer(height=4, parent=parent_tag)

        search_row = dpg.add_group(horizontal=True, parent=parent_tag)
        dpg.add_text("Search", parent=search_row)
        self.search_input = dpg.add_input_text(
            hint="Search topics and glossary...",
            width=430,
            parent=search_row,
            callback=self._on_search_changed,
        )
        clear_button = dpg.add_button(
            label=" Clear ",
            parent=search_row,
            callback=self._clear_search,
        )
        self.search_status = dpg.add_text("", color=(140, 180, 220), parent=search_row)
        add_text_tooltip(
            self.search_input,
            "Help search\n\nFilters both the subject list and the A-Z glossary. Search by full words, acronyms such as DHT/PEX/LPD, or concepts such as port mapping, pieces, privacy or magnet links.",
        )
        add_text_tooltip(clear_button, "Clear help search\n\nRestores the complete Contents and Glossary A-Z lists.")

        dpg.add_separator(parent=parent_tag)
        dpg.add_spacer(height=3, parent=parent_tag)

        split = dpg.add_group(horizontal=True, parent=parent_tag)
        left = dpg.add_child_window(width=340, height=-1, border=True, parent=split)
        right = dpg.add_child_window(width=-1, height=-1, border=True, parent=split)
        self.left_pane = left
        self.right_pane = right

        self.left_tab_bar = dpg.add_tab_bar(parent=left)
        self.contents_tab = dpg.add_tab(label="Contents", parent=self.left_tab_bar)
        self.glossary_tab = dpg.add_tab(label="Glossary A-Z", parent=self.left_tab_bar)

        self._build_contents_index()
        self._build_glossary_index()

        self.content_title = dpg.add_text("", color=(100, 180, 255), parent=right)
        self.content_summary = dpg.add_text(
            "", color=(180, 180, 185), wrap=self._last_wrap_width, parent=right
        )
        self._wrapped_content_items = [self.content_summary]
        dpg.add_separator(parent=right)
        self.content_sections = dpg.add_group(parent=right)

        self._show_topic("basics")

        self._layout_root = parent_tag
        self.layout.watch_item(
            parent_tag,
            ("help_topics", "root"),
            self._layout_help_view,
        )

    def _layout_help_view(self):
        width, _height = self.layout.item_size(self._layout_root)
        if width <= 1:
            return

        left_width, right_width = split_widths(
            width - 16,
            (0.28, 0.72),
            minimums=(260, 500),
            gap=8,
        )
        self.layout.width(self.left_pane, left_width)
        self.layout.width(self.right_pane, right_width)
        self.layout.width(self.search_input, clamp(width * 0.36, 280, 620))
        self._update_content_wrap(force=True)

    def _build_contents_index(self):
        intro = dpg.add_text("CONTENTS", color=(100, 180, 255), parent=self.contents_tab)
        add_text_tooltip(
            intro,
            "Help Contents\n\nThe main SalixTorrent manual arranged by subject, similar to the Contents pane in traditional Windows CHM help files.",
        )
        dpg.add_separator(parent=self.contents_tab)

        for topic in HELP_TOPICS:
            item = dpg.add_selectable(
                label=topic.title,
                parent=self.contents_tab,
                callback=self._on_topic_selected,
                user_data=topic.key,
            )
            self._topic_items[topic.key] = item
            add_text_tooltip(item, f"{topic.title}\n\n{topic.summary}")

    @staticmethod
    def _glossary_sort_key(entry: Tuple[str, Tuple[str, str]]):
        key, value = entry
        title = str(value[0] if value else key)
        return title.casefold()

    def _build_glossary_index(self):
        intro = dpg.add_text("GLOSSARY A-Z", color=(100, 180, 255), parent=self.glossary_tab)
        add_text_tooltip(
            intro,
            "Glossary A-Z\n\nAlphabetical index generated from the same definitions used by SalixTorrent's contextual hover help.",
        )
        dpg.add_separator(parent=self.glossary_tab)

        current_group = None
        last_letter = ""
        for key, (title, body) in sorted(HELP_TERMS.items(), key=self._glossary_sort_key):
            letter = self._index_letter(title)
            if letter != last_letter:
                current_group = dpg.add_group(parent=self.glossary_tab)
                self._glossary_letter_groups[letter] = current_group
                dpg.add_spacer(height=3, parent=current_group)
                dpg.add_text(letter, color=(255, 200, 100), parent=current_group)
                last_letter = letter

            item = dpg.add_selectable(
                label=title,
                parent=current_group or self.glossary_tab,
                callback=self._on_term_selected,
                user_data=key,
            )
            self._term_items[key] = item
            self._term_letters[key] = letter
            add_text_tooltip(item, f"{title}\n\n{body}")

    @staticmethod
    def _index_letter(title: str) -> str:
        for ch in str(title).strip():
            if ch.isalpha():
                return ch.upper()
            if ch.isdigit():
                return "#"
        return "#"

    # ------------------------------------------------------------------
    # Dear PyGui callbacks
    # ------------------------------------------------------------------

    def _on_topic_selected(self, sender=None, app_data=None, user_data=None):
        """Render the Help Topic selected in the Contents navigator.

        Dear PyGui always supplies ``user_data`` as the third callback argument.
        Keeping the topic key in the item's explicit ``user_data`` avoids a subtle
        lambda/default-argument bug where DPG's ``None`` replaced the captured key.
        """
        if user_data is not None:
            self._show_topic(str(user_data))

    def _on_term_selected(self, sender=None, app_data=None, user_data=None):
        """Render the selected A-Z glossary definition."""
        if user_data is not None:
            self._show_term(str(user_data))

    def _on_related_term_clicked(self, sender=None, app_data=None, user_data=None):
        """Follow a Help Topic -> related glossary cross-reference."""
        if user_data is not None:
            self._open_glossary_term(str(user_data))

    def _on_related_topic_clicked(self, sender=None, app_data=None, user_data=None):
        """Follow a glossary definition -> related Help Topic cross-reference."""
        if user_data is not None:
            self._open_contents_topic(str(user_data))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _clear_content(self):
        if not self.content_sections:
            return
        try:
            dpg.delete_item(self.content_sections, children_only=True)
        except Exception:
            pass
        self._wrapped_content_items = (
            [self.content_summary] if self.content_summary is not None else []
        )

    def _set_selections(self, topic_key: str = "", term_key: str = ""):
        for key, item in self._topic_items.items():
            try:
                dpg.set_value(item, key == topic_key)
            except Exception:
                pass
        for key, item in self._term_items.items():
            try:
                dpg.set_value(item, key == term_key)
            except Exception:
                pass

    def _show_topic(self, topic_key: str):
        topic = TOPIC_BY_KEY.get(str(topic_key))
        if topic is None:
            return

        self._current_topic = topic.key
        self._current_term = ""
        self._set_selections(topic_key=topic.key)

        dpg.set_value(self.content_title, topic.title)
        dpg.set_value(self.content_summary, topic.summary)
        self._clear_content()

        for heading, body in topic.sections:
            dpg.add_text(heading.upper(), color=(255, 200, 100), parent=self.content_sections)
            body_item = dpg.add_text(
                body, wrap=self._last_wrap_width, parent=self.content_sections
            )
            self._wrapped_content_items.append(body_item)
            dpg.add_spacer(height=9, parent=self.content_sections)

        if topic.related_terms:
            dpg.add_separator(parent=self.content_sections)
            dpg.add_text("RELATED GLOSSARY TERMS", color=(100, 180, 255), parent=self.content_sections)
            related_row = None
            count_in_row = 0
            for term_key in topic.related_terms:
                entry = HELP_TERMS.get(term_key)
                if not entry:
                    continue
                if related_row is None or count_in_row >= 3:
                    related_row = dpg.add_group(horizontal=True, parent=self.content_sections)
                    count_in_row = 0
                button = dpg.add_button(
                    label=f" {entry[0]} ",
                    parent=related_row,
                    callback=self._on_related_term_clicked,
                    user_data=term_key,
                )
                add_text_tooltip(button, f"Open glossary entry\n\n{entry[0]}\n\n{entry[1]}")
                count_in_row += 1

        if topic.key == "glossary":
            dpg.add_spacer(height=8, parent=self.content_sections)
            button = dpg.add_button(
                label=" Open Glossary A-Z ",
                parent=self.content_sections,
                callback=self._open_glossary_tab,
            )
            add_text_tooltip(button, "Open Glossary A-Z\n\nSwitches the left navigator to the alphabetized glossary index.")

    def _show_term(self, term_key: str):
        key = str(term_key or "").upper()
        entry = HELP_TERMS.get(key)
        if not entry:
            return

        title, body = entry
        self._current_term = key
        self._set_selections(term_key=key)
        dpg.set_value(self.content_title, title)
        dpg.set_value(self.content_summary, "Glossary definition")
        self._clear_content()

        body_item = dpg.add_text(
            body, wrap=self._last_wrap_width, parent=self.content_sections
        )
        self._wrapped_content_items.append(body_item)
        dpg.add_spacer(height=10, parent=self.content_sections)

        topic_key = TERM_TOPIC_MAP.get(key, "basics")
        topic = TOPIC_BY_KEY.get(topic_key)
        if topic:
            dpg.add_separator(parent=self.content_sections)
            dpg.add_text("RELATED HELP TOPIC", color=(100, 180, 255), parent=self.content_sections)
            button = dpg.add_button(
                label=f" {topic.title} ",
                parent=self.content_sections,
                callback=self._on_related_topic_clicked,
                user_data=topic.key,
            )
            add_text_tooltip(button, f"Open help topic\n\n{topic.title}\n\n{topic.summary}")

    def _open_contents_topic(self, topic_key: str):
        try:
            dpg.set_value(self.left_tab_bar, self.contents_tab)
        except Exception:
            pass
        self._show_topic(topic_key)

    def _open_glossary_term(self, term_key: str):
        try:
            dpg.set_value(self.left_tab_bar, self.glossary_tab)
        except Exception:
            pass
        self._show_term(term_key)

    def _open_glossary_tab(self, sender=None, app_data=None, user_data=None):
        try:
            dpg.set_value(self.left_tab_bar, self.glossary_tab)
        except Exception:
            pass
        # Keep the right pane on the glossary overview until a term is selected.

    def open_glossary(self):
        """Public helper used by menu commands to jump directly to the A-Z index."""
        self._open_glossary_tab()
        if self._current_term:
            self._show_term(self._current_term)
        else:
            self._show_topic("glossary")

    def _update_content_wrap(self, force: bool = False):
        """Keep Help text readable at both windowed and maximized sizes.

        The content pane may become very wide on a large monitor. A bounded
        reading measure uses more of that space without creating extremely long
        lines that are tiring to scan.
        """
        if self.right_pane is None:
            return
        try:
            width = float(dpg.get_item_rect_size(self.right_pane)[0])
        except Exception:
            return
        if width <= 1:
            return

        target = int(max(560, min(1050, width - 36)))
        if not force and abs(target - self._last_wrap_width) < 8:
            return
        self._last_wrap_width = target

        alive = []
        for item in self._wrapped_content_items:
            try:
                if dpg.does_item_exist(item):
                    dpg.configure_item(item, wrap=target)
                    alive.append(item)
            except Exception:
                continue
        self._wrapped_content_items = alive

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @staticmethod
    def _matches(query: str, values: Iterable[str]) -> bool:
        if not query:
            return True
        needle = query.casefold()
        return any(needle in str(value).casefold() for value in values)

    def _on_search_changed(self, sender=None, app_data=None, user_data=None):
        try:
            query = str(dpg.get_value(self.search_input) or "").strip()
        except Exception:
            query = str(app_data or "").strip()

        visible_topics = 0
        for topic in HELP_TOPICS:
            values: List[str] = [topic.title, topic.summary]
            for heading, body in topic.sections:
                values.extend((heading, body))
            for term_key in topic.related_terms:
                entry = HELP_TERMS.get(term_key)
                if entry:
                    values.extend(entry)
            show = self._matches(query, values)
            visible_topics += int(show)
            try:
                dpg.configure_item(self._topic_items[topic.key], show=show)
            except Exception:
                pass

        visible_terms = 0
        visible_letters = set()
        for key, (title, body) in HELP_TERMS.items():
            show = self._matches(query, (key, title, body))
            visible_terms += int(show)
            if show:
                visible_letters.add(self._term_letters.get(key, ""))
            try:
                dpg.configure_item(self._term_items[key], show=show)
            except Exception:
                pass

        for letter, group in self._glossary_letter_groups.items():
            try:
                dpg.configure_item(group, show=(not query or letter in visible_letters))
            except Exception:
                pass

        if query:
            dpg.set_value(
                self.search_status,
                f"{visible_topics} topic(s), {visible_terms} glossary term(s)",
            )
        else:
            dpg.set_value(self.search_status, "")

    def _clear_search(self, sender=None, app_data=None, user_data=None):
        try:
            dpg.set_value(self.search_input, "")
        except Exception:
            pass
        self._on_search_changed()

    # Scene hooks -------------------------------------------------------

    def on_show(self, **kwargs):
        self.layout.trigger(("help_topics", "root"))
        self._update_content_wrap(force=True)
        if kwargs.get("glossary"):
            self.open_glossary()
        elif kwargs.get("topic"):
            self._open_contents_topic(str(kwargs["topic"]))

    def update(self, dt: float):
        # Layout is resize-event driven; there is intentionally no per-frame
        # geometry polling in the Help view.
        del dt
