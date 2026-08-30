# Changelog

Notable SalixTorrent changes are recorded here.

## Unreleased

### Added

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
