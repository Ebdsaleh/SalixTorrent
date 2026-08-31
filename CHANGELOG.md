# Changelog

Notable SalixTorrent changes are recorded here.

## Unreleased

### Added

- Phase 10 centralized runtime-path policy for source, frozen installed and portable execution, removing process-working-directory assumptions from state, default downloads, UI error logs and documentation media resources.
- PyInstaller release specification plus Windows build script producing a windowed standalone `SalixTorrent.exe`, console `SalixTorrentCLI.exe`, and portable ZIP with `portable.flag`.
- Inno Setup 6 installer definition with per-user installation, Start Menu/optional desktop shortcuts, optional `.torrent` and `magnet:` integration, and clean unregister behavior.
- Dependency-free Windows shell integration commands: `--shell-status`, `--register-torrent-handler`, `--unregister-torrent-handler`, `--register-magnet-handler`, and `--unregister-magnet-handler`.
- Conservative `.torrent` OpenWith ProgID registration and opt-in `magnet:` ownership with previous-handler backup/restore protection.
- Phase 10 regression coverage for portable/frozen path behavior, cwd-independent defaults, resource resolution, shell command construction and packaging contracts.
- Phase 9 BitTorrent v2 peer networking, BEP-52 hash exchange, `btmh` magnets with verified piece-layer acquisition, v2-only transfers, dual-swarm hybrid operation, protocol provenance and v1/v2/hybrid torrent creation.
- Phase 9 real-wire regression coverage for v2 seeding/downloading, BEP-52 hash servicing, hybrid v1-to-v2 upgrade, btmh piece-layer acquisition and BEP-47 virtual padding.
- Phase 8 BEP-52 metainfo/SHA-256/file-tree/Merkle/piece-layer validation foundation.
- Phase 7 shared desktop/headless transfer-add architecture and clean headless lifecycle.

### Changed

- New installations no longer derive their default download directory from the process working directory; installed profiles default to the user's Downloads/SalixTorrent folder while portable profiles default beside the executable.
- UI error logging and application state now share one centralized state-directory policy.
- Documentation image resources resolve relative to the application/bundle instead of the launch working directory.
- `TorrentFile`, `TorrentSession`, storage verification, tracker/DHT/PEX discovery and torrent creation are generation-aware across v1, v2 and hybrid metainfo.

### Fixed

- Frozen launches from Start Menu shortcuts, Explorer `.torrent` handlers or `magnet:` protocol handlers cannot accidentally place writable state/download defaults in an unrelated working directory.
- Hybrid BEP-47 padding remains virtual storage while still being serviceable to v1 peers, and v2 disk recheck uses generation-aware verification rather than a hard-coded SHA-1 assumption.

## v0.3.0 - 2026-08-31

### Added

- Generic framework property-cascade resolver with an explicit `UNSET` inheritance sentinel, Default/Theme/Instance provenance, per-property validation fallback, and rejected-candidate diagnostics.
- Phase 6.5 documentation-layout policy split with hard-coded safe framework defaults, sparse `DocumentationLayoutTheme` overrides, sparse per-`DocPage` `DocLayout` instance overrides, and independent margin/padding/document/title/media alignment properties.
- Runtime documentation constraint geometry that preserves valid configured values while temporarily fitting them to smaller parent bounds instead of treating responsive contraction as invalid configuration.
- Inspectable documentation layout snapshots exposing configured values, property source layers, rejected candidates, and effective document/content rectangles for programmatic theme development.

- Phase 6.5 semantic Documentation subsystem with renderer-neutral `DocPage`/section/paragraph/link/callout/code/media models and a Dear PyGui renderer.
- Parent-relative `ContentBounds` geometry and horizontal/vertical alignment primitives so reusable components can align inside their current pane instead of assuming viewport coordinates.
- Semantic documentation typography roles for page titles, leads, section/subsection headings, body text, captions, code and index headings, backed by pre-registered scalable font sizes.
- Independent Documentation Scale preference (90/100/115/130%) plus an in-Help scale control; document hierarchy scales together without enlarging data tables/toolbars.
- Centered bounded-width documentation composition: page titles center within the current readable content rectangle and long body text keeps a capped reading measure on wide monitors.
- Reusable documentation icon/callout and rich-media plumbing with portable ASCII icon fallback, lazy responsive static-image textures, captions/alt text, and graceful animation/video fallback until timed playback is implemented.
- Documentation subsystem regression coverage for content bounds, semantic typography hierarchy, scale normalization, media aspect-ratio fitting and renderer-neutral models.

- Reusable event-driven `ResponsiveLayout` service for Dear PyGui viewport/item resize dispatch, memoized geometry writes, proportional splits, fill regions, and resizable-dialog content anchoring.
- Responsive geometry regression tests covering bounds, proportional split allocation, narrow-window fallback, and growable content-height calculations.
- BEP-48 HTTP/HTTPS tracker scrape support with standards-derived scrape endpoints, repeated `info_hash` parameters, and bounded multi-torrent batching.
- BEP-15 UDP tracker scrape action support with bounded multi-info-hash datagrams and connection-ID reuse across batches.
- One application-wide timer-driven scrape coordinator that groups active torrents by tracker, caches results, and avoids UI-driven or per-torrent scrape polling.
- Per-tracker scrape telemetry for seeds, leechers, cumulative completed downloads, scrape status/age/latency, endpoint, protocol, and batch size.
- General, Sources, Properties, Diagnostics, Help Topics, and Glossary coverage for scrape S/L/C statistics and batching semantics.
- Dual-stack BitTorrent peer networking with explicit IPv4/IPv6 listeners, outbound peer TCP, family-aware endpoint telemetry, and bracket-safe IPv6 display formatting.
- IPv6 tracker support through BEP-7 `peers6`, IPv6 UDP tracker announces/responses, and concurrent per-family tracker announces with one stable session key.
- IPv6 Peer Exchange using BEP-11 `added6`/`dropped6` compact endpoints.
- IPv6 DHT participation using BEP-32 `nodes6`, family-appropriate `want` requests, hybrid compact-peer parsing, and separate IPv4/IPv6 UDP telemetry.
- IPv6-aware network-interface/VPN binding and Interface Lock diagnostics, including an `IPv6 Direct` state that distinguishes routed IPv6 from IPv4 NAT mapping.
- Bounded 64 MiB asynchronous piece write-behind pipeline with one sleeping disk worker, byte-level backpressure, and fail-closed disk-write error handling.
- Bounded 32 MiB recent-piece LRU cache plus pinned pending-piece reads so freshly verified data can be seeded without immediate read-after-write disk I/O.
- O(1) disk telemetry for queued bytes/writes, write latency, backpressure events/time, cache usage/hits/misses, completed writes, and failures.
- Explicit per-peer outstanding block-request ownership with a reverse index for O(pipeline-size) cleanup on choke, disconnect and timeout.
- Bounded Endgame Mode for the final 32 wanted blocks, including duplicate tail requests, targeted peer-wire `CANCEL` frames, and received-CANCEL handling for pending uploads.
- Adaptive per-peer request pipelines (8-64 blocks) with sent-request timeout and immediate stalled-block reassignment.
- Incremental per-piece peer-availability accounting driven by BITFIELD, HAVE, and disconnect events.
- File-priority-preserving rarest-first piece scheduling with randomized equal-rarity tie-breaking.
- BitTorrent MSE/PE peer transport with `Disabled`, `Prefer Encryption`, and `Require Encryption` policies; `Prefer Encryption` is the default.
- RC4-protected MSE incoming and outgoing peer streams, with fresh-connection plaintext fallback only under `Prefer Encryption`.
- Dependency-free internal RC4 stream implementation for MSE/PE; the existing project requirements remain sufficient.
- Network-interface/VPN source binding for peer TCP, the incoming listener, HTTP/UDP trackers, DHT, LPD, and magnet metadata retrieval.
- Optional Interface Lock / kill switch that fails a torrent closed if its selected local address disappears.
- Per-peer and per-session transport-security telemetry (`MSE/RC4` versus `Plaintext`).
- Optional display-only peer IP masking, disabled by default.
- Transport/privacy Preferences controls and expanded Help/Glossary documentation.
- Event-driven seeding telemetry for uploaded-this-session bytes, received/served upload requests, last successful PIECE upload, and active/this-session incoming peers.
- Exact listener-endpoint reporting plus separate UPnP and NAT-PMP result diagnostics.
- Structured incoming-connectivity diagnosis with mapping stage/result codes, actionable next-step guidance, and conservative public/private/Shared-CGNAT external-address classification.
- Offline Help/Glossary coverage for tracker timeouts, mapping diagnosis, manual port forwarding, double NAT, CGNAT, and external-address scope.

### Changed

- SalixTorrent's active Help/Glossary layout theme now widens the framework's conservative 980 px default reading measure to 1180 px with smaller inner insets, reducing excessive dead margin while page titles remain centered inside the resolved content bounds.
- Documentation visual tokens and geometry policy are now separate concerns: `DocumentationTheme` owns colors/spacing while `DocumentationLayoutTheme`/`DocLayout` own responsive geometry.

- The entire Help Topics and Glossary detail pane now renders through the Documentation subsystem; topic titles are visually significant centered page headings, section hierarchy is semantic, related links share one component, and glossary definitions use the same document renderer.
- Help content no longer maintains an ad-hoc list of wrapped text widgets; one resize-event-driven renderer reapplies cached content bounds, wrapping, anchoring and typography only when geometry or documentation scale changes.
- Global UI font registration now covers the bounded semantic size range once at startup, allowing item-level document roles without runtime font-atlas rebuilds.
- Diagnostics now reports Interface Text Size, Documentation Scale and the selected scalable UI font for presentation troubleshooting.

- Primary application scenes now occupy the available viewport region as real child workspaces instead of fixed-content groups, allowing native-style expansion and scrolling.
- Active Transfers now gives additional height to the queue on tall windows, lets the detail workspace consume the remaining area, expands Peers/Pieces/Files/Sources/Speed tables and plots, and proportionally resizes the General panels with live wrap widths.
- Create Torrent now grows the tracker editor with available vertical space; Preferences uses responsive two-column widths and adaptive field/text wrapping; Help uses a responsive navigator/content split.
- Diagnostics, Torrent Properties, and Open Magnet are resizable data dialogs whose growable content keeps their action rows attached to the lower content boundary. Small destructive confirmations and transient notices remain intentionally fixed-size.
- Help text wrapping is now driven by resize events instead of checking pane geometry every UI frame.
- Tracker announce health and tracker scrape statistics are now represented independently so a scrape timeout/unsupported endpoint cannot make an otherwise healthy discovery source look failed.
- Sources now exposes scrape S/L/C alongside announce-derived Swarm S/L and summarizes scrape active/pending/warning/error state separately.
- Manual tracker refresh also schedules a coalesced scrape refresh, while normal scrape refreshes use one shared low-frequency timer.
- Any-interface torrent sessions now use IPv4 and IPv6 concurrently where available, while a specific address bind remains fail-closed to that address family.
- BEP-32 DHT selects a concrete route-derived IPv6 source address under Any interface and skips IPv6 DHT cleanly when no routable IPv6 source exists.
- Tracker Sources telemetry now records returned IPv4/IPv6 peer counts and the address families used for the latest announce cycle.
- BEP-14 Local Peer Discovery is explicitly disabled under an IPv6-only bind because the protocol is IPv4 multicast.
- Verified piece filesystem writes and resume-state fsync work now run away from the asyncio peer/UI hot path; torrent completion waits for the bounded disk queue to flush.
- Fast-resume metadata now records only persisted pieces, while verified-but-buffered pieces remain temporarily uploadable from memory.
- Pieces telemetry now exposes scheduler mode, wanted blocks remaining, outstanding wire requests, and endgame duplicate counts without adding a polling loop.
- Download workers refill bounded pipelines in small bursts and start request timeout clocks only after REQUEST frames are actually transmitted.
- Pieces telemetry now reads the incremental availability cache instead of rebuilding availability by rescanning every connected peer bitfield.
- Download block selection now uses cached rarity buckets rather than sequentially scanning pieces from index zero.
- Tracker announces advertise encrypted-peer support and request encrypted peers when `Require Encryption` is selected.
- Changing the selected network path or peer-encryption policy closes existing torrent sockets so subsequent connections use the new policy.
- Incoming connectivity now tracks every active torrent listen port independently instead of exposing one global port as if it belonged to every torrent.
- General transfer wording now distinguishes persisted `Uploaded Total` from process-local `Uploaded This Session`, and `Active Time` from wall-clock age.
- Finite UPnP/NAT-PMP mapping leases are renewed before expiry using one shared low-frequency timer for all active ports rather than a polling loop per torrent.
- Sources telemetry now separates neutral pending states from amber timeout warnings and red source errors instead of grouping them together as generic problems.
- NAT-PMP diagnostics decode standard gateway result codes; UPnP diagnostics preserve the failing discovery/SOAP stage and router fault code when available.

### Fixed
- Dear PyGui item-resize callbacks now expose only the standard sender/app_data/user_data signature under manual callback management; responsive window resizing no longer crashes `dpg.run_callbacks()` with `IndexError: tuple index out of range`.
- UDP tracker timeouts now remain source-local Timeout warnings through dual-stack address failover instead of being wrapped and misreported as protocol Errors.
- Sources labels the primary state column as Discovery and tracker help distinguishes announce status from independent scrape status.

- Windows Proactor shutdown no longer prints a traceback for the expected `ConnectionResetError` / WinError 10054 case when a remote peer resets its TCP connection during application teardown; unrelated asyncio exceptions remain visible.
- IPv6 DHT `values` parsing now accepts the BEP-32-required hybrid list containing both 6-byte IPv4 and 18-byte IPv6 peer entries.
- IPv6-bound sessions no longer attempt unrelated IPv4 UPnP/NAT-PMP mappings that could violate the selected network path.
- Slow storage can no longer block the peer event loop during verified-piece writes; bounded asynchronous backpressure limits memory growth instead.
- A disk write failure no longer leaves buffered-only pieces represented as safely completed resume data.
- Starting a second active torrent no longer removes the UPnP/NAT-PMP mapping belonging to the first torrent.
- Stopping or rebinding a torrent releases only that torrent listener's router mapping.
- General/Diagnostics connectivity reporting now follows the selected torrent's actual listen port, preventing another torrent's mapping from being shown as its own.
- A failed router-lease refresh now retains the previous mapping while retrying instead of deleting a still-valid mapping first.
- UPnP gateways that reject finite leases with `OnlyPermanentLeasesSupported` are retried with a permanent mapping rather than being reported as simply unmapped.
- NAT-PMP lease scheduling now respects the lifetime actually returned by the gateway instead of assuming the requested lifetime was granted.

## v0.2.0 - 2026-08-26

### Added

- Persistent multi-torrent session restoration and queue ordering.
- Fast-resume state with background SHA-1 checking and live checking progress.
- Seeding, external-source seeding, and upload telemetry.
- Bidirectional peer connections so verified pieces can be uploaded while downloading.
- HTTP/HTTPS and UDP tracker telemetry and manual tracker refresh.
- DHT (BEP-5), PEX (BEP-10/BEP-11), and Local Peer Discovery (BEP-14).
- BitTorrent v1 magnet support with BEP-9 metadata retrieval and metadata serving.
- Create Torrent workflow for files and directories.
- Multi-file storage views and selective per-file download priorities.
- Torrent High/Normal/Low queue priorities, Move Up/Move Down ordering, and active download slots.
- Per-torrent and global upload/download bandwidth limits.
- General, Peers, Pieces, Files, Sources, and Speed detail views.
- Compact piece map and per-piece/per-peer/source telemetry.
- Traditional application menu, keyboard shortcuts, diagnostics, properties, and expanded context actions.
- Persistent Preferences view with networking, queue, bandwidth, desktop, and display settings.
- UPnP/NAT-PMP automatic mapping attempts and incoming-connectivity reporting.
- Configurable transfer-rate display units: Automatic, KB/s, MB/s, kbps, and Mbps.
- Comprehensive contextual hover help.
- Searchable CHM-style Help Topics view and A-Z glossary.

### Changed

- File loading, checking, peer handling, and Dear PyGui refresh paths were moved away from blocking UI work.
- Live UI telemetry is coalesced/rate-limited so hidden or stale detail views do not freeze the interface.
- Remote peer disconnects are treated as normal swarm churn rather than unhandled asyncio errors.
- Private torrents no longer use public fallback trackers and disable DHT, PEX, and LPD discovery.
- UI-facing typography uses ASCII-safe separators for consistent rendering with the bundled/current monospace font.

### Fixed
- Dear PyGui item-resize callbacks now expose only the standard sender/app_data/user_data signature under manual callback management; responsive window resizing no longer crashes `dpg.run_callbacks()` with `IndexError: tuple index out of range`.

- Torrent file-picker delays and inconsistent transfer controls after newly loading a torrent.
- Pause/Stop/Resume behaviour while checking or downloading.
- Stale UI snapshot backlogs when switching views.
- Win32 tray callback pointer-width errors on 64-bit Windows.
- Tooltip parent/container-stack corruption in Dear PyGui.
- Help Topics navigation callbacks that highlighted entries without updating the content pane.
- Upload-speed reporting while the session is in Downloading state.

## v0.1.0

Initial development baseline: custom bencode/metainfo parsing, basic tracker/peer-wire download path, piece verification, and the first Dear PyGui transfer interface.
