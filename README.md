# SalixTorrent (Salix_T) v0.2.0

SalixTorrent is a desktop BitTorrent v1 client written in Python with a custom asynchronous protocol engine and a Dear PyGui interface. The project aims to expose what a torrent client is doing rather than hiding the protocol behind a single progress bar: transfers, peers, pieces, files, trackers, discovery sources, bandwidth history, connectivity, and protocol terminology are all inspectable from the application.

> **Release status:** v0.2.0 is a development release. Core downloading, concurrent uploading, seeding, torrent creation, magnet metadata retrieval, queue management, and the desktop UI are functional. Packaging into a standalone executable is intentionally deferred until the feature set is considered complete.

## Highlights

- Load `.torrent` files or BitTorrent v1 magnet links.
- BEP-9 magnet metadata retrieval with info-hash verification and local metadata caching.
- HTTP/HTTPS and UDP tracker announce support plus batched tracker scrape statistics, DHT, PEX, and Local Peer Discovery for public torrents.
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
- Comprehensive hover tooltips plus a semantic, responsive offline Documentation subsystem powering Help Topics and the A-Z glossary.
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

- **General** — transfer totals, ETA, ratio, announce-derived swarm counts, freshest tracker scrape S/L/C statistics, metadata, storage, discovery, connectivity, and limits.
- **Peers** — live peer address/client/source/direction/piece availability/rates/state/flags.
- **Pieces** — verification state, active requests, availability, and a compact graphical piece map.
- **Files** — per-file verified progress, piece span, state, and priority/selective-download controls.
- **Sources** — trackers, DHT, PEX, and LPD with live status and diagnostic telemetry; tracker announce health remains separate from scrape S/L/C statistics, while neutral Pending, amber Timeout warnings, and red source errors are reported separately.
- **Speed** — rolling upload/download history plus per-torrent and global limit references.

Technical labels and values throughout the interface have contextual hover help. `Help -> Help Topics...` opens the built-in searchable manual, while `Help -> Glossary A-Z...` jumps directly to the technical glossary.

### Documentation subsystem

Help and Glossary content is rendered through a reusable semantic documentation layer instead of assigning presentation directly inside each topic. Content describes page titles, leads, sections, paragraphs, links, callouts, code and media; the Dear PyGui renderer supplies semantic fonts, colors, spacing, parent-relative alignment and responsive reflow. The same content model can therefore be extracted later without carrying torrent-specific layout code with it.

Documentation layout is resolved through a deterministic framework property cascade rather than one hard-coded rectangle. Every property starts from a safe framework default; a sparse active documentation-layout theme may override only the values it defines; and an individual `DocPage` may explicitly override either layer through `DocLayout`. Invalid higher-precedence values fall back to the next valid layer independently, while valid values that merely exceed the current pane are constrained at runtime without losing their configured intent. SalixTorrent's active theme widens the framework's conservative readable-width default so the manual uses more of a desktop-sized Help pane without stretching indefinitely on very wide monitors.

Outer document margins and inner content padding are separate policies. Document, page-title and media alignment are separate too, so a page can tune its left/right inset while its title remains mathematically centered inside the resulting content bounds. The cascade uses an explicit `UNSET` sentinel for inheritance instead of overloading `None`; this leaves values such as `maximum_width=None` available as meaningful explicit configuration. Resolved layouts retain Default/Theme/Instance provenance and rejected candidates, allowing programmatic theme editing and future visual layout inspectors to explain exactly where an effective property came from.

`Preferences -> Desktop -> Documentation scale` independently controls Help/Glossary presentation at 90%, 100%, 115% or 130%. Semantic roles scale together, preserving the visual hierarchy between page titles, section headings, body text, captions and code. The normal Interface Text Size setting still controls the rest of SalixTorrent. Role fonts are pre-registered before Dear PyGui setup so changing document scale does not rebuild the font atlas during an active session.

The model already supports semantic icons/callouts and media blocks. Static images can be loaded lazily into Dear PyGui textures, centered within the current document bounds and scaled down while preserving aspect ratio. Animation/video are represented as media types so a future timed decoder/player backend can be added without rewriting documentation content; until such a backend exists they intentionally degrade to an explanatory text fallback.

### Responsive desktop layout

SalixTorrent treats Dear PyGui as the rendering engine rather than accepting fixed launch-time geometry. Main scenes fill the available client area, data tables/plots and editors grow into useful space, split panes recompute their proportions on resize, and data-heavy dialogs keep their action rows attached to the bottom of the resizable content. Text wrapping follows the rendered pane width instead of retaining one hard-coded measure.

The layout system is event-driven: viewport and item resize handlers feed one reusable `ResponsiveLayout` service, which memoizes geometry writes and performs no per-frame layout polling. Small destructive confirmations and transient notices intentionally remain compact/fixed-size, matching normal desktop-application conventions rather than stretching controls that gain no usability from extra space.

## Peer discovery

For public torrents SalixTorrent can discover peers through:

- HTTP/HTTPS trackers
- UDP trackers (BEP-15)
- Distributed Hash Table / DHT (BEP-5)
- Peer Exchange / PEX (BEP-10/BEP-11)
- Local Peer Discovery / LPD (BEP-14)

Private torrents deliberately remain tracker-controlled. SalixTorrent disables DHT, PEX, LPD, and public fallback tracker injection when the torrent metadata declares `private = 1`.

### Tracker scrape statistics

Phase 6 adds tracker scrape as a statistics path that is deliberately separate from announce. HTTP/HTTPS trackers use the BEP-48 convention: SalixTorrent derives a scrape endpoint only when the announce URL contains `announce` in its path and sends repeated `info_hash` parameters. UDP trackers use BEP-15 action `2`. Scrape does not announce SalixTorrent as a peer and does not change participation in the swarm.

The scrape values are displayed as **S / L / C**:

- **S** — current complete peers (seeds) reported by that tracker;
- **L** — current incomplete peers (leechers) reported by that tracker;
- **C** — that tracker's cumulative completed-download counter.

These are tracker-local statistics, not mathematically global swarm totals. Different trackers can maintain different peer populations and historical completion counts, so SalixTorrent keeps each tracker's scrape result visible in Sources and labels the freshest individual tracker scrape in General rather than summing incompatible populations.

Scraping is application-wide and batched. Active torrents that share the same tracker are grouped into one bounded HTTP request or one/more bounded UDP scrape datagrams. UDP batches reuse a single tracker connection ID, while HTTP batches reuse one client session. A single timer-driven coordinator refreshes cached scrape state; opening or repainting a Dear PyGui view never initiates tracker traffic.

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

SalixTorrent is dual-stack. With **Any interface** selected it opens explicit IPv4 and IPv6 BitTorrent TCP listeners on the same numeric port where the platform supports both families. A specific IPv4 or IPv6 bind constrains outgoing peers, listeners, trackers and DHT to that family instead of silently escaping through the other path.

IPv6 peer discovery is supported end-to-end: HTTP trackers consume BEP-7 `peers6`, UDP tracker announces use the BEP-15 18-byte IPv6 response stride, BEP-11 PEX sends/receives `added6`/`dropped6`, and DHT participates in the IPv4 BEP-5 and IPv6 BEP-32 address spaces. Under Any interface, dual-stack tracker announces run concurrently per available family with a stable BEP-7 tracker key; this avoids serial latency while allowing trackers to observe the usable IPv4 and IPv6 sources. BEP-32 DHT uses a concrete route-selected IPv6 source when one exists rather than a wildcard `::` source.

For IPv4 NAT, SalixTorrent attempts automatic router mapping using UPnP, with NAT-PMP as a fallback where available. A specifically bound IPv6 listener is reported as **IPv6 Direct**: UPnP/NAT-PMP are IPv4 NAT mechanisms and are deliberately not invoked through some unrelated IPv4 interface. IPv6 incoming reachability instead depends on the route and host/router firewall.

Peer transport has three policies:

- **Disabled** - normal plaintext BitTorrent peer wire only;
- **Prefer Encryption** - the default; tries MSE/RC4 first and opens a fresh plaintext TCP connection only if the peer does not support MSE;
- **Require Encryption** - accepts MSE/RC4 peer transport only and never falls back to plaintext.

MSE/PE is the legacy interoperable BitTorrent peer-encryption mechanism. It obscures/encrypts the peer stream for compatible peers, but it is not modern authenticated encryption, does not hide IP addresses, and should not be treated as a guarantee that an ISP cannot classify or block BitTorrent traffic. SalixTorrent implements the MSE-required RC4 stream internally, so no additional cryptography package is required.

Preferences can also bind torrent networking to a specific local IPv4 or IPv6 address, including an address owned by a VPN interface. Peer TCP connections, listeners, HTTP/UDP trackers, DHT, and magnet metadata retrieval use the selected source address/family. **Interface Lock** is an additional fail-closed guard: if that selected address disappears, the torrent enters Error and its torrent networking is closed immediately instead of allowing later activity to use another path. BEP-14 Local Peer Discovery is IPv4 multicast, so an explicit IPv6-only bind disables LPD rather than leaking discovery through another IPv4 route.

Peer IP masking is a display-only option intended for screenshots/recordings. It is **off by default** and does not change real socket endpoints or provide anonymity.

`Mapped` means the router accepted a mapping request. `Incoming Confirmed` is stronger: SalixTorrent has actually observed a remote peer complete an incoming BitTorrent handshake on that listener. General, Preferences, and Diagnostics report UPnP and NAT-PMP separately, including the failing stage and protocol fault/result code when available, plus a cached diagnosis and suggested next action. Failure to obtain automatic mapping is a notice rather than a fatal transfer error; outbound connections and other discovery mechanisms can continue normally.

When a mapping protocol reports an external IPv4 address, SalixTorrent classifies it conservatively as Public, Private, Shared/CGNAT, or another non-global scope. A non-public address is treated as a clue that double NAT or provider-side CGNAT may exist, not as definitive proof. The built-in Help/Glossary explains automatic mapping, manual TCP/UDP forwarding, double NAT, CGNAT, and why `Incoming Confirmed` is the strongest practical evidence available to the client.

Router mapping leases are finite on many devices. SalixTorrent renews successful mappings before expiry with one shared sleeping timer covering all active listen ports. There is no busy connectivity poll and no per-torrent renewal loop. If a renewal attempt fails while an earlier mapping may still be valid, SalixTorrent retains the previous mapping and schedules a later retry rather than tearing the rule down first.

On Windows, a remote BitTorrent peer can reset a TCP connection while the application is closing. Python's Proactor event loop can surface `WSAECONNRESET` / WinError 10054 from its internal `connection_lost` callback even after SalixTorrent has already begun normal socket teardown. SalixTorrent treats only that specific reset as expected peer churn at the event-loop boundary; unrelated asyncio exceptions still use the normal error handler.

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
python test_piece_selection.py
python test_request_scheduling.py
python test_disk_io.py
python test_transport_security.py
python test_ipv6.py
python test_tracker_scrape.py
python test_responsive_layout.py
python test_documentation.py
```

The release-critical regression coverage includes MSE/RC4 interoperability, rarest-first/endgame scheduling, bounded request pipelines, asynchronous disk backpressure/caching, source binding, encryption fallback rules, multi-torrent port mappings, finite/permanent mapping-lease handling, structured UPnP/NAT-PMP diagnostics, source-severity accounting, Interface Lock, real inbound seeding uploads, IPv6 peer TCP, BEP-7/BEP-15 tracker peers, BEP-11 IPv6 PEX, BEP-32 DHT behavior, BEP-48 HTTP scrape batching, BEP-15 UDP scrape batching, scrape/announce telemetry isolation, Windows Proactor reset handling, responsive content-bounds geometry, framework property-cascade fallback/provenance, per-page documentation layout overrides, and semantic documentation typography/media sizing.

## Current scope

v0.2.0 focuses on BitTorrent v1. BitTorrent v2 / `btmh` support is not implemented yet. Standalone executable packaging, file associations, magnet URI registration, and installer work are intentionally planned for a later feature-complete release pass.

## Project structure

```text
SalixTorrent/
├── main.py
├── requirements.txt
├── foundation_test.py
├── test_tracker_scrape.py
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
│   │   ├── tracker.py
│   │   └── tracker_scrape.py
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
