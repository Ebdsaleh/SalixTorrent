# main.py

import argparse
import asyncio
import queue
from app.logic.torrent_manager import TorrentManager
from app.engine.master_viewport import MasterViewport


def main():
    parser = argparse.ArgumentParser(description="SalixTorrent (Salix_T) BitTorrent Client")
    parser.add_argument("torrent", nargs="?", default="test.torrent", help="Path to .torrent file")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI mode")
    parser.add_argument("--max-peers", type=int, default=25, help="Maximum concurrent peer connections")
    args = parser.parse_args()

    ui_queue = queue.Queue()
    manager = TorrentManager(ui_queue=ui_queue)

    if args.cli:
        print(f"Launching Salix_T in Headless CLI Mode...")
        session = manager.add_torrent(args.torrent, max_peers=args.max_peers)
        asyncio.run(session.start())
    else:
        print(f"Launching Salix_T DearPyGui Desktop Interface...")
        # Start unified async background engine
        manager.start_engine()

        # Enqueue default torrent if file exists
        if args.torrent:
            try:
                session = manager.add_torrent(args.torrent, max_peers=args.max_peers)
                manager.start_torrent(session.torrent.hex_info_hash)
            except Exception as e:
                print(f"[Salix_T Notice] Could not load default torrent: {e}")

        # Run UI on main thread
        viewport = MasterViewport(ui_queue=ui_queue)
        viewport.run()


if __name__ == "__main__":
    main()
