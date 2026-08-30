# Changelog

Notable SalixTorrent changes are recorded here.

## Unreleased

### Added

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

- Torrent file-picker delays and inconsistent transfer controls after newly loading a torrent.
- Pause/Stop/Resume behaviour while checking or downloading.
- Stale UI snapshot backlogs when switching views.
- Win32 tray callback pointer-width errors on 64-bit Windows.
- Tooltip parent/container-stack corruption in Dear PyGui.
- Help Topics navigation callbacks that highlighted entries without updating the content pane.
- Upload-speed reporting while the session is in Downloading state.

## v0.1.0

Initial development baseline: custom bencode/metainfo parsing, basic tracker/peer-wire download path, piece verification, and the first Dear PyGui transfer interface.
