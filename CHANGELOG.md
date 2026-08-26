# Changelog

Notable SalixTorrent changes are recorded here.

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
