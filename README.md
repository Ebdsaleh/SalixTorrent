# SalixTorrent (Salix_T) v0.2.0

SalixTorrent is a desktop BitTorrent v1 client written in Python with a custom asynchronous protocol engine and a Dear PyGui interface. The project aims to expose what a torrent client is doing rather than hiding the protocol behind a single progress bar: transfers, peers, pieces, files, trackers, discovery sources, bandwidth history, connectivity, and protocol terminology are all inspectable from the application.

> **Release status:** v0.2.0 is a development release. Core downloading, concurrent uploading, seeding, torrent creation, magnet metadata retrieval, queue management, and the desktop UI are functional. Packaging into a standalone executable is intentionally deferred until the feature set is considered complete.

## Highlights

- Load `.torrent` files or BitTorrent v1 magnet links.
- BEP-9 magnet metadata retrieval with info-hash verification and local metadata caching.
- HTTP/HTTPS and UDP tracker support, plus DHT, PEX, and Local Peer Discovery for public torrents.
- Private-torrent isolation: no public fallback trackers, DHT, PEX, or LPD leakage.
- Concurrent downloading and uploading over bidirectional peer connections.
- Incoming peer listener, seeding, and external-source seeding.
- Fast resume with SHA-1 recheck fallback.
- Single-file and multi-file torrents with selective file downloading and file priorities.
- Torrent queue priorities, move up/down ordering, and configurable active download slots.
- Per-torrent and true global upload/download rate limits.
- Live General, Peers, Pieces, Files, Sources, and Speed views.
- Compact piece map, peer client identification, source diagnostics, and rolling speed history.
- Incremental piece-availability accounting with file-priority-preserving rarest-first scheduling and randomized equal-rarity tie-breaking.
- Torrent creation from a file/archive or directory.
- Persistent session restoration and application preferences.
- UPnP / NAT-PMP mapping for each active torrent listener, with per-listener incoming-connectivity reporting, structured failure diagnosis, and automatic lease renewal.
- Event-driven seeding telemetry: uploaded total/session bytes, upload requests served/received, last upload, incoming peers, and exact listener endpoint.
- MSE/PE peer transport with Disabled, Prefer Encryption (default), and Require Encryption policies.
- Network-interface/VPN binding across peer, tracker, DHT, LPD, listener, and magnet traffic, with optional fail-closed Interface Lock.
- Live transport-security telemetry and optional display-only peer IP masking (off by default).
- Traditional File/Edit/View/Transfers/Tools/Help menu bar and keyboard shortcuts.
- Comprehensive hover tooltips plus searchable Help Topics and an A-Z glossary.
- Context menus for lifecycle actions, priorities, transfer-rate display units, recheck, tracker refresh, properties, and removal.

## Requirements

- Python 3.13 is the primary development/runtime version for v0.2.0.
- Dear PyGui 2.3.1 or newer in the 2.x series.
- aiohttp 3.11 or newer in the 3.x series.
- Tk support in the Python installation for native file/folder dialogs.

Install the Python dependencies with:

```bash
python -m pip install -r requirements.txt
```

## Run

Desktop interface:

```bash
python main.py
```

Open a `.torrent` at launch:

```bash
python main.py path/to/file.torrent
```

Open a BitTorrent v1 magnet at launch:

```bash
python main.py "magnet:?xt=urn:btih:..."
```

Show the release version:

```bash
python main.py --version
```

A headless CLI path is also available for `.torrent` files:

```bash
python main.py --cli path/to/file.torrent
```

## Interface

The Active Transfers view contains a persistent queue and a selected-torrent inspector:

```text
General | Peers | Pieces | Files | Sources | Speed
```

- **General** — transfer totals, ETA, ratio, swarm statistics, metadata, storage, discovery, connectivity, and limits.
- **Peers** — live peer address/client/source/direction/piece availability/rates/state/flags.
- **Pieces** — verification state, active requests, availability, and a compact graphical piece map.
- **Files** — per-file verified progress, piece span, state, and priority/selective-download controls.
- **Sources** — trackers, DHT, PEX, and LPD with live status and diagnostic telemetry; neutral Pending, amber Timeout warnings, and red source errors are reported separately.
- **Speed** — rolling upload/download history plus per-torrent and global limit references.

Technical labels and values throughout the interface have contextual hover help. `Help -> Help Topics...` opens the built-in searchable manual, while `Help -> Glossary A-Z...` jumps directly to the technical glossary.

## Peer discovery

For public torrents SalixTorrent can discover peers through:

- HTTP/HTTPS trackers
- UDP trackers (BEP-15)
- Distributed Hash Table / DHT (BEP-5)
- Peer Exchange / PEX (BEP-10/BEP-11)
- Local Peer Discovery / LPD (BEP-14)

Private torrents deliberately remain tracker-controlled. SalixTorrent disables DHT, PEX, LPD, and public fallback tracker injection when the torrent metadata declares `private = 1`.

## Downloads, uploads, and seeding

BitTorrent peer connections are bidirectional. While a torrent is still downloading, SalixTorrent can upload pieces that have already passed SHA-1 verification. Unverified or incomplete pieces are never served.

Download scheduling maintains piece availability incrementally from peer `BITFIELD`, `HAVE`, and disconnect events. File priority remains the primary rule (High, then Normal, then Low); within one priority level SalixTorrent requests the rarest piece available from that peer, with randomized tie-breaking between equally rare pieces. This avoids a torrent-wide availability rebuild or full sequential piece scan for every block request.

Block scheduling keeps explicit peer ownership for every outstanding request. Each unchoked peer uses a bounded adaptive request pipeline (8-64 blocks, based on observed throughput) so round-trip latency does not leave the connection idle, while a 30-second sent-request timeout releases stalled work for immediate reassignment. A choke or disconnect releases that peer's owned blocks directly through a per-peer reverse index rather than scanning the torrent.

When 32 or fewer wanted blocks remain, SalixTorrent enters bounded Endgame Mode. Unrequested blocks are still assigned first; only after the tail is fully outstanding may an older lingering block be duplicated to another peer, with at most three owners per block. The first valid `PIECE` wins and SalixTorrent sends peer-wire `CANCEL` messages to the other owners. Received `CANCEL` messages are honoured for pending uploads as well.

Verified pieces use a bounded asynchronous disk pipeline. Live downloads reserve byte capacity in a 64 MiB write-behind buffer and one sleeping writer performs filesystem writes away from the asyncio peer/UI hot path. If storage cannot keep up, the peer coroutine completing the next piece waits asynchronously for capacity; the rest of networking and Dear PyGui remain runnable. Torrent completion is not announced until all queued verified pieces have been persisted.

A separate bounded 32 MiB recent-piece LRU cache keeps freshly written data hot for seeding, avoiding immediate read-after-write disk traffic. Verified pieces still waiting in the write-behind buffer are pinned in memory and can also be served to peers immediately. Both buffers are strictly bounded, and disk telemetry reports pending bytes/writes, write latency, backpressure, cache hits/misses, and failures without scanning the payload.

When all wanted pieces are complete, the session can transition to seeding. Torrents created from local files/directories can also seed directly from the original source in read-only external-seed mode.

The General view distinguishes the persisted **Uploaded Total** from **Uploaded This Session** and shows received/served peer `REQUEST` counts, the age of the last successful `PIECE` upload, and active/this-session incoming peers. These counters are updated directly at the corresponding network events; SalixTorrent does not add a peer-scanning loop merely to produce telemetry.

## Queue and bandwidth management

Torrent scheduling uses two separate concepts:

1. **Priority:** High, Normal, or Low.
2. **Queue position:** controlled with Move Up / Move Down.

The configurable Active Download Slots value limits concurrent downloads without counting seed-only sessions. A value of `0` means unlimited.

Bandwidth can be controlled at two levels:

- per-torrent upload/download limits;
- global aggregate upload/download limits shared by all active torrents.

Transfer-rate presentation can be switched between Automatic, KB/s, MB/s, kbps, and Mbps without changing the underlying limiter values.

## Storage and state

On Windows, persistent application state is stored under:

```text
%LOCALAPPDATA%\SalixTorrent\
```

This includes settings, session state, cached magnet metadata, and the UI error log. Download payloads use the configured download directory.

Fast-resume information trusts previously verified pieces only while the relevant file metadata still matches. A Force Recheck discards that trust and verifies the payload again from disk without deleting it.

Fast-resume metadata records only pieces that have actually reached storage. A piece may be SHA-1 verified and temporarily uploadable from the bounded write-behind buffer before it is marked persisted; this prevents a crash or disk failure from making resume state claim that buffered-only data is safely on disk.

## Connectivity, transport security and network binding

SalixTorrent listens for incoming BitTorrent TCP connections and attempts automatic router mapping using UPnP, with NAT-PMP as a fallback where available.

Peer transport has three policies:

- **Disabled** - normal plaintext BitTorrent peer wire only;
- **Prefer Encryption** - the default; tries MSE/RC4 first and opens a fresh plaintext TCP connection only if the peer does not support MSE;
- **Require Encryption** - accepts MSE/RC4 peer transport only and never falls back to plaintext.

MSE/PE is the legacy interoperable BitTorrent peer-encryption mechanism. It obscures/encrypts the peer stream for compatible peers, but it is not modern authenticated encryption, does not hide IP addresses, and should not be treated as a guarantee that an ISP cannot classify or block BitTorrent traffic. SalixTorrent implements the MSE-required RC4 stream internally, so no additional cryptography package is required.

Preferences can also bind torrent networking to a specific local IPv4 address, including an address owned by a VPN interface. Peer TCP connections, the incoming listener, HTTP/UDP trackers, DHT, LPD, and magnet metadata retrieval all use the selected source address. **Interface Lock** is an additional fail-closed guard: if that selected address disappears, the torrent enters Error and its torrent networking is closed immediately instead of allowing later activity to use another path.

Peer IP masking is a display-only option intended for screenshots/recordings. It is **off by default** and does not change real socket endpoints or provide anonymity.

`Mapped` means the router accepted a mapping request. `Incoming Confirmed` is stronger: SalixTorrent has actually observed a remote peer complete an incoming BitTorrent handshake on that listener. General, Preferences, and Diagnostics report UPnP and NAT-PMP separately, including the failing stage and protocol fault/result code when available, plus a cached diagnosis and suggested next action. Failure to obtain automatic mapping is a notice rather than a fatal transfer error; outbound connections and other discovery mechanisms can continue normally.

When a mapping protocol reports an external IPv4 address, SalixTorrent classifies it conservatively as Public, Private, Shared/CGNAT, or another non-global scope. A non-public address is treated as a clue that double NAT or provider-side CGNAT may exist, not as definitive proof. The built-in Help/Glossary explains automatic mapping, manual TCP/UDP forwarding, double NAT, CGNAT, and why `Incoming Confirmed` is the strongest practical evidence available to the client.

Router mapping leases are finite on many devices. SalixTorrent renews successful mappings before expiry with one shared sleeping timer covering all active listen ports. There is no busy connectivity poll and no per-torrent renewal loop. If a renewal attempt fails while an earlier mapping may still be valid, SalixTorrent retains the previous mapping and schedules a later retry rather than tearing the rule down first.

## Create Torrent

The Create Torrent view can build a BitTorrent v1 `.torrent` from:

- a single file;
- an archive such as ZIP/7z (treated as an ordinary file payload);
- a directory tree.

Users can choose piece size, trackers, privacy, comment, output path, and optionally start seeding the original source after creation.

## Tests

The project currently includes a small foundation suite and focused regression coverage. Local/network integration scripts may require a `test.torrent` and active peers.

```bash
python foundation_test.py
python test_transport_security.py
```

The release-critical regression coverage includes MSE/RC4 interoperability, source binding, encryption fallback rules, multi-torrent port mappings, finite/permanent mapping-lease handling, structured UPnP/NAT-PMP diagnostics, source-severity accounting, Interface Lock, and real inbound seeding uploads with telemetry counters.

## Current scope

v0.2.0 focuses on BitTorrent v1. BitTorrent v2 / `btmh` support is not implemented yet. Standalone executable packaging, file associations, magnet URI registration, and installer work are intentionally planned for a later feature-complete release pass.

## Project structure

```text
SalixTorrent/
├── main.py
├── requirements.txt
├── foundation_test.py
├── app/
│   ├── version.py
│   ├── engine/
│   │   ├── desktop_integration.py
│   │   ├── gui_engine.py
│   │   ├── master_viewport.py
│   │   └── scene_manager.py
│   ├── logic/
│   │   ├── bencode.py
│   │   ├── connectivity.py
│   │   ├── dht.py
│   │   ├── local_peer_discovery.py
│   │   ├── magnet.py
│   │   ├── mse.py
│   │   ├── network_binding.py
│   │   ├── peer.py
│   │   ├── piece_manager.py
│   │   ├── session.py
│   │   ├── torrent_creator.py
│   │   ├── torrent_file.py
│   │   ├── torrent_manager.py
│   │   └── tracker.py
│   └── views/
│       ├── application_menu.py
│       ├── create_torrent_view.py
│       ├── download_view.py
│       ├── file_view.py
│       ├── help_terms.py
│       ├── help_topics_view.py
│       ├── peer_view.py
│       ├── piece_view.py
│       ├── settings_view.py
│       ├── source_view.py
│       ├── speed_view.py
│       └── transfer_rate.py
└── README.md
```
