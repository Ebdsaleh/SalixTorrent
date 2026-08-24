# main.py

import argparse
import asyncio
import queue

from app.engine.master_viewport import MasterViewport
from app.logic.torrent_manager import TorrentManager


def main():
    parser = argparse.ArgumentParser(
        description="SalixTorrent (Salix_T) BitTorrent Client"
    )
    parser.add_argument(
        "torrent",
        nargs="?",
        default=None,
        help="Optional path to a .torrent file to open at launch",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in headless CLI mode",
    )
    parser.add_argument(
        "--max-peers",
        type=int,
        default=25,
        help="Maximum concurrent peer connections",
    )
    args = parser.parse_args()

    ui_queue = queue.Queue()
    manager = TorrentManager(ui_queue=ui_queue)

    if args.cli:
        # Preserve the old CLI convenience: without an explicit path the CLI
        # still uses test.torrent. CLI runs are intentionally not added to the
        # desktop application's persistent transfer queue.
        torrent_path = args.torrent or "test.torrent"
        print("Launching Salix_T in Headless CLI Mode...")
        session = manager.add_torrent(
            torrent_path,
            max_peers=args.max_peers,
            persist=False,
        )
        asyncio.run(session.start())
        return

    print("Launching Salix_T DearPyGui Desktop Interface...")
    manager.start_engine()

    try:
        # Restore saved queue order, transfer limits, paused/stopped state and
        # automatically restart torrents that were active when Salix_T closed.
        manager.restore_previous_session()

        # Supplying an explicit .torrent on the command line opens it in
        # addition to the restored session and marks it active.
        if args.torrent:
            try:
                session = manager.add_torrent(
                    args.torrent,
                    max_peers=args.max_peers,
                )
                manager.set_selected_torrent(session.torrent.hex_info_hash)
                manager.start_torrent(session.torrent.hex_info_hash)
            except Exception as exc:
                print(f"[Salix_T Notice] Could not load torrent: {exc}")

        # Run UI on the main thread.
        viewport = MasterViewport(ui_queue=ui_queue)
        viewport.run()

    finally:
        # Save the user's intended lifecycle state BEFORE shutting networking
        # down. Active torrents therefore come back active on the next launch.
        manager.shutdown()


if __name__ == "__main__":
    main()
