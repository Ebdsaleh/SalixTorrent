# main.py

import argparse
import queue

from app.version import APP_NAME, APP_VERSION


def main():
    parser = argparse.ArgumentParser(
        description="SalixTorrent (Salix_T) BitTorrent Client"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
    )
    parser.add_argument(
        "torrent",
        nargs="?",
        default=None,
        help="Optional .torrent path or magnet URI to open at launch",
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
    parser.add_argument(
        "--download-dir",
        default=None,
        help="Override the download directory for this launch",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=1.0,
        help="Headless status output interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--json-status",
        action="store_true",
        help="Emit headless progress/status as JSON Lines",
    )
    parser.add_argument(
        "--exit-on-complete",
        action="store_true",
        help="In headless mode, exit after the download becomes complete instead of continuing to seed",
    )
    args = parser.parse_args()

    # Defer engine/UI imports until after argument parsing so lightweight
    # commands such as --version do not require Dear PyGui to be imported.
    try:
        from app.logic.torrent_manager import TorrentManager
        from app.logic.transfer_add import TransferAddRequest
    except KeyboardInterrupt:
        # Ctrl+C during a cold CLI import should still be a quiet conventional
        # shell interruption rather than a Python traceback. No engine exists
        # yet, so there is nothing to tear down at this point.
        if args.cli:
            raise SystemExit(130)
        raise

    event_queue = queue.Queue()

    if args.cli:
        # A headless process deliberately does not read/write the desktop
        # transfer queue. It can still reuse ordinary application preferences
        # such as networking policy and the default download location.
        manager = TorrentManager(
            event_queue=event_queue,
            session_persistence_enabled=False,
        )
        source = args.torrent or "test.torrent"
        if not args.json_status:
            print("Launching Salix_T in Headless CLI Mode...")

        from app.cli.headless import HeadlessOptions, HeadlessRunner

        runner = HeadlessRunner(manager, event_queue)
        exit_code = runner.run(
            source,
            HeadlessOptions(
                max_peers=max(1, int(args.max_peers)),
                download_dir=args.download_dir,
                status_interval=max(0.1, float(args.status_interval)),
                json_status=bool(args.json_status),
                exit_on_complete=bool(args.exit_on_complete),
            ),
        )
        raise SystemExit(exit_code)

    manager = TorrentManager(event_queue=event_queue)
    print("Launching Salix_T DearPyGui Desktop Interface...")
    manager.start_engine()

    try:
        # Restore saved queue order, transfer limits, paused/stopped state and
        # automatically restart torrents that were active when Salix_T closed.
        manager.restore_previous_session()

        # An explicit startup target uses the exact same add path as Open
        # Torrent/Open Magnet and the headless CLI.
        if args.torrent:
            try:
                handle = manager.add_transfer(
                    TransferAddRequest(
                        source=str(args.torrent).strip(),
                        start=True,
                        persist=True,
                        max_peers=max(1, int(args.max_peers)),
                        download_dir=args.download_dir,
                    )
                )
                if handle.info_hash:
                    manager.set_selected_torrent(handle.info_hash)
            except Exception as exc:
                print(f"[Salix_T Notice] Could not load torrent: {exc}")

        # Run UI on the main thread. Import Dear PyGui only for desktop mode.
        from app.engine.master_viewport import MasterViewport

        viewport = MasterViewport(ui_queue=event_queue)
        viewport.run()

    finally:
        # Save the user's intended lifecycle state BEFORE shutting networking
        # down. Active torrents therefore come back active on the next launch.
        manager.shutdown()


if __name__ == "__main__":
    main()
