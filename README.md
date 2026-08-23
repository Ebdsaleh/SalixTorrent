# SalixTorrent (Salix_T) `v0.1.0`

A lightweight, object-oriented BitTorrent client and network protocol engine written in Python. SalixTorrent features a strict separation between its core networking engine and presentation layers, supporting headless CLI operations as well as a GPU-accelerated desktop interface built with DearPyGui.

---

## Features

- **Protocol & Network Engine:**
  - **Custom Bencode Engine:** Native encoder and decoder for BitTorrent metainfo serialization and deserialization.
  - **Dual Tracker Support:** Handles HTTP/HTTPS tracker queries as well as asynchronous UDP tracker transactions (BEP 0015) with fallback tracker injection for trackerless torrents.
  - **Peer Wire Protocol:** Asynchronous TCP peer state machine managing protocol handshakes, bitfield exchanges, choke/unchoke transitions, and pipelined 16 KiB block requests.
  - **Multi-Torrent Session Manager:** Single-worker event loop command bus managing concurrent multi-torrent lifecycle states (`Idle`, `Checking`, `Downloading`, `Paused`, `Stopped`, `Completed`).

- **Disk & Storage Subsystem:**
  - **Non-Blocking Storage Preparation:** Disk pre-allocation and verification runs offloaded in background worker threads without stalling the network loop or GUI rendering.
  - **Fast-Resume Sidecars:** Verified piece bitfields and file timestamps (`mtime_ns`) persist atomically to `.salix_resume/<info_hash>.json`, enabling instant application restarts without re-hashing multi-gigabyte files.
  - **Lazy Block Allocator:** Optimizes memory usage by instantiating 16 KiB block descriptors on demand.

- **Presentation & Interface:**
  - **DearPyGui Desktop UI:** Real-time transfer queue table, per-torrent inspector, swarm health telemetry, and lifecycle controls (Start, Resume, Pause, Stop).
  - **Native OS File Dialog:** Integrated file selection for loading `.torrent` files directly into the active session queue.
  - **Headless CLI Runner:** Terminal runner with live throughput telemetry and unit test verification suites.

---

## Architecture

SalixTorrent decouples networking and storage business logic from UI rendering:

```text
SalixTorrent/
├── main.py                     # Root entrypoint (CLI & GUI dispatch)
├── foundation_test.py          # Metainfo, Bencode, and SHA-1 unit test suite
├── app/
│   ├── engine/                 # DearPyGui abstraction framework
│   │   ├── gui_engine.py       # Context bootstrap and frame render loop
│   │   ├── master_viewport.py  # Primary window setup and navigation header
│   │   ├── scene_manager.py    # View container registration and lifecycle
│   │   └── texture_manager.py  # Texture and asset pipeline
│   ├── logic/                  # BitTorrent protocol engine
│   │   ├── bencode.py          # Bencode encoder / decoder
│   │   ├── peer.py             # TCP socket framing & state machine
│   │   ├── piece_manager.py    # Block requests, SHA-1 verification & fast-resume
│   │   ├── session.py          # Torrent session coordinator & telemetry emitter
│   │   ├── torrent_file.py     # .torrent parser & fallback tracker provider
│   │   ├── torrent_manager.py  # Unified background async engine & command queue
│   │   └── tracker.py          # HTTP & BEP 0015 UDP tracker client
│   └── views/                  # Presentation layers
│       ├── download_view.py    # Multi-torrent queue & inspector view
│       └── peer_view.py        # Swarm peer monitor
