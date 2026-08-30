# app/views/help_terms.py

from __future__ import annotations

from typing import Iterable, Optional

import dearpygui.dearpygui as dpg


# This glossary is the single source of truth for inline hover help. The planned
# Help -> Help Topics / Glossary window can consume the same entries later, so
# SalixTorrent never ends up with one definition in the UI and another in the
# documentation.
HELP_TERMS = {
    # ------------------------------------------------------------------
    # BitTorrent / discovery terminology
    # ------------------------------------------------------------------
    "DHT": (
        "DHT - Distributed Hash Table",
        "A decentralized BitTorrent peer-discovery network. SalixTorrent participates "
        "in the IPv4 BEP-5 DHT and the IPv6 BEP-32 DHT when those address families "
        "are available. A specific network bind restricts DHT to that family. Private "
        "torrents deliberately disable DHT.",
    ),
    "PEX": (
        "PEX - Peer Exchange",
        "A BitTorrent extension where already-connected peers introduce one another "
        "to additional peers. SalixTorrent negotiates BEP-10 and exchanges BEP-11 "
        "IPv4 added/dropped endpoints plus IPv6 added6/dropped6 endpoints. Private "
        "torrents deliberately disable PEX.",
    ),
    "LPD": (
        "LPD - Local Peer Discovery",
        "BEP-14 Local Peer Discovery uses IPv4 multicast to find compatible peers on "
        "the same LAN. It does not search the wider Internet. Because BEP-14 is IPv4-"
        "multicast based, SalixTorrent disables LPD under an explicit IPv6-only bind "
        "rather than leaking discovery through a different IPv4 interface. Private "
        "torrents also disable LPD.",
    ),
    "LAN": (
        "LAN - Local Area Network",
        "Your nearby private network, such as computers connected to the same "
        "home or office router. LAN peers can often exchange data directly at "
        "local-network speed without sending the payload through the Internet.",
    ),
    "UPNP": (
        "UPnP - Universal Plug and Play",
        "A router protocol SalixTorrent can use to request automatic incoming "
        "port mappings for its active torrent listeners. SalixTorrent records the exact "
        "stage and router fault code when available, and automatically retries with a "
        "permanent lease when an IGD reports that only permanent mappings are supported. "
        "Failure is not fatal: outbound peer connections can still download and upload normally.",
    ),
    "NATPMP": (
        "NAT-PMP - NAT Port Mapping Protocol",
        "A lightweight automatic router port-mapping protocol used as a fallback "
        "when UPnP is unavailable. SalixTorrent decodes standard NAT-PMP result codes so a "
        "timeout, authorization refusal, network failure, resource exhaustion, or unsupported "
        "operation can be distinguished. Failure remains non-fatal to outbound transfers.",
    ),
    "BEP": (
        "BEP - BitTorrent Enhancement Proposal",
        "A numbered specification describing a BitTorrent protocol or extension. "
        "Examples: BEP-5 defines IPv4 DHT, BEP-9 defines magnet metadata exchange, "
        "BEP-11 defines Peer Exchange, BEP-14 defines Local Peer Discovery, BEP-15 "
        "defines the UDP tracker protocol including scrape, BEP-32 extends DHT to IPv6, "
        "and BEP-48 documents HTTP tracker scrape conventions.",
    ),
    "BEP32": (
        "BEP-32 - IPv6 Extension for DHT",
        "The BitTorrent extension that adds IPv6 node/address forms to the DHT. "
        "SalixTorrent maintains separate IPv4 and IPv6 UDP sockets/address spaces and "
        "uses family-appropriate n4/n6 node requests without running a duplicate polling loop.",
    ),
    "IPV6": (
        "IPv6",
        "The 128-bit Internet Protocol address family. SalixTorrent can connect to IPv6 "
        "peers, accept IPv6 peer TCP connections, consume tracker peers6 responses, "
        "exchange IPv6 PEX endpoints, and participate in BEP-32 DHT. IPv6 endpoints are "
        "displayed in brackets when a port follows them, for example [2001:db8::1]:6881.",
    ),
    "DUAL_STACK": (
        "Dual Stack",
        "Using IPv4 and IPv6 at the same time. With Any interface selected, SalixTorrent "
        "opens explicit family-specific peer/DHT sockets when the operating system supports "
        "them. Selecting a specific IPv4 or IPv6 address constrains torrent networking to "
        "that family instead of silently escaping through the other one.",
    ),
    "BEP9": (
        "BEP-9 - Extension for Peers to Send Metadata Files",
        "The protocol used to retrieve a torrent's metadata from peers when you "
        "start with only a magnet link. SalixTorrent downloads the metadata in "
        "small pieces, reconstructs it, and verifies that its SHA-1 info hash "
        "matches the magnet before accepting it.",
    ),
    "TCP": (
        "TCP - Transmission Control Protocol",
        "The reliable, connection-oriented transport used for normal BitTorrent "
        "peer-wire connections. One TCP peer connection is bidirectional: both "
        "clients can upload and download pieces over the same connection.",
    ),
    "UDP": (
        "UDP - User Datagram Protocol",
        "A lightweight datagram transport used by DHT, UDP trackers, Local Peer "
        "Discovery multicast, and some automatic router-mapping protocols. UDP "
        "does not establish a reliable stream like TCP does.",
    ),
    "TRACKER": (
        "BitTorrent Tracker",
        "A server that introduces peers participating in the same torrent. The "
        "tracker coordinates discovery; the actual torrent payload is transferred "
        "directly between peers, not through the tracker.",
    ),
    "HTTP_TRACKER": (
        "HTTP Tracker",
        "A BitTorrent tracker contacted with HTTP announce requests for peer discovery. "
        "When its announce path has a standards-defined scrape counterpart, SalixTorrent "
        "can also batch BEP-48 scrape statistics for multiple active torrents. Torrent "
        "payload data does not pass through the tracker.",
    ),
    "HTTPS_TRACKER": (
        "HTTPS Tracker",
        "A BitTorrent tracker contacted using encrypted HTTPS. It performs the "
        "same discovery role as an HTTP tracker while protecting the tracker "
        "request in transit. Torrent payload data is still exchanged peer-to-peer.",
    ),
    "UDP_TRACKER": (
        "UDP Tracker",
        "A tracker using BEP-15's compact UDP protocol. In addition to announce, BEP-15 "
        "defines a scrape action that can return seed, leecher and completed-download counts "
        "for many info hashes in one datagram. Torrent payload is still exchanged directly "
        "between peers.",
    ),
    "TRACKER_SCRAPE": (
        "Tracker Scrape - S / L / C",
        "A tracker scrape asks for swarm statistics without announcing SalixTorrent as a peer "
        "and without changing swarm participation. S is complete peers (seeds), L is incomplete "
        "peers (leechers), and C is the tracker's cumulative completed-download counter. "
        "SalixTorrent batches multiple active torrents that share a tracker so one scrape can "
        "return several swarms' statistics efficiently. HTTP uses the BEP-48 scrape endpoint; "
        "UDP uses BEP-15 action 2.",
    ),
    "SCRAPE_BATCHING": (
        "Tracker Scrape Batching",
        "Instead of sending one scrape request per torrent, SalixTorrent groups active torrents "
        "that use the same tracker. HTTP requests carry repeated info_hash parameters in bounded "
        "batches; UDP requests carry many 20-byte info hashes under one tracker connection. "
        "The coordinator is shared application-wide and timer-driven, so the UI does not create "
        "network traffic merely by displaying statistics.",
    ),
    "SCRAPE_COMPLETED": (
        "Scrape Completed Downloads",
        "The C value from a tracker scrape is the tracker's cumulative count of completed "
        "downloads for that info hash. It is not the number of current seeds and it is not a "
        "globally authoritative total: different trackers may maintain different populations "
        "and historical counters.",
    ),
    "DISCOVERY": (
        "Peer Discovery",
        "The ways SalixTorrent can learn that other peers exist. Public torrents "
        "can use trackers, DHT, PEX and LPD/LAN. Private torrents intentionally "
        "restrict discovery to their configured trackers.",
    ),
    "SOURCE_PEERS": (
        "Peers Reported by This Source",
        "This count belongs to one discovery source and is not necessarily the "
        "number of peers currently connected. Sources can discover duplicate, "
        "offline, unreachable, or already-connected endpoints.",
    ),
    "SWARM_SL": (
        "Swarm S/L - Seeds / Leechers",
        "Seed/leecher counts reported by a tracker announce result. The Sources view keeps "
        "these announce figures separate from scrape S/L/C statistics so advanced users can "
        "see which tracker operation supplied each number. '--' means the source has not "
        "provided comparable announce counts.",
    ),
    "SOURCE_RESPONSE": (
        "Discovery Response Time",
        "How long the latest tracker request took to complete. This measures the "
        "tracker response, not a peer's download latency or transfer speed. '--' "
        "means this source does not expose a comparable request/response time.",
    ),
    "SOURCE_LAST_UPDATE": (
        "Last Discovery Update",
        "How long ago SalixTorrent last received or recorded activity from this "
        "discovery source. 'Never' means no result has been recorded yet.",
    ),
    "SOURCE_DETAIL": (
        "Discovery Detail",
        "Protocol-specific diagnostic information such as tracker announce "
        "intervals, DHT node activity, PEX receive/transmit counts, or the Local "
        "Peer Discovery multicast endpoint.",
    ),
    "SOURCE_WAITING": (
        "Discovery Source: Waiting",
        "A neutral discovery state. The source exists but has not produced a result yet, "
        "or its next scheduled announce/query has not run. Waiting is not a failure and "
        "does not imply that the torrent is unable to find peers through other sources.",
    ),
    "TRACKER_TIMEOUT": (
        "Tracker Timeout",
        "A warning that one tracker did not answer before its request deadline. Public "
        "trackers can be overloaded, offline, filtered, or temporarily unreachable. A "
        "timeout is source-local rather than a torrent failure: other trackers, DHT, PEX "
        "and LPD can continue discovering peers, and already-connected peers are unaffected.",
    ),

    # ------------------------------------------------------------------
    # Swarm / peer state
    # ------------------------------------------------------------------
    "SEEDS_LEECHERS": (
        "Seeds / Leechers",
        "A seed has the complete torrent and can upload any piece. A leecher is "
        "still obtaining some of the torrent. Tracker counts are estimates and "
        "can differ from SalixTorrent's currently connected peers.",
    ),
    "CONNECTED_PEERS": (
        "Connected Peers",
        "The number of live BitTorrent peer connections currently attached to "
        "this torrent. This is different from the number of peers discovered by "
        "trackers, DHT or PEX because not every discovered endpoint connects.",
    ),
    "AVAILABILITY": (
        "Swarm Availability",
        "An estimate of how many complete copies of the torrent are represented "
        "by pieces advertised by connected peers. Below 1.0 can mean the current "
        "connected swarm does not contain every piece required to finish.",
    ),
    "SWARM_HEALTH": (
        "Swarm Health",
        "A human-readable summary derived from the torrent's current peer and "
        "piece availability. It helps explain whether the connected swarm appears "
        "capable of supplying the wanted data; it is not a guarantee of speed.",
    ),
    "PEER_ADDRESS": (
        "Peer Address",
        "The remote IP address and TCP port of this live BitTorrent connection. "
        "It identifies the network endpoint SalixTorrent is talking to, not the "
        "person or account using that client. Optional IP masking changes only how "
        "the address is displayed in SalixTorrent; the real endpoint is still "
        "required for the peer-to-peer connection.",
    ),
    "PEER_CLIENT": (
        "Peer Client",
        "A best-effort client name/version decoded from the peer ID or extension "
        "handshake sent by the remote program. It is self-reported protocol "
        "information and is not cryptographic proof of the remote software.",
    ),
    "PEER_SOURCE": (
        "Peer Source",
        "How SalixTorrent originally learned about this peer: a tracker, DHT, PEX, "
        "Local Peer Discovery, or an incoming connection. The data connection "
        "itself is still a direct peer-to-peer TCP connection.",
    ),
    "PEER_DIRECTION": (
        "Connection Direction",
        "Outgoing means SalixTorrent initiated the TCP connection. Incoming means "
        "the remote peer connected to SalixTorrent's listen port. Either direction "
        "can carry both downloads and uploads.",
    ),
    "PEER_PROGRESS": (
        "Peer Piece Completion",
        "An estimate of how much of the torrent this remote peer has advertised "
        "through its bitfield and HAVE messages. '--' means the peer has not sent "
        "enough information to calculate a percentage.",
    ),
    "PEER_FLAGS": (
        "Peer Protocol Flags",
        "I = SalixTorrent is interested in data from the peer; i = the peer is "
        "interested in our data; C = the peer is choking us; c = we are choking "
        "the peer. Choking is normal BitTorrent flow control, not an error.",
    ),
    "PEER_STATE": (
        "Peer Connection State",
        "A compact summary of what this connection is doing now, such as Ready, "
        "Downloading, Uploading, or Choked. The peer-wire flags provide the more "
        "precise protocol-level flow-control state.",
    ),
    "PEER_AGE": (
        "Connection Age",
        "How long this particular peer connection has remained established during "
        "the current torrent run. Disconnecting and reconnecting starts a new age.",
    ),

    # ------------------------------------------------------------------
    # Torrent structure / verification
    # ------------------------------------------------------------------
    "INFO_HASH": (
        "Info Hash",
        "The SHA-1 identifier of a BitTorrent v1 torrent's exact bencoded info "
        "dictionary. Peers use it to identify the swarm, and v1 magnet links "
        "contain the same value as their btih identifier.",
    ),
    "PIECE": (
        "Torrent Pieces",
        "A torrent payload is divided into fixed-size pieces. Each piece has a "
        "cryptographic hash and is treated as trusted only after the complete "
        "piece has been received and verified.",
    ),
    "PIECE_SIZE": (
        "Piece Size",
        "The amount of payload represented by most torrent pieces. Smaller pieces "
        "create more hashes and metadata but allow finer-grained verification; "
        "larger pieces reduce metadata overhead. The final piece may be smaller.",
    ),
    "PIECE_MAP": (
        "Piece Map",
        "A visual overview of the torrent's piece states. Large torrents are "
        "condensed so one map cell can represent several pieces. The map is a "
        "display aid only; verification still happens per real torrent piece.",
    ),
    "BLOCK": (
        "Piece Blocks",
        "Pieces are normally requested from peers in smaller blocks (commonly "
        "16 KiB). Blocks can arrive out of order or from different peers. A piece "
        "is not trusted until all of its blocks are present and its hash verifies.",
    ),
    "PIECE_AVAILABILITY": (
        "Piece Availability",
        "How many currently connected peers advertise that they possess this "
        "specific piece. SalixTorrent updates this count incrementally from peer "
        "BITFIELD, HAVE, and disconnect events and uses it for rarest-first piece "
        "selection. A value of 0 means no connected peer is currently known to "
        "supply the piece.",
    ),
    "RAREST_FIRST": (
        "Rarest-First Piece Selection",
        "Within the current file-priority level, SalixTorrent prefers incomplete "
        "pieces advertised by the fewest connected peers. Acquiring scarce pieces "
        "early reduces the chance of losing access to them and helps redistribute "
        "rare data through the swarm. File priority remains the stronger rule.",
    ),
    "RANDOM_TIE_BREAKING": (
        "Random Rarity Tie-Breaking",
        "When several wanted pieces have the same file priority and the same peer "
        "availability, SalixTorrent chooses between them randomly instead of always "
        "starting at the lowest piece number. This avoids deterministic piece-order "
        "clustering between clients while preserving rarest-first behaviour.",
    ),
    "REQUEST_SCHEDULER": (
        "Download Request Scheduler",
        "The block-level scheduler that turns rarest-first piece choices into bounded "
        "peer-wire REQUEST pipelines. SalixTorrent tracks exactly which peer owns each "
        "outstanding block, expires stalled ownership for reassignment, and activates "
        "bounded duplicate requests only during endgame. The scheduler is event-driven; "
        "it does not rescan the entire torrent on every peer message.",
    ),
    "REQUEST_PIPELINE": (
        "Request Pipelining",
        "Keeping several 16 KiB REQUEST messages outstanding to one unchoked peer so "
        "network round-trip latency does not leave the connection idle between blocks. "
        "SalixTorrent adapts the target depth from observed peer throughput and clamps "
        "it to a strict per-peer range, preventing an unresponsive peer from owning an "
        "unbounded amount of work.",
    ),
    "OUTSTANDING_REQUEST": (
        "Outstanding Block Request",
        "A block that SalixTorrent has assigned to a particular peer but has not yet "
        "received. Normal downloading gives a block one owner. During endgame a small "
        "number of peers may temporarily own the same final block; ownership is cleared "
        "when data arrives, a peer disconnects/chokes, or the request times out.",
    ),
    "REQUEST_TIMEOUT": (
        "Block Request Timeout",
        "A deadline applied after a REQUEST frame is actually transmitted. If the peer "
        "does not return that block before the deadline, SalixTorrent releases the peer's "
        "ownership and the scheduler can immediately assign the block elsewhere. A CANCEL "
        "is also sent to the stale peer when the connection is still alive.",
    ),
    "ENDGAME_MODE": (
        "Endgame Mode",
        "A completion-latency strategy used only when a small tail of wanted blocks "
        "remains. SalixTorrent first assigns every still-unrequested tail block normally. "
        "If all remaining blocks are already outstanding, the oldest lingering requests "
        "may be duplicated to a bounded number of other peers. The first valid PIECE wins "
        "and SalixTorrent sends CANCEL to the other owners.",
    ),
    "CANCEL_MESSAGE": (
        "Peer-wire CANCEL Message",
        "BitTorrent peer-wire message ID 8. A downloader sends CANCEL for a previously "
        "issued block REQUEST when that work is no longer needed, such as after another "
        "peer wins an endgame race or a request is reassigned. SalixTorrent both sends "
        "CANCEL and honours received CANCEL messages for pending uploads.",
    ),
    "DISK_IO_PIPELINE": (
        "Asynchronous Disk I/O Pipeline",
        "SalixTorrent writes newly verified pieces through one bounded write-behind queue "
        "instead of making a peer/network coroutine wait for synchronous filesystem I/O. "
        "The disk worker sleeps when idle and performs writes away from the event loop. "
        "Torrent completion is not announced until queued verified pieces are persisted.",
    ),
    "DISK_WRITE_BUFFER": (
        "Bounded Disk Write Buffer",
        "A byte-limited queue of verified pieces waiting to be written to storage. The "
        "default limit is 64 MiB (or one full piece when a torrent uses unusually larger "
        "pieces). The bound prevents a fast network from creating unlimited Python memory "
        "growth when storage is slower than the incoming transfer.",
    ),
    "DISK_BACKPRESSURE": (
        "Disk Backpressure",
        "When the bounded write buffer is full, the peer coroutine that completed another "
        "piece sleeps on an asynchronous condition until the disk worker frees capacity. "
        "Other peers, Dear PyGui, trackers and timers remain runnable. Backpressure is "
        "therefore flow control, not a blocking busy-wait or polling loop.",
    ),
    "RECENT_PIECE_CACHE": (
        "Recent-Piece Read Cache",
        "A bounded in-memory LRU cache for pieces that were just verified and written. It "
        "lets upload requests reuse hot piece data instead of immediately reading it back "
        "from disk. A verified piece that is still waiting in the write buffer is also "
        "served from its pinned memory copy, so write-behind never creates an upload gap.",
    ),
    "DISK_TELEMETRY": (
        "Disk I/O Telemetry",
        "Cached counters describing the disk pipeline: pending bytes/writes, write latency, "
        "completed/failed writes, backpressure events and time, plus recent-piece cache "
        "usage/hits/misses. Reading these values is O(1); SalixTorrent does not scan files "
        "or piece lists merely to update the display.",
    ),
    "PIECE_STATE": (
        "Piece State",
        "Verified means the piece hash passed. Downloading/Requested means work is "
        "in progress. Missing means it is still needed. No known source means it "
        "is needed but no currently connected peer advertises it.",
    ),
    "FILE_PIECES": (
        "File Piece Span",
        "The torrent-piece range that overlaps this file. BitTorrent piece "
        "boundaries do not have to align with file boundaries, so one piece can "
        "contain the end of one file and the beginning of the next.",
    ),
    "FILE_PRIORITY": (
        "Per-file Download Priority",
        "Controls which wanted files SalixTorrent tries to satisfy first. High "
        "outranks Normal, which outranks Low. Rarest-first selection is applied "
        "inside each priority level, so rarity never causes a Low-priority file to "
        "jump ahead of a wanted High-priority file. 'Don't Download' skips pieces "
        "used only by skipped files, while shared boundary pieces may still be needed.",
    ),
    "FILE_STATE": (
        "File State",
        "A summary derived from the verified and in-progress pieces that overlap "
        "this file. Because pieces can span file boundaries, the state reflects "
        "BitTorrent verification rather than only the physical file size on disk.",
    ),
    "FILE_PROGRESS": (
        "Verified File Progress",
        "The proportion of this file covered by SHA-1-verified torrent data. It is "
        "more meaningful than the file's current disk length because out-of-order "
        "downloads can create sparse or partially populated files.",
    ),
    "STORAGE_ROOT": (
        "Storage Root",
        "The directory or external source backing this torrent's payload. Normal "
        "downloads write under the configured download directory. External seeds "
        "are read-only and are served directly from their original location.",
    ),
    "PRIVATE_TORRENT": (
        "Private Torrent",
        "A torrent marked private restricts swarm discovery to its configured "
        "trackers. SalixTorrent disables DHT, PEX, Local Peer Discovery and public "
        "fallback trackers to avoid leaking the private swarm's info hash.",
    ),
    "FORCE_RECHECK": (
        "Force Recheck",
        "Discards SalixTorrent's fast-resume trust and SHA-1 verifies the existing "
        "payload again. It does not delete downloaded data. Use this if files were "
        "modified externally or you want to confirm on-disk data integrity.",
    ),
    "FAST_RESUME": (
        "Fast Resume",
        "Saved verification state that lets SalixTorrent trust previously checked "
        "pieces after restart when the payload fingerprint still matches. If the "
        "files appear to have changed, SalixTorrent falls back to a full recheck.",
    ),

    # ------------------------------------------------------------------
    # Transfer / queue terminology
    # ------------------------------------------------------------------
    "UI_TEXT_SIZE": (
        "Interface Text Size",
        "Controls the font size used throughout SalixTorrent, including menus, "
        "tables, tooltips, Preferences and Help Topics. Comfortable (15 px) is "
        "the default. Larger sizes are useful on high-density or physically "
        "smaller displays. SalixTorrent prefers a scalable system monospace font "
        "so text remains crisp instead of enlarging Dear PyGui's tiny bitmap font.",
    ),
    "TRANSFER_RATE": (
        "Transfer Rate Units",
        "Controls how live upload/download speeds are displayed. KB/s and MB/s "
        "show bytes per second; kbps and Mbps show bits per second. This changes "
        "presentation only and does not change limits or network speed.",
    ),
    "DOWNLOADED": (
        "Downloaded",
        "The verified payload data obtained for this torrent compared with its "
        "total size. For selective downloads, the completion state can also be "
        "based on only the files currently marked as wanted.",
    ),
    "REMAINING": (
        "Remaining",
        "The amount of currently wanted torrent data that is not yet verified. "
        "Changing file priorities or marking files 'Don't Download' can change "
        "the amount considered remaining.",
    ),
    "UPLOADED": (
        "Uploaded Total",
        "The persisted cumulative payload bytes SalixTorrent has served to other peers "
        "for this torrent. Uploading can happen while downloading as soon as verified "
        "pieces are available and continues naturally while seeding.",
    ),
    "UPLOADED_SESSION": (
        "Uploaded This Session",
        "Payload bytes served by this torrent since the current SalixTorrent process "
        "created/restored the torrent session. This counter is intentionally lightweight "
        "and is not persisted across application restarts.",
    ),
    "UPLOAD_REQUESTS": (
        "Upload Requests",
        "Counts BitTorrent REQUEST messages received and how many were successfully "
        "served with PIECE payload data. The counters update only when those network "
        "events happen; SalixTorrent does not scan peers to calculate them.",
    ),
    "LAST_UPLOAD": (
        "Last Upload",
        "How long ago this torrent last successfully transmitted a PIECE payload to a "
        "peer. An idle seed can correctly show no current upload speed even when this "
        "value proves that it served data recently.",
    ),
    "ETA": (
        "ETA - Estimated Time of Arrival",
        "An estimate of how long the currently wanted data will take to finish at "
        "the recent download rate. It changes naturally as peer availability and "
        "transfer speed change, and may be unavailable when speed is near zero.",
    ),
    "ELAPSED": (
        "Active Time",
        "How long this torrent has spent actively running in the current application "
        "session. Paused, stopped and queued time is excluded so the value is not "
        "mistaken for wall-clock age.",
    ),
    "SHARE_RATIO": (
        "Share Ratio",
        "Uploaded payload divided by downloaded payload. A ratio of 1.0 means "
        "roughly as much data has been uploaded as downloaded. A source-backed "
        "seed can upload even though SalixTorrent itself downloaded zero bytes.",
    ),
    "TRANSFER_LIMITS": (
        "Per-torrent Transfer Limits",
        "Optional speed ceilings that apply only to the selected torrent. A value "
        "of 0 means unlimited. These work alongside the application-wide global "
        "bandwidth limits in Preferences.",
    ),
    "GLOBAL_BANDWIDTH": (
        "Global Bandwidth Limit",
        "A shared aggregate ceiling across every active torrent. For example, a "
        "5 MB/s global download limit is shared by all downloads together; it is "
        "not 5 MB/s for each torrent. A value of 0 means unlimited.",
    ),
    "ACTIVE_DL_SLOTS": (
        "Active Download Slots",
        "The maximum number of torrents allowed to consume download slots at the "
        "same time. Extra started torrents wait in Queued state. Seeding torrents "
        "do not consume a download slot. 0 means unlimited.",
    ),
    "QUEUE_PRIORITY": (
        "Torrent Queue Priority",
        "High, Normal, or Low scheduling importance for a torrent. Priority is "
        "considered before queue position when a download slot becomes available. "
        "Changing display sorting does not change this scheduling priority.",
    ),
    "QUEUE_ORDER": (
        "Queue Order",
        "The persistent scheduling order controlled by Move Up / Move Down. Within "
        "the same priority level, torrents earlier in this order are considered "
        "first when a download slot becomes available.",
    ),
    "QUEUE_SORT": (
        "Display Sorting",
        "Click a column header to sort what you see. Sorting is visual only and "
        "does not alter the real Move Up / Move Down queue order or scheduler "
        "priority. Use Queue Order to return to scheduling order.",
    ),
    "QUEUE_SEARCH": (
        "Torrent Search Filter",
        "Filters the visible transfer list by torrent name. It does not stop, "
        "remove, reprioritize, or otherwise change hidden torrents.",
    ),
    "QUEUE_STATUS_FILTER": (
        "Status Filter",
        "Shows only torrents in the chosen lifecycle state (or Active group). This "
        "is a display filter only; hidden torrents keep running according to their "
        "normal queue and transfer state.",
    ),
    "TORRENT_STATUS": (
        "Torrent Status",
        "The selected torrent's current lifecycle state, such as Checking, Queued, "
        "Downloading, Paused, Seeding, Stopped, Completed, or Error.",
    ),
    "SESSION_STATE": (
        "Session State",
        "The current internal lifecycle state for this torrent. It controls which "
        "network, checking, disk, and peer-worker activities are currently active.",
    ),

    # ------------------------------------------------------------------
    # Networking / connectivity
    # ------------------------------------------------------------------
    "LISTEN_PORT": (
        "BitTorrent Listen Port",
        "The TCP port on which SalixTorrent accepts incoming peer connections. "
        "SalixTorrent can try nearby fallback ports if the preferred port is "
        "already in use. DHT may use the same number over UDP.",
    ),
    "LISTENER_ENDPOINT": (
        "Listener Endpoint",
        "The exact local IPv4 address and TCP port used by the selected torrent's "
        "incoming peer listener. 0.0.0.0 means the socket accepts connections on all "
        "local IPv4 interfaces; a specific address means network binding is active.",
    ),
    "INCOMING_CONNECTIONS": (
        "Incoming Connections",
        "Shows currently connected inbound peers and the number of successfully "
        "handshaken inbound peer connections observed during this application session. "
        "This is event-driven telemetry and does not require a polling loop.",
    ),
    "MAPPING_METHOD_STATUS": (
        "Port Mapping Method Status",
        "Shows UPnP and NAT-PMP separately so an Unmapped result explains which method "
        "failed, was disabled, or was not needed. UPnP is attempted first; NAT-PMP is "
        "the fallback when enabled.",
    ),
    "MAPPING_LEASE": (
        "Port Mapping Lease Refresh",
        "Automatic router mappings can have finite lifetimes. SalixTorrent keeps one "
        "low-frequency renewal timer for all active mapped listen ports and refreshes "
        "finite leases before expiry. If a UPnP gateway requires a permanent lease, "
        "SalixTorrent records that fact and does not schedule unnecessary renewals. It "
        "does not run a polling loop per torrent.",
    ),
    "MAPPING_DIAGNOSIS": (
        "Incoming Connectivity Diagnosis",
        "A cached explanation derived from the most recent UPnP/NAT-PMP attempt for the "
        "selected listen port. It distinguishes discovery failure, gateway refusal, port "
        "conflicts, malformed replies and other mapping stages. The diagnosis is updated "
        "when mapping work already occurs; SalixTorrent does not continuously poll the router.",
    ),
    "CONNECTIVITY_ACTION": (
        "Connectivity Suggested Action",
        "A practical next step based on the latest mapping result. Suggestions may include "
        "enabling UPnP/NAT-PMP, choosing another listen port, configuring a manual TCP port "
        "forward, checking the active VPN/default route, or investigating double NAT/CGNAT. "
        "The wording is guidance, not a claim that SalixTorrent can inspect router settings it cannot see.",
    ),
    "MANUAL_PORT_FORWARD": (
        "Manual Port Forward",
        "A router rule configured by the user that sends unsolicited Internet traffic on a "
        "chosen external port to SalixTorrent's local computer and listen port. TCP is the "
        "important mapping for incoming BitTorrent peers; forwarding the same UDP port can "
        "also improve DHT reachability. The computer should keep a stable LAN address/reservation.",
    ),
    "CGNAT": (
        "CGNAT - Carrier-Grade NAT",
        "NAT performed by the Internet provider upstream of your own router. With CGNAT, your "
        "router may not own a directly reachable public IPv4 address, so a local UPnP or manual "
        "port-forward rule may still be unreachable from the Internet. The shared IPv4 range "
        "100.64.0.0/10 is a strong indicator, but absence of that range does not rule CGNAT out.",
    ),
    "DOUBLE_NAT": (
        "Double NAT",
        "Two routing/NAT devices are in series, for example an ISP modem-router in front of a "
        "second home router. A port mapping on the inner router can succeed while the outer "
        "router still blocks unsolicited inbound traffic. Incoming Confirmed is stronger proof "
        "than a local mapping because it demonstrates the complete path in practice.",
    ),
    "EXTERNAL_ADDRESS_SCOPE": (
        "External Address Scope",
        "How SalixTorrent classifies an external IPv4 address reported by a mapping protocol. "
        "Public means globally routable according to Python's IP address rules. Private, "
        "Shared/CGNAT, or other non-global values suggest an upstream NAT may still exist; this "
        "is a diagnostic clue rather than definitive proof of the ISP's network design.",
    ),
    "MSE": (
        "MSE - Message Stream Encryption",
        "A legacy BitTorrent peer-transport encryption/obfuscation mechanism. "
        "SalixTorrent negotiates MSE with Diffie-Hellman and protects the peer-wire "
        "stream with RC4 after discarding the first 1024 keystream bytes. It can "
        "make simple protocol inspection harder, but it is not modern authenticated "
        "encryption, does not provide anonymity, and cannot guarantee that an ISP "
        "cannot identify or block BitTorrent traffic.",
    ),
    "PE": (
        "PE - Protocol Encryption",
        "A common BitTorrent name for the same family of encrypted/obfuscated peer "
        "transport negotiated by MSE. In SalixTorrent, an encrypted peer shown as "
        "MSE/RC4 is using this transport; tracker HTTPS is a separate security layer.",
    ),
    "RC4": (
        "RC4",
        "The legacy stream cipher used by BitTorrent MSE/PE. SalixTorrent uses the "
        "MSE RC4-drop1024 convention required for interoperability. RC4 should not "
        "be confused with modern authenticated encryption and is used here only "
        "because it is part of the legacy peer-encryption protocol.",
    ),
    "PEER_ENCRYPTION_POLICY": (
        "Peer Encryption Policy",
        "Disabled uses normal plaintext BitTorrent peer transport. Prefer Encryption "
        "tries MSE/RC4 first and, if the peer does not support it, opens a fresh "
        "plaintext TCP connection. Require Encryption accepts only MSE/RC4 peer "
        "transport and never falls back to plaintext.",
    ),
    "TRANSPORT_SECURITY": (
        "Transport Security",
        "Shows how a live BitTorrent peer connection is carrying the peer-wire "
        "stream. MSE/RC4 means peer transport encryption was negotiated; Plaintext "
        "means the normal unencrypted peer stream is in use. This describes the "
        "peer connection only, not tracker HTTPS, VPN tunnelling, or anonymity.",
    ),
    "NETWORK_BINDING": (
        "Network Interface / VPN Binding",
        "Pins SalixTorrent torrent networking to a selected local IPv4 or IPv6 address. "
        "Peer TCP connections and listeners, HTTP/UDP trackers, DHT and magnet metadata "
        "retrieval use that source family/address. BEP-14 LPD is IPv4-only and therefore "
        "stays disabled under an explicit IPv6 bind. Choosing Any interface permits dual-"
        "stack system routing where supported.",
    ),
    "INTERFACE_LOCK": (
        "Interface Lock / Kill Switch",
        "An active fail-closed guard for a specifically selected network address. "
        "Binding already chooses the source address; Interface Lock additionally "
        "monitors it. If that address disappears, SalixTorrent immediately moves the "
        "torrent to Error and closes its torrent networking instead of allowing a "
        "future connection to escape through another interface.",
    ),
    "VPN": (
        "VPN - Virtual Private Network",
        "A network path provided by VPN software, usually exposed to applications as "
        "a local interface/address. Selecting that address in Network Interface / VPN "
        "Binding pins SalixTorrent torrent traffic to it; Interface Lock adds active "
        "fail-closed monitoring if the address vanishes.",
    ),
    "IP_MASKING": (
        "Peer IP Masking",
        "A display-only privacy option that hides part of peer IP addresses in "
        "SalixTorrent's interface and peer table. It does not change the real socket "
        "address, hide you from the peer, tracker or ISP, or provide network anonymity. "
        "It is useful mainly when sharing screenshots or screen recordings.",
    ),
    "PORT_MAPPING": (
        "Incoming Port Mapping",
        "An IPv4 NAT-router rule forwarding an Internet-facing port to one of SalixTorrent's "
        "active listen sockets. UPnP/NAT-PMP are not required for globally routed IPv6; an "
        "IPv6 listener instead depends on the route and host/router firewall allowing inbound "
        "traffic. Multiple IPv4 listener mappings remain independent.",
    ),
    "LOCAL_ENDPOINT": (
        "Local Endpoint",
        "The local address and listen port used by SalixTorrent, for example "
        "192.168.x.x:6881 or [2001:db8::10]:6881. IPv4 private addresses are usually "
        "LAN-only; IPv6 scope depends on the selected address and network route.",
    ),
    "EXTERNAL_ENDPOINT": (
        "External Endpoint",
        "The public Internet address/port reported by the router mapping system. "
        "It may be unavailable when no UPnP/NAT-PMP mapping exists, when the router "
        "does not reveal it, or when the network is behind CGNAT.",
    ),
    "MAPPED_PROTOCOLS": (
        "Mapped Protocols",
        "TCP mapping is used for incoming BitTorrent peer connections. UDP mapping "
        "can help DHT reachability. A mapping only means the router accepted the "
        "rule; a real incoming peer is stronger proof that connectivity works.",
    ),
    "LAST_INCOMING": (
        "Last Incoming Peer",
        "The most recent remote BitTorrent peer observed connecting to SalixTorrent's "
        "listen socket. Seeing one is practical evidence that an inbound path is "
        "working from at least that peer's network location.",
    ),
    "MAX_PEERS": (
        "Default Maximum Peers",
        "The default connection target used for torrents added later. More peers "
        "can improve source diversity but also consume sockets, memory, CPU and "
        "bandwidth. Existing torrents keep the values already assigned to them.",
    ),

    # ------------------------------------------------------------------
    # Torrent creation / magnet links
    # ------------------------------------------------------------------
    "CREATE_TORRENT": (
        "Create Torrent",
        "Builds a standard BitTorrent v1 .torrent metainfo file from an existing "
        "file or folder. SalixTorrent hashes the source in the background; the "
        "payload itself is not copied merely to create the .torrent file.",
    ),
    "TORRENT_SOURCE_FILE": (
        "Single-file Torrent Source",
        "Select one existing file to publish as a single-file torrent. Archives, "
        "disk images, videos and ordinary files are all treated as normal payload "
        "bytes; SalixTorrent does not interpret their internal format.",
    ),
    "TORRENT_SOURCE_FOLDER": (
        "Multi-file Torrent Source",
        "Select a directory to create a multi-file torrent preserving its relative "
        "file tree. Directory symlinks are deliberately not followed so creation "
        "does not unexpectedly include data outside the selected folder.",
    ),
    "TORRENT_OUTPUT": (
        "Torrent Output File",
        "Where the generated .torrent metadata file will be saved. This file is "
        "small compared with the payload and can be shared independently; it "
        "contains metadata and piece hashes, not the original payload data.",
    ),
    "TRACKER_LIST": (
        "Tracker List",
        "Tracker announce URLs embedded in the .torrent metadata. Other clients can "
        "contact these servers to discover peers. One URL is entered per line; "
        "blank/comment lines are ignored and duplicates are removed.",
    ),
    "TORRENT_COMMENT": (
        "Torrent Comment",
        "Optional human-readable metadata stored in the .torrent file. It does not "
        "affect piece hashes, transfer behavior, or the torrent's info hash unless "
        "placed inside the info dictionary (SalixTorrent stores it outside).",
    ),
    "CREATION_PROGRESS": (
        "Torrent Creation Progress",
        "Shows hashing progress while SalixTorrent reads the source and generates "
        "SHA-1 piece hashes. Creation runs in a worker thread so the user interface "
        "remains responsive. Cancelling does not replace the destination with a "
        "half-written torrent.",
    ),
    "START_SEEDING": (
        "Start Seeding Created Torrent",
        "Adds the newly created torrent to Active Transfers and seeds directly from "
        "the original source path after verifying it. SalixTorrent does not make an "
        "unnecessary duplicate copy inside the downloads directory.",
    ),
    "MAGNET_LINK": (
        "Magnet Link",
        "A compact URI that identifies a torrent by info hash without carrying the "
        "full .torrent metadata. SalixTorrent discovers peers, retrieves metadata "
        "with BEP-9, verifies the hash, then turns it into an ordinary torrent "
        "session.",
    ),

    # ------------------------------------------------------------------
    # Storage / metadata
    # ------------------------------------------------------------------
    "STORAGE_MODE": (
        "Storage Mode",
        "Downloads are written to SalixTorrent-managed storage. 'External Seed' "
        "means SalixTorrent is reading an already-complete original file/folder in "
        "place and treats that source as read-only.",
    ),
    "STORAGE_PATH": (
        "Storage Path",
        "The filesystem path containing this torrent's payload data. Opening the "
        "folder does not alter transfer state; changing or deleting data externally "
        "can invalidate fast-resume information and require a recheck.",
    ),
    "TORRENT_PATH": (
        ".torrent Metadata Path",
        "The local .torrent metainfo file used to reconstruct this session. "
        "SalixTorrent also keeps private cached metadata so restored sessions are "
        "not dependent on the originally opened .torrent file remaining in place.",
    ),
    "CREATED_BY": (
        "Created By",
        "An optional metainfo field identifying the application that created the "
        ".torrent. It is descriptive only and does not prove who authored or owns "
        "the payload.",
    ),
    "CREATION_DATE": (
        "Torrent Creation Date",
        "An optional Unix timestamp stored in the .torrent metadata. It describes "
        "when the torrent file was created, not necessarily when the underlying "
        "payload files themselves were created.",
    ),
    "FILE_COUNT": (
        "Torrent Files",
        "The number of payload files described by the torrent. A single-file "
        "torrent reports one file; a multi-file torrent preserves a relative "
        "directory tree of many payload files.",
    ),

    # ------------------------------------------------------------------
    # Preferences / desktop behavior
    # ------------------------------------------------------------------
    "DEFAULT_DOWNLOAD_DIR": (
        "Default Download Directory",
        "The storage root assigned to newly added downloading torrents. Existing "
        "torrents remember their own storage paths, so changing this preference "
        "does not silently move data that is already in progress.",
    ),
    "AUTO_RESUME": (
        "Restore Active Transfers",
        "When enabled, torrents that were actively downloading or seeding at clean "
        "shutdown are scheduled to become active again on the next launch. Paused "
        "and stopped torrents keep their intentional inactive state.",
    ),
    "NEW_TORRENT_LIMITS": (
        "New Torrent Default Limits",
        "Per-torrent upload/download limits copied onto torrents added in the "
        "future. Changing these defaults does not overwrite custom limits already "
        "stored on existing torrents.",
    ),
    "COMPLETION_NOTICE": (
        "In-app Completion Notice",
        "Shows a small SalixTorrent window when a download reaches completion. It "
        "can provide a quick Open Folder action without relying on operating-system "
        "notification services.",
    ),
    "NATIVE_NOTIFICATION": (
        "Native Windows Completion Notification",
        "Uses the Windows shell/tray notification backend to announce completed "
        "downloads outside the main SalixTorrent window. This is desktop integration "
        "only and has no effect on torrent activity.",
    ),
    "SYSTEM_TRAY": (
        "System Tray Integration",
        "Creates a Windows notification-area icon with quick SalixTorrent controls. "
        "The Python-development build may behave differently from the eventual "
        "packaged executable, so tray behavior is considered desktop integration.",
    ),
    "MINIMIZE_TRAY": (
        "Minimize to System Tray",
        "When supported, minimizing hides the main window while transfers continue "
        "in the background and the tray icon remains available for reopening it.",
    ),
    "SETTINGS_FILE": (
        "Settings File",
        "The JSON file containing persistent application preferences. It is kept "
        "in SalixTorrent's application-data directory rather than mixed with "
        "torrent payloads.",
    ),

    # ------------------------------------------------------------------
    # Commands / actions
    # ------------------------------------------------------------------
    "OPEN_TORRENT": (
        "Open Torrent",
        "Choose a .torrent metainfo file, add it to SalixTorrent, select it, and "
        "start its normal checking/download workflow. The .torrent contains "
        "metadata; the payload is downloaded separately into its storage path.",
    ),
    "OPEN_MAGNET": (
        "Open Magnet",
        "Paste a v1 magnet URI. SalixTorrent first resolves the missing torrent "
        "metadata through peers, then creates a normal persistent torrent session "
        "and begins the usual checking/download process.",
    ),
    "START_RESUME": (
        "Start / Resume Torrent",
        "Starts a stopped/completed/error torrent or resumes a paused one. If the "
        "download-slot limit is already full, the torrent can wait in Queued state "
        "until a slot becomes available.",
    ),
    "PAUSE_TORRENT": (
        "Pause Torrent",
        "Temporarily suspends active transfer work while keeping the torrent loaded "
        "and preserving its intended resumable state. Use Stop when you want it to "
        "remain inactive until explicitly started again.",
    ),
    "STOP_TORRENT": (
        "Stop Torrent",
        "Stops active transfer/checking work and records the torrent as intentionally "
        "stopped. Downloaded payload and verified resume state remain on disk.",
    ),
    "RETRY_TORRENT": (
        "Retry Torrent",
        "Attempts to restart a torrent after an error or recoverable problem. The "
        "original human-readable error remains useful for understanding what failed "
        "before retrying.",
    ),
    "UPDATE_TRACKERS": (
        "Update / Announce Trackers",
        "Requests an immediate tracker announce for the selected active torrent "
        "instead of waiting for the next normal announce interval. Newly returned "
        "peer addresses are fed into the running swarm.",
    ),
    "OPEN_FOLDER": (
        "Open Download Folder",
        "Opens the filesystem location containing this torrent's payload. This does "
        "not pause or modify the torrent. Editing/deleting payload files externally "
        "can cause a later recheck to mark pieces missing or corrupt.",
    ),
    "COPY_INFO_HASH": (
        "Copy Info Hash",
        "Copies the torrent's v1 SHA-1 info hash to the clipboard. This identifier "
        "names the swarm but does not itself contain the full torrent metadata.",
    ),
    "COPY_MAGNET": (
        "Copy Magnet Link",
        "Builds and copies a standard v1 magnet URI containing the torrent's btih "
        "info hash plus useful display-name/tracker parameters where available.",
    ),
    "PROPERTIES": (
        "Torrent Properties",
        "Opens a consolidated readout of torrent metadata, paths, trackers, transfer "
        "statistics, priority, and limits for the selected torrent.",
    ),
    "REMOVE_TORRENT": (
        "Remove Torrent",
        "Removes the transfer from SalixTorrent's queue/session state. The safe "
        "remove option leaves payload data on disk; the separate Delete Data option "
        "also removes SalixTorrent-managed payload/resume data after confirmation.",
    ),
    "DELETE_DATA": (
        "Remove + Delete Data",
        "A destructive cleanup action. It removes the torrent from SalixTorrent and "
        "deletes payload data managed under the torrent's download storage, plus "
        "resume metadata. External seed sources and the original opened .torrent "
        "file are deliberately protected.",
    ),

    # ------------------------------------------------------------------
    # Speed graph / statistics
    # ------------------------------------------------------------------
    "SPEED_HISTORY": (
        "Rolling Transfer History",
        "A short in-memory history of the selected torrent's measured download and "
        "upload rates. It is sampled about every half second and intentionally "
        "resets when SalixTorrent restarts rather than bloating session storage.",
    ),
    "SPEED_WINDOW": (
        "Graph Time Window",
        "Chooses how much recent transfer history is visible on the Speed graph. "
        "Changing the window affects only the visualization; it does not change "
        "sampling, bandwidth limits, or transfer behavior.",
    ),
    "AVERAGE_PEAK": (
        "Average and Peak Transfer Rates",
        "Average summarizes the recent retained speed samples; Peak is the highest "
        "sample in that retained history. These are session telemetry values, not "
        "advertised ISP line speed or theoretical network capacity.",
    ),

    # ------------------------------------------------------------------
    # Application navigation / support
    # ------------------------------------------------------------------
    "ACTIVE_TRANSFERS_VIEW": (
        "Active Transfers",
        "The main torrent queue and selected-torrent inspector. Transfers continue "
        "running when you switch to Create Torrent or Preferences; changing views "
        "does not pause network activity.",
    ),
    "PREFERENCES_VIEW": (
        "Preferences",
        "Persistent SalixTorrent settings for storage defaults, peer encryption, "
        "network-interface/VPN binding, Interface Lock, peer-IP display masking, "
        "discovery, queue behavior, bandwidth, transfer-rate display and desktop integration.",
    ),
    "DIAGNOSTICS": (
        "Diagnostics",
        "A support/development snapshot containing version, runtime, selected "
        "torrent, discovery settings, connectivity state and application-data file "
        "locations. It is designed to make troubleshooting reproducible.",
    ),
}


def help_text(term: str) -> str:
    entry = HELP_TERMS.get(str(term or "").upper())
    if not entry:
        return ""
    title, body = entry
    return f"{title}\n\n{body}"


def contextual_text(
    title: str,
    body: str,
    facts: Optional[Iterable[str]] = None,
    footer: str = "",
) -> str:
    """Build a consistent long-form tooltip with optional live facts."""
    parts = [str(title).strip(), "", str(body).strip()]
    clean_facts = [str(x).strip() for x in (facts or ()) if str(x).strip()]
    if clean_facts:
        parts.extend(["", *clean_facts])
    if str(footer or "").strip():
        parts.extend(["", str(footer).strip()])
    return "\n".join(parts)


def add_text_tooltip(item, text: str, wrap: int = 450):
    """Attach arbitrary explanatory text to a Dear PyGui item safely.

    Some Dear PyGui item types (notably table columns and a few container-like
    items) cannot own a tooltip.  Using the ``with dpg.tooltip(...)`` context
    manager for one of those items can raise during ``__enter__`` after Dear
    PyGui has already touched its internal container stack.  Catching that
    exception is therefore not enough: later widgets may be parented to the
    wrong container.

    Create the tooltip and its text with explicit parent IDs instead.  Failed
    tooltip attachment then remains non-fatal *and* cannot disturb the active
    layout/container stack.  Tooltips are help-only, so unsupported targets are
    intentionally skipped.
    """
    if not item or not str(text or "").strip():
        return None

    tooltip_id = None
    try:
        tooltip_id = dpg.add_tooltip(parent=item)
        return dpg.add_text(str(text), parent=tooltip_id, wrap=wrap)
    except Exception:
        # If the tooltip container itself was accepted but adding its content
        # failed, clean it up so no empty/orphan help item is left behind.
        try:
            if tooltip_id and dpg.does_item_exist(tooltip_id):
                dpg.delete_item(tooltip_id)
        except Exception:
            pass
        return None


def add_help_tooltip(item, term: str, wrap: int = 450):
    """Attach a consistent glossary tooltip to an existing DPG item."""
    return add_text_tooltip(item, help_text(term), wrap=wrap)


def add_context_tooltip(
    item,
    title: str,
    body: str,
    facts: Optional[Iterable[str]] = None,
    footer: str = "",
    wrap: int = 470,
):
    """Attach an explanatory tooltip containing optional live/current values."""
    return add_text_tooltip(
        item,
        contextual_text(title, body, facts=facts, footer=footer),
        wrap=wrap,
    )
