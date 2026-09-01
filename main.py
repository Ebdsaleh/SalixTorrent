# main.py

import argparse
import json
import os
import queue
from typing import Optional

from app.localization import localization_manager, tr, tr_value
from app.version import APP_NAME, APP_VERSION


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=tr("cli.parser.description", "SalixTorrent (Salix_T) BitTorrent Client")
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
        help=tr("cli.parser.torrent", "Optional .torrent path or magnet URI to open at launch"),
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help=tr("cli.parser.headless", "Run in headless CLI mode"),
    )
    parser.add_argument(
        "--max-peers",
        type=int,
        default=25,
        help=tr("cli.parser.max_peers", "Maximum concurrent peer connections"),
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help=tr("cli.parser.download_dir", "Override the download directory for this launch"),
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=1.0,
        help=tr("cli.parser.status_interval", "Headless status output interval in seconds (default: 1.0)"),
    )
    parser.add_argument(
        "--json-status",
        action="store_true",
        help=tr("cli.parser.json_status", "Emit headless progress/status as JSON Lines"),
    )
    parser.add_argument(
        "--exit-on-complete",
        action="store_true",
        help=tr("cli.parser.exit_complete", "In headless mode, exit after the download becomes complete instead of continuing to seed"),
    )

    # Phase 10 runtime/desktop integration controls. These are intentionally
    # handled before TorrentManager/Dear PyGui imports so the installer can use
    # the frozen executable as a lightweight registration helper.
    parser.add_argument(
        "--portable",
        action="store_true",
        help=tr("cli.parser.portable", "Store SalixTorrent state/download defaults beside the executable for this launch"),
    )
    parser.add_argument(
        "--shell-status",
        action="store_true",
        help=tr("cli.parser.shell_status", "Report Windows .torrent/magnet handler registration status and exit"),
    )
    parser.add_argument(
        "--register-torrent-handler",
        action="store_true",
        help=tr("cli.parser.register_torrent", "Register SalixTorrent as a per-user .torrent handler and exit"),
    )
    parser.add_argument(
        "--unregister-torrent-handler",
        action="store_true",
        help=tr("cli.parser.unregister_torrent", "Remove this SalixTorrent executable's per-user .torrent handler and exit"),
    )
    parser.add_argument(
        "--register-magnet-handler",
        action="store_true",
        help=tr("cli.parser.register_magnet", "Register this SalixTorrent executable for magnet: links and exit"),
    )
    parser.add_argument(
        "--unregister-magnet-handler",
        action="store_true",
        help=tr("cli.parser.unregister_magnet", "Restore/remove this SalixTorrent executable's magnet: handler and exit"),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _handle_phase10_commands(args: argparse.Namespace) -> Optional[int]:
    if args.portable:
        # Must be set before TorrentManager/runtime_paths is imported.
        os.environ["SALIX_T_PORTABLE"] = "1"

    requested = any(
        (
            args.shell_status,
            args.register_torrent_handler,
            args.unregister_torrent_handler,
            args.register_magnet_handler,
            args.unregister_magnet_handler,
        )
    )
    if not requested:
        return None

    from app.engine.shell_integration import ShellIntegration

    shell = ShellIntegration()
    operation_requested = False
    success = True

    if args.register_torrent_handler:
        operation_requested = True
        success = shell.register_torrent_handler() and success
    if args.unregister_torrent_handler:
        operation_requested = True
        success = shell.unregister_torrent_handler() and success
    if args.register_magnet_handler:
        operation_requested = True
        success = shell.register_magnet_handler() and success
    if args.unregister_magnet_handler:
        operation_requested = True
        success = shell.unregister_magnet_handler() and success

    status = shell.status()
    if args.shell_status and not args.quiet:
        print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
    elif operation_requested and not args.quiet:
        if not status.supported:
            print(status.message)
        else:
            print(
                tr(
                    "cli.shell.integration_status",
                    "SalixTorrent shell integration: .torrent={torrent}, magnet={magnet}",
                    torrent=tr_value("Registered" if status.torrent_handler_registered else "Not registered"),
                    magnet=tr_value("Registered" if status.magnet_handler_registered else "Not registered"),
                )
            )

    if operation_requested and (not shell.supported or not success):
        return 2
    return 0


def main():
    parser = _build_argument_parser()
    args = parser.parse_args()

    phase10_exit = _handle_phase10_commands(args)
    if phase10_exit is not None:
        raise SystemExit(phase10_exit)

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
        localization_manager().configure(manager.get_app_settings().get("language", "auto"))
        source = args.torrent or "test.torrent"
        if not args.json_status:
            print(tr("cli.launch.headless", "Launching Salix_T in Headless CLI Mode..."))

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
    localization_manager().configure(manager.get_app_settings().get("language", "auto"))
    print(tr("cli.launch.desktop", "Launching Salix_T DearPyGui Desktop Interface..."))
    manager.start_engine()

    try:
        # Restore saved queue order, transfer limits, paused/stopped state and
        # automatically restart torrents that were active when Salix_T closed.
        manager.restore_previous_session()

        # An explicit startup target uses the exact same add path as Open
        # Torrent/Open Magnet and the headless CLI. This is also what Windows
        # file/URL handlers invoke in frozen builds.
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
