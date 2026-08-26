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
- Torrent creation from a file/archive or directory.
- Persistent session restoration and application preferences.
- UPnP / NAT-PMP mapping attempts and incoming-connectivity reporting.
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
- **Sources** — trackers, DHT, PEX, and LPD with live status and diagnostic telemetry.
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

When all wanted pieces are complete, the session can transition to seeding. Torrents created from local files/directories can also seed directly from the original source in read-only external-seed mode.

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

## Connectivity

SalixTorrent listens for incoming BitTorrent TCP connections and attempts automatic router mapping using UPnP, with NAT-PMP as a fallback where available.

`Mapped` means the router accepted a mapping request. `Incoming Confirmed` is stronger: SalixTorrent has actually observed a remote peer reaching the listening socket. Failure to obtain automatic mapping is a notice rather than a fatal transfer error; outbound connections and other discovery mechanisms can continue normally.

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
python test_regressions.py
```

The release-critical regression coverage includes private-torrent discovery isolation and uploading verified data while a session is still downloading.

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
