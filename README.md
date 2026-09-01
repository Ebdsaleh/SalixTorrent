# SalixTorrent (Salix_T) v0.3.0

SalixTorrent is a desktop BitTorrent client written in Python with a custom asynchronous protocol engine and a Dear PyGui interface. Its transfer engine is generation-aware across BitTorrent v1, BitTorrent v2 and hybrid torrents, while keeping protocol identity, storage verification, discovery provenance and torrent creation explicit. The project aims to expose what a torrent client is doing rather than hiding the protocol behind a single progress bar: transfers, peers, pieces, files, trackers, discovery sources, bandwidth history, connectivity, and protocol terminology are all inspectable from the application.

> **Release status:** v0.3.0 remains the current development version string while the post-v0.3.0 roadmap work is integrated. Phases 1-10 are complete. Phase 11 adds a cross-platform desktop-integration layer with safe tray/menu-bar behavior, Linux/BSD and macOS backends, platform-aware notifications, close/minimize-to-tray policy, and capability diagnostics.

## Highlights

**v0.3.0 milestone:** SalixTorrent now combines a substantially more capable BitTorrent v1 engine with a reusable responsive Dear PyGui presentation foundation. The release adds rarest-first/endgame scheduling, bounded adaptive request pipelines, asynchronous disk backpressure/caching, MSE/PE transport, network-interface binding and Interface Lock, dual-stack IPv6 peer/tracker/DHT support, batched tracker scrape statistics, event-driven seeding/connectivity telemetry, and the semantic responsive Documentation subsystem.

- Load v1, v2 or hybrid `.torrent` files and `btih`/`btmh` magnet links.
- Generation-aware magnet metadata retrieval with info-hash and BEP-52 piece-layer verification.
- HTTP/HTTPS and UDP tracker announce support plus batched tracker scrape statistics, DHT, PEX, and Local Peer Discovery for public torrents.
- Private-torrent isolation: no public fallback trackers, DHT, PEX, or LPD leakage.
- Concurrent downloading and uploading over bidirectional peer connections.
- Incoming peer listener, seeding, and external-source seeding.
- Fast resume with generation-aware SHA-1 / SHA-256-Merkle recheck fallback.
- Single-file and multi-file torrents with selective file downloading and file priorities.
- Torrent queue priorities, move up/down ordering, and configurable active download slots.
- Per-torrent and true global upload/download rate limits.
- Live General, Peers, Pieces, Files, Sources, and Speed views.
- Compact piece map, peer client identification, source diagnostics, and rolling speed history.
- Incremental piece-availability accounting with file-priority-preserving rarest-first scheduling and randomized equal-rarity tie-breaking.
- v1, v2 and recommended hybrid torrent creation from a file/archive or directory.
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

- Python 3.13 is the primary development/runtime version for v0.3.0.
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

Open a magnet at launch (`btih`, `btmh`, or hybrid):

```bash
python main.py "magnet:?xt=urn:btih:..."
```

Show the release version:

```bash
python main.py --version
```

Headless mode uses the same transfer-add API and BitTorrent engine as the desktop interface. It accepts v1/v2/hybrid `.torrent` files and compatible magnets:

```bash
python main.py --cli path/to/file.torrent
python main.py --cli "magnet:?xt=urn:btih:..."
```

Headless status is rate-limited terminal output by default. For scripts and external tooling, JSON Lines output is available without importing Dear PyGui:

```bash
python main.py --cli path/to/file.torrent --json-status
```

Useful headless options include `--download-dir`, `--max-peers`, `--status-interval`, and `--exit-on-complete`. Without `--exit-on-complete`, a completed transfer remains alive and seeds until interrupted. `Ctrl+C`, SIGTERM, and Windows SIGBREAK request the same centralized TorrentManager shutdown used by desktop exit. Headless runs are deliberately excluded from the desktop application's persistent transfer queue and resolved magnet metainfo is held only for the lifetime of the headless process.

## Shared transfer-add architecture

Phase 7 removes the old GUI/CLI split for user-supplied torrent sources. Desktop Open Torrent/Open Magnet, command-line startup targets, headless `.torrent` files, and headless magnets all enter one presentation-neutral `TransferAddRequest -> TorrentManager.add_transfer()` path. The request carries lifecycle/persistence/download/max-peer policy while the engine owns validation, magnet metadata resolution, session creation, queue/start behavior, and structured events.

The headless layer lives under `app/cli/` and consumes the same `MAGNET_*` and `TRANSFER_STATS` event dictionaries used by the desktop presentation. It formats those events as human-readable terminal status or JSON Lines; it does not import Dear PyGui and does not contain torrent protocol logic. This keeps the backend usable by future OS file/magnet registration, service processes, tests, or alternate front ends without cloning application behavior.

## BitTorrent v2 foundation (Phase 8)

Phase 8 established strict BEP-52 parsing and validation. `TorrentFile` preserves exact raw `info` bytes, calculates the complete 32-byte SHA-256 v2 info hash, represents hybrid SHA-1/SHA-256 identities without truncating canonical storage, traverses file-aligned BEP-52 file trees safely, and validates required piece layers against file size and declared Merkle roots.

`app/logic/torrent_v2.py` contains presentation-neutral Merkle primitives for 16 KiB SHA-256 leaf blocks, layer-specific zero-subtree hashes, file-root construction, piece-layer construction/verification and sibling-proof verification. Short final pieces are padded only inside the appropriate Merkle subtree.

## BitTorrent v2 networking & hybrid swarms (Phase 9)

Phase 9 carries that foundation through the live engine. Auto / Best Compatible chooses v1 for v1-only metainfo, v2 for v2-only metainfo, and both compatible swarms for hybrid metainfo; explicit v1 Only / v2 Only overrides remain available for compatibility and testing. Tracker/DHT discovery, PEX provenance, peer handshakes, storage verification and scrape identities remain generation-aware.

The peer wire supports BEP-52 `HASH_REQUEST`, `HASHES` and `HASH_REJECT`, including hybrid v1-to-v2 upgrading. `btmh` magnet resolution can obtain and verify the top-level v2 piece layers that BEP-9 metadata alone does not carry. v2-only downloads/seeding and hybrid operation use the same storage engine, while BEP-47 alignment padding is virtual zero data: it is not written as payload files but remains serviceable to legacy v1 peers.

Create Torrent can emit BitTorrent v1, BitTorrent v2, or recommended hybrid metainfo. v2 output includes file trees, pieces roots and piece layers; hybrid output carries both identities and BEP-47 alignment entries.

## Packaging & Windows integration (Phase 10)

Phase 10 centralizes runtime paths so source runs, PyInstaller one-file executables, Start Menu launches, Explorer `.torrent` opens and `magnet:` URL launches do not depend on the process working directory. Installed builds keep settings/session/cache/error state in the platform per-user state location. A `portable.flag` beside the executable switches state to `.\data` and makes `.\downloads` the default for a new portable profile; `--portable` can request the same mode for one launch.

`packaging/build_windows.bat` is the primary Windows release builder. Run it from an already activated project virtual environment; it prints the exact Python interpreter it will use, runs the regression suite, builds the windowed `SalixTorrent.exe` and console `SalixTorrentCLI.exe`, creates the portable ZIP, and can compile the Inno Setup installer. The PowerShell builder remains available as an alternative. Build-only dependencies live in `requirements-build.txt`.

The Windows installer is per-user by default and offers `.torrent` handler registration plus explicit opt-in `magnet:` registration. `.torrent` registration uses SalixTorrent's own ProgID/Open With entry rather than silently replacing another client's default. Because `magnet:` is a single-owner URL scheme, SalixTorrent backs up the previous standard handler values and restores them on unregister only when the current scheme still belongs to that SalixTorrent executable. Portable users can use `--register-torrent-handler`, `--register-magnet-handler`, matching unregister commands, and `--shell-status`.

To build Windows release artifacts from an activated virtual environment in Command Prompt:

```bat
.venv\Scripts\activate
packaging\build_windows.bat
```

PyInstaller builds must be produced on the target operating system; the build script therefore refuses to pretend it can cross-build Windows executables from Linux/macOS. Inno Setup 6 is required only for the installer step; `--skip-installer` still produces the standalone and portable artifacts.

## Cross-platform desktop integration (Phase 11)

Phase 11 moves tray/menu-bar behavior behind `DesktopIntegration`, so torrent logic and Dear PyGui views do not call platform APIs directly. Tray callbacks enqueue semantic actions (`Open SalixTorrent`, `Pause All`, `Resume All`, `Exit`) and the Dear PyGui main thread performs the actual UI/torrent action. This makes the tray lifecycle the same for `python main.py` and frozen builds and avoids manipulating live Dear PyGui widgets from tray worker threads.

Windows keeps a dependency-free native Win32 notification-area backend. After the Dear PyGui viewport is shown, SalixTorrent discovers its real top-level HWND by process rather than depending on a Dear PyGui native-handle helper, then installs a small native close/minimize bridge. `Open SalixTorrent` performs restore/foreground activation while the tray thread is servicing the user's click, with a main-thread restore fallback; the icon is also re-added after Explorer/taskbar recreation. This same binding path is used by `python main.py` and frozen builds. Linux and BSD use pystray when a compatible desktop tray implementation is available; X11 supplies native hide/restore/focus and minimize detection. Wayland-only sessions without an X11 viewport are reported as limited instead of allowing SalixTorrent to disappear into an unreachable tray. macOS uses a pystray menu-bar status item with AppKit window activation. Native notification capability is tracked separately from tray capability because desktops may provide one without the other.

`Minimize to system tray` and `Close window to system tray` are separate preferences. SalixTorrent hides the viewport only when a tray is currently running and native recovery is available. If that capability disappears, close falls back to a normal shutdown rather than hiding the application. Tray `Exit` always requests a real clean shutdown. Preferences and `Help -> Diagnostics` expose the selected backend, live tray state, menu/notification support, native window recovery support and an explanatory capability/detail string.

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

This includes settings, session state, cached magnet metadata, shell-integration backup state, and the UI error log. Download payloads use the configured download directory. A portable build instead keeps writable state in `data/` beside the executable and defaults new portable profiles to `downloads/` beside it.

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

The Create Torrent view can build BitTorrent v1, v2, or recommended hybrid `.torrent` metainfo from:

- a single file;
- an archive such as ZIP/7z (treated as an ordinary file payload);
- a directory tree.

Users can choose generation, piece size, trackers, privacy, comment, output path, and optionally start seeding the original source after creation. Hybrid output uses BEP-47 alignment padding while v2 output includes BEP-52 file-tree/Merkle metadata.

## Tests

The project currently includes a foundation suite and focused regression coverage, including dedicated BEP-52/v2 metainfo and Merkle tests. Local/network integration scripts may require a `test.torrent` and active peers.

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
python test_headless_cli.py
python test_torrent_v2.py
python test_phase9.py
python test_phase10.py
python test_phase11.py
```

The release-critical regression coverage includes strict BEP-52 v2 identity/file-tree/piece-layer/Merkle validation, MSE/RC4 interoperability, rarest-first/endgame scheduling, bounded request pipelines, asynchronous disk backpressure/caching, source binding, encryption fallback rules, multi-torrent port mappings, finite/permanent mapping-lease handling, structured UPnP/NAT-PMP diagnostics, source-severity accounting, Interface Lock, real inbound seeding uploads, IPv6 peer TCP, BEP-7/BEP-15 tracker peers, BEP-11 IPv6 PEX, BEP-32 DHT behavior, BEP-48 HTTP scrape batching, BEP-15 UDP scrape batching, scrape/announce telemetry isolation, Windows Proactor reset handling, responsive content-bounds geometry, framework property-cascade fallback/provenance, per-page documentation layout overrides, and semantic documentation typography/media sizing.

## Current scope

Phases 1-10 are complete in the live source tree, including native Windows standalone/portable/installer validation. Phase 11 implements the cross-platform desktop/tray abstraction, the native Windows lifecycle/focus fixes, Linux/BSD and macOS backends, safe close/minimize-to-tray policy, and capability diagnostics/help. Linux/BSD/macOS native desktop behavior still requires smoke-testing on those operating systems even though the platform-neutral contracts are regression-tested.

## Project structure

```text
SalixTorrent/
├── main.py
├── cli_main.py
├── requirements.txt
├── requirements-build.txt
├── foundation_test.py
├── test_piece_selection.py
├── test_request_scheduling.py
├── test_disk_io.py
├── test_transport_security.py
├── test_ipv6.py
├── test_tracker_scrape.py
├── test_responsive_layout.py
├── test_documentation.py
├── test_headless_cli.py
├── test_torrent_v2.py
├── test_phase9.py
├── test_phase10.py
├── test_phase11.py
├── packaging/
│   ├── SalixTorrent.spec
│   ├── build_windows.bat
│   ├── build_windows.ps1
│   └── windows/SalixTorrent.iss
├── app/
│   ├── version.py
│   ├── cli/
│   │   └── headless.py
│   ├── engine/
│   │   ├── documentation/
│   │   │   ├── layout.py
│   │   │   ├── model.py
│   │   │   ├── renderer.py
│   │   │   └── typography.py
│   │   ├── desktop_integration.py
│   │   ├── gui_engine.py
│   │   ├── master_viewport.py
│   │   ├── property_cascade.py
│   │   ├── responsive_layout.py
│   │   ├── runtime_paths.py
│   │   ├── shell_integration.py
│   │   ├── scene_manager.py
│   │   ├── texture_manager.py
│   │   └── ui_typography.py
│   ├── logic/
│   │   ├── async_manager.py
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
│   │   ├── torrent_v2.py
│   │   ├── transfer_add.py
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
├── CHANGELOG.md
└── README.md
```


## Phase 12 localization foundation

SalixTorrent now has an offline-first localization layer. The application never
contacts a translation service at runtime: locale JSON files are bundled into
source/frozen releases and `en-AU` is the canonical fallback when a translated
entry is missing or invalid.

Initial locale identifiers are:

```text
en-AU   English (Australia)       canonical source
en-GB   English (United Kingdom)
en-US   English (United States)
pt-BR   Português (Brasil)
fil-PH  Filipino
```

Preferences exposes **Application language** with **System Default** plus the
explicit locale choices. A language change is persisted immediately and the UI
asks for a restart while the Phase-12 migration is in progress, which avoids
partially rebuilding live Dear PyGui controls.

Translation generation is development-only:

```bat
python -m pip install -r requirements-localization.txt
python tools\localization\build_locales.py --extract
python tools\localization\build_locales.py --check
python tools\localization\build_locales.py --report
python tools\localization\build_locales.py --translate
python tools\localization\build_locales.py --validate
```

Or run the complete pipeline:

```bat
python tools\localization\build_locales.py --all
```

The Google Cloud adapter uses Application Default Credentials and the
`GOOGLE_CLOUD_PROJECT` environment variable. Credentials are never stored in
SalixTorrent, locale packs, the portable bundle or the installer.

Useful offline/maintenance modes include:

```bat
python tools\localization\build_locales.py --validate
python tools\localization\build_locales.py --translate --no-network
python tools\localization\build_locales.py --translate --locale pt-BR
```

The pipeline translates only explicitly marked `tr(key, source)` strings plus
the semantic Help and Glossary data. It does **not** scrape arbitrary Python
string literals. Named format placeholders and protected BitTorrent/network
terms are validated before generated locale data is accepted.

Machine translation remains a draft layer. Reviewed wording can be placed in
`tools/localization/manual_overrides/<locale>.json`; unchanged strings are
reused through `translation_cache.json` so routine runs do not repeatedly send
the whole application to the translation provider.

The complete architecture and Phase-12 completion checklist are documented in
`SalixTorrent-Phase12-Localization-Design.md`.

### Phase 12 Stage 2 - UI string migration

Stage 2 routes the primary application views through semantic localization keys
instead of embedding user-facing English directly in Dear PyGui calls. The
canonical `en-AU` UI catalog currently contains **649 entries**, including a
presentation-only catalog for stable torrent states, priorities and protocol
choices.

Internal values remain canonical and locale-independent. For example, the engine
and settings still store `Downloading`, `High`, `Prefer Encryption` and
`BitTorrent v2 Only`; the view layer translates those values only when they are
displayed and maps localized combo choices back to their canonical values before
saving them. This prevents a language change from altering persistence, protocol
logic or state comparisons.

Stage 2 covers the main transfer queue/detail views, Preferences, dialogs,
status/progress text, Create Torrent, completion notifications and human-facing
CLI output. Machine-readable CLI/JSON output, torrent metadata, paths, hashes,
tracker URLs and protocol identifiers remain locale-independent.

The four non-canonical locale packs intentionally remain incomplete until the
canonical migration is stable. Missing Stage-2 entries therefore fall back to
bundled `en-AU` text offline; the Google translation step has **not** been run as
part of this migration. The catalog validator reports missing-translation
warnings but no structural errors.

Localization source resources, manual overrides, protected terminology, the
translation cache and this design document are intended to be committed. Google
credentials, local build output, torrent payloads, virtual environments and the
project's existing local regression-test files remain ignored by `.gitignore`.

### Phase 12 Stage 3 - semantic documentation migration

Stage 3 moves canonical Help and Glossary prose out of the Dear PyGui view
modules and into renderer-neutral semantic source documents:

```text
app/localization/content/help.json
app/localization/content/glossary.json
```

Help topics, Help sections and Glossary terms have stable locale-neutral IDs.
Translated locale catalogs contain wording only; navigation relationships,
related-term links, topic order and section structure are shared across every
language. Help section translation keys now use stable section IDs rather than
list positions, so reordering an article does not rename its translations.

`help_topics_view.py` and `help_terms.py` therefore render semantic objects and
no longer own the canonical English manual/glossary text. The same Glossary
source continues to power both the A-Z manual and contextual hover help.

The localization validator now checks documentation topology as well as locale
catalogs: duplicate/missing IDs, broken related-term links and canonical catalog
drift are release errors. PyInstaller bundles both the locale packs and the
semantic document sources, so Help/Glossary remain fully offline in standalone,
portable and installed builds.

The Stage 3 documentation-shell cleanup adds four localized navigation/tool-tip
strings, bringing the current canonical UI catalog to **653 entries**.

Target-language Help and Glossary prose is intentionally still ungenerated at
this checkpoint; missing entries continue to fall back to bundled `en-AU` until
the translation-generation stage.


### Phase 12 Stage 4 - reproducible extraction

Stage 4 makes the canonical `en-AU` catalogs reproducible from authoritative
source. The extractor reads literal `tr(key, source)` calls through Python AST,
the semantic Help/Glossary documents, presentation-value sources and the small
`app/localization/content/ui_static.json` source for intentionally indirect UI
text. It no longer carries unknown entries forward from a previously generated
catalog.

The committed `tools/localization/extraction_manifest.json` records each key's
SHA-256 source hash, placeholders/format fields and source locations. Conflicting
duplicate keys are rejected; exact same-text reuse is recorded for audit. Dynamic
direct `tr()` calls are also surfaced instead of silently disappearing from the
canonical catalog.

Useful offline developer commands are:

```bat
python tools\localization\build_locales.py --extract
python tools\localization\build_locales.py --check
python tools\localization\build_locales.py --report
python tools\localization\build_locales.py --validate
```

`--check` is non-mutating and fails when the generated canonical catalogs or
manifest no longer match source. `--report` prints extraction counts, placeholder
coverage, safe key reuse and the dynamic-call audit.


### Phase 12 Stage 5 - changed-only translation pipeline

Stage 5 turns the development-only Google adapter into a safe, reproducible
translation pipeline. The default provider path uses Cloud Translation v3 with
Google's `general/translation-llm` model so the regional English targets
(`en-AU`, `en-GB`, `en-US`) can be treated as real locale targets alongside
`pt-BR` and Filipino. Translation remains a build/development operation only;
none of these Google dependencies or credentials are needed by SalixTorrent at
runtime.

Before contacting Google, inspect the changed-only plan without credentials or
network access:

```bat
python tools\localization\build_locales.py --dry-run
python tools\localization\build_locales.py --dry-run --locale pt-BR
```

The checked-in `translation_cache.json` is keyed by the Stage-4 source hashes.
Unchanged strings are reused, changed/new strings are scheduled for translation,
and reviewed entries in `manual_overrides/<locale>.json` always win even when
`--force` is requested. Stage 5 bootstraps the 113 pre-existing UI translations
for each target locale into that cache, so the first Google run starts with
1,158 untranslated strings per locale rather than retranslating known wording.

For a real Google run, install only the development dependency and configure
Application Default Credentials plus a project:

```bat
python -m pip install -r requirements-localization.txt
gcloud auth application-default login
set SALIX_T_GOOGLE_PROJECT=your-google-cloud-project-id
python tools\localization\build_locales.py --dry-run --locale pt-BR
python tools\localization\build_locales.py --translate --locale pt-BR
python tools\localization\build_locales.py --validate --locale pt-BR
```

`--project-id` can be supplied instead of the environment variable. Project
discovery precedence is explicit `--project-id`, `SALIX_T_GOOGLE_PROJECT`,
`GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT`, then the project supplied by Google
Application Default Credentials. `SALIX_T_GOOGLE_LOCATION` / `--location` and
`SALIX_T_GOOGLE_MODEL` / `--model` are available for advanced development use.

`--no-network` never loads the Google client and rebuilds locale files only from
source-hash-valid cache entries plus manual overrides. It deliberately refuses
to trust an old generated translation whose source hash is no longer current;
that entry is omitted and runtime `en-AU` fallback remains available.

Provider calls are batched, protected placeholders/technical tokens are restored
and validated before acceptance, HTML entities returned by the provider are
unescaped, transient Google failures receive bounded retries, and provider/auth
failures occur before locale/cache files are committed. The cache is written
last so an interrupted artifact write can at worst cause harmless retranslation
on the next development run.

### Phase 12 Stage 6 - initial locale generation

Stage 6 is intentionally split into a safe local preflight and the credentialed
Google generation run. SalixTorrent itself remains fully offline: Google tooling
exists only in the developer virtual environment and generated locale JSON is
bundled into the application.

The Windows helper is tracked as:

```bat
tools\localization\stage6_generate_locales.bat
```

With the SalixTorrent `.venv` activated, running it with no arguments performs
only non-translation preflight checks: canonical extraction, extraction drift, the
changed-only translation plan, locale completeness status, and the Google setup
doctor. It does **not** submit application text to the Translation API or make a
billable translation request.

Stage-6-specific commands are:

```bat
python tools\localization\build_locales.py --status
python tools\localization\build_locales.py --doctor
python tools\localization\build_locales.py --doctor --probe
python tools\localization\build_locales.py --generate-initial
```

`--status` is offline and reports packaged/catalog/cache coverage. `--doctor`
checks that the development client library, Google auth,
Application Default Credentials and project resolution are available without
printing credential paths, tokens or secrets. `--doctor --probe` is optional
and performs one tiny authenticated Translation request to verify API/model
access before the full generation run.

For a new Windows development machine, the intended setup is:

```bat
python -m pip install -r requirements-localization.txt
gcloud init
gcloud services enable translate.googleapis.com --project YOUR_PROJECT_ID
gcloud auth application-default login
set SALIX_T_GOOGLE_PROJECT=YOUR_PROJECT_ID
python tools\localization\build_locales.py --doctor
```

Cloud Translation v3 uses Application Default Credentials; credentials are not
written into this repository. The `SALIX_T_GOOGLE_PROJECT` assignment above is
for the current Command Prompt only unless the developer deliberately persists
it separately.

Once the doctor reports ready, either run:

```bat
tools\localization\stage6_generate_locales.bat --run
```

or equivalently:

```bat
python tools\localization\build_locales.py --generate-initial
```

The one-shot Stage 6 command refuses to translate if canonical extraction is
stale, translates only source-hash-missing entries, then runs **strict** locale
validation. It succeeds only when every selected target pack has every canonical
UI, Help and Glossary key. Until that credentialed command has completed on a
development machine, Stage 6 remains in progress rather than being marked done.


### Phase 12 Stage 7 - validation and packaging hardening

Stage 7 is fully offline and can proceed while initial machine translation is on hold.
Canonical extraction now also regenerates a deterministic runtime locale manifest:

```text
app/localization/locales/manifest.json
```

The manifest records per-locale/catalog counts and hashes plus script, text direction,
font profile and support state. `--check` verifies both the Stage-4 extraction manifest
and this runtime locale manifest.

The Stage-7 validator additionally checks catalog metadata/hash integrity, stale
source-hash provenance for packaged translations, protected technical terminology,
placeholder contracts, semantic Help/Glossary topology and target completeness. A
missing or corrupt target runtime catalog does not prevent application startup: the
`LocalizationManager` records the load failure and falls back to canonical `en-AU`.

Development pseudo-localization is available as the derived `en-XA` locale. It is
created entirely in memory, accents text, expands it by roughly 30%, and preserves
Python formatting placeholders. To launch a source-tree smoke test from Windows CMD:

```bat
set SALIX_T_PSEUDO_LOCALE=1
python main.py
set SALIX_T_PSEUDO_LOCALE=
```

The normal Stage-7 preflight is:

```bat
tools\localization\stage7_validate_localization.bat
```

or directly:

```bat
python tools\localization\build_locales.py --extract
python tools\localization\build_locales.py --check
python tools\localization\build_locales.py --stage7-check
```

`--stage7-check` performs no translation-provider calls. It audits the pseudo locale,
checks required Help/Glossary/locale resources and the PyInstaller data contract, then
runs the hardened locale validator. The existing missing-translation warnings remain
expected until Stage 6B locale population resumes.

### Phase 12 Stage 8A - offline translation review infrastructure

Stage 8A is provider-neutral and can be used while Stage 6B machine-translation
population is on hold. It distinguishes *translation completeness* from *human
review completeness*: an entry may be missing, present but awaiting review,
reviewed, locked, stale, or invalid.

Run the normal offline review audit from an activated Windows `.venv` with:

```bat
tools\localization\stage8_review_localization.bat
```

The direct commands are:

```bat
python tools\localization\build_locales.py --review-report
python tools\localization\build_locales.py --review-export --locale pt-BR
python tools\localization\build_locales.py --stage8-check
```

`--review-export` writes an editable working bundle under
`tools/localization/review_exports/` by default. That directory is intentionally
ignored by Git: review bundles are handoff/work files, while canonical source,
manual overrides, translation cache and locale packs remain the repository source
of truth. Each exported entry carries its canonical source text/hash, placeholders,
source locations, current translation, provenance/provider metadata, current status,
and editable `review_state`, `reviewer`, and `note` fields.

A reviewer should leave ordinary entries as `pending`. After checking a translation
in context, set `review_state` to `reviewed` or `locked`; `locked` is intended for
terminology/text that future provider regeneration must never replace. Import the
finished bundle with:

```bat
python tools\localization\build_locales.py --review-import tools\localization\review_exports\pt-BR.review.json
```

Import is fail-closed and validates the *entire* bundle before promotion. It rejects
a changed canonical source hash, edited source text, missing/changed protected terms,
broken Python formatting placeholders, unknown keys/catalogs, empty reviewed text,
and invalid review states. Accepted translations are written into the packaged locale
and then recorded as rich authoritative entries in
`manual_overrides/<locale>.json`, including source hash, review/lock state, reviewer,
note and UTC review timestamp. A later canonical wording change therefore makes the
reviewed entry stale instead of silently treating old wording as approved.

Current Stage 8A reports are expected to remain incomplete while Stage 6B is paused:
the four target locales presently contain 113 seeded UI entries awaiting review and
1,158 missing entries each. That is a content-status warning, not an infrastructure
failure. Stage 8B will perform the actual warning/security/BitTorrent/Help/Glossary/
high-visibility language review after locale population resumes.

