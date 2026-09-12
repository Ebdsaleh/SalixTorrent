"""Run the non-visual SalixTorrent tranche acceptance sequence.

The repository-level ``validate_tranche.bat`` launcher invokes this module with
its selected Python interpreter.  Commands are passed to ``subprocess`` as
argument lists rather than reconstructed shell strings so Windows paths and
quoting remain deterministic.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import locale
import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_TEST_COUNT = 956


@dataclass(frozen=True)
class ValidationCommand:
    """One non-visual acceptance command and its optional unittest count."""

    label: str
    args: tuple[str, ...]
    expected_test_count: int | None = None


def validation_commands(python_executable: str | Path) -> tuple[ValidationCommand, ...]:
    """Return the ordered post-v0.5.1 Tranche-12 validation sequence."""

    python = str(python_executable)
    return (
        ValidationCommand("Current branch", ("git", "branch", "--show-current")),
        ValidationCommand("Current HEAD", ("git", "rev-parse", "HEAD")),
        ValidationCommand("Published dev", ("git", "rev-parse", "origin/dev")),
        ValidationCommand("Application version", (python, "main.py", "--version")),
        ValidationCommand(
            "Post-v0.5.1 Tranche 5 designer component-palette request surface",
            (python, "-m", "unittest", "tests.presentation.test_designer_component_palette", "-v"),
            expected_test_count=14,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 6 designer component-placement resolver",
            (python, "-m", "unittest", "tests.presentation.test_designer_component_placement", "-v"),
            expected_test_count=16,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 7 designer structural commands and shortcuts",
            (python, "-m", "unittest", "tests.presentation.test_designer_shell_shortcuts", "-v"),
            expected_test_count=16,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 8 designer preview sizing and explicit resize controls",
            (python, "-m", "unittest", "tests.presentation.test_designer_preview_sizing", "-v"),
            expected_test_count=13,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 9 designer pointer resize regression",
            (python, "-m", "unittest", "tests.presentation.test_designer_preview_resize", "-v"),
            expected_test_count=19,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 10 designer reset and numeric scrubbing",
            (
                python, "-m", "unittest",
                "tests.presentation.test_designer_numeric_drag",
                "tests.presentation.test_designer_inspector_panel",
                "-v",
            ),
            expected_test_count=33,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 11 layout autonomy and hierarchy drag/reparent",
            (
                python, "-m", "unittest",
                "tests.presentation.test_designer_layout_autonomy",
                "tests.presentation.test_designer_hierarchy_drag",
                "-v",
            ),
            expected_test_count=23,
        ),
        ValidationCommand(
            "Post-v0.5.1 Tranche 12 live Inspector scrub preview",
            (
                python, "-m", "unittest",
                "tests.presentation.test_designer_inspector_live_preview",
                "-v",
            ),
            expected_test_count=10,
        ),
        ValidationCommand(
            "Torrent detail-menu routing regression",
            (python, "-m", "unittest", "tests.presentation.test_structural_migration", "-v"),
            expected_test_count=6,
        ),
        ValidationCommand(
            "Designer and relocation focus",
            (
                python,
                "-m",
                "unittest",
                "tests.presentation.test_designer_model",
                "tests.presentation.test_designer_editing",
                "tests.presentation.test_designer_structure",
                "tests.presentation.test_designer_preview",
                "tests.presentation.test_designer_preview_host",
                "tests.presentation.test_designer_preview_selection",
                "tests.presentation.test_designer_component_palette",
                "tests.presentation.test_designer_component_placement",
                "tests.presentation.test_designer_shell_shortcuts",
                "tests.presentation.test_designer_preview_sizing",
                "tests.presentation.test_designer_preview_resize",
                "tests.presentation.test_designer_numeric_drag",
                "tests.presentation.test_designer_layout_autonomy",
                "tests.presentation.test_designer_hierarchy_drag",
                "tests.presentation.test_designer_inspector_live_preview",
                "tests.presentation.test_designer_clipboard",
                "tests.presentation.test_designer_selection",
                "tests.presentation.test_designer_project",
                "tests.presentation.test_designer_navigation",
                "tests.presentation.test_designer_hierarchy",
                "tests.presentation.test_designer_hierarchy_panel",
                "tests.presentation.test_designer_inspector",
                "tests.presentation.test_designer_inspector_panel",
                "tests.presentation.test_designer_workspace",
                "tests.presentation.test_designer_shell",
                "tests.presentation.test_designer_shell_menu",
                "tests.packaging.test_framework_packaging",
                "tests.packaging.test_tranche_validation",
                "-v",
            ),
            expected_test_count=344,
        ),
        ValidationCommand(
            "GUI component regression",
            (python, "-m", "unittest", "tests.presentation.test_gui_components", "-v"),
            expected_test_count=64,
        ),
        ValidationCommand(
            "Tkinter live backend regression",
            (python, "-m", "unittest", "tests.presentation.test_tkinter_backend", "-v"),
            expected_test_count=46,
        ),
        ValidationCommand(
            "Localization extraction check",
            (python, "tools/localization/build_locales.py", "--check"),
        ),
        ValidationCommand(
            "Canonical unittest discovery",
            (python, "-m", "unittest", "discover", "-s", "tests", "-t", "."),
            expected_test_count=DISCOVERY_TEST_COUNT,
        ),
        ValidationCommand(
            "Plain unittest discovery",
            (python, "-m", "unittest", "discover"),
            expected_test_count=DISCOVERY_TEST_COUNT,
        ),
        ValidationCommand(
            "Headless ecosystem proof",
            (python, "examples/ecosystem_blank_app.py", "--ui-backend", "headless"),
        ),
        ValidationCommand(
            "Python compileall",
            (python, "-m", "compileall", "-q", "app", "tests", "examples"),
        ),
        ValidationCommand("Git whitespace check", ("git", "diff", "--check")),
        ValidationCommand("Git working-tree status", ("git", "status", "--short")),
    )


def default_report_path() -> Path:
    """Return the requested Desktop report destination."""

    profile = os.environ.get("USERPROFILE")
    desktop_root = Path(profile) if profile else Path.home()
    return desktop_root / "Desktop" / "console_output.txt"


def _timestamp() -> str:
    return _datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _write_line(report: TextIO, text: str = "") -> None:
    print(text)
    report.write(text + "\n")
    report.flush()


def _command_text(args: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(args))


def _observed_test_count(output: str) -> int | None:
    matches = re.findall(r"\bRan\s+(\d+)\s+tests?\b", output)
    return int(matches[-1]) if matches else None


def _run_command(command: ValidationCommand, report: TextIO) -> bool:
    _write_line(report)
    _write_line(report, f"---------------- {command.label} ----------------")
    _write_line(report, f" { _command_text(command.args) }")

    encoding = locale.getpreferredencoding(False) or "utf-8"
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    captured: list[str] = []

    try:
        process = subprocess.Popen(
            command.args,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
            env=env,
        )
    except OSError as exc:
        _write_line(report, f"Unable to start command: {exc}")
        _write_line(report, "Exit code: launch-failed")
        return False

    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip("\r\n")
        captured.append(line)
        _write_line(report, text)

    return_code = process.wait()
    _write_line(report, f"Exit code: {return_code}")

    passed = return_code == 0
    if command.expected_test_count is not None:
        output = "".join(captured)
        observed = _observed_test_count(output)
        _write_line(
            report,
            "Test-count check: "
            f"expected={command.expected_test_count}, "
            f"observed={observed if observed is not None else 'not found'}",
        )
        if observed != command.expected_test_count:
            passed = False

    return passed


def run_validation(report_path: Path) -> int:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    failed_labels: list[str] = []

    with report_path.open("w", encoding="utf-8", newline="\n") as report:
        _write_line(report, "============================================================")
        _write_line(report, " SalixTorrent Tranche Validation")
        _write_line(report, "============================================================")
        _write_line(report, f"Repository : {PROJECT_ROOT}")
        _write_line(report, f"Report     : {report_path}")
        _write_line(report, f"Python     : {sys.executable}")
        _write_line(report, f"Started    : {_timestamp()}")
        _write_line(report)

        for command in validation_commands(sys.executable):
            if not _run_command(command, report):
                failed_labels.append(command.label)

        _write_line(report)
        _write_line(report, "============================================================")
        _write_line(report, " Manual visual checks still required")
        _write_line(report, "============================================================")
        _write_line(report, "Dear PyGui blank app:")
        _write_line(report, r"  python examples\ecosystem_blank_app.py --ui-backend dearpygui")
        _write_line(report, "Tkinter blank app:")
        _write_line(report, r"  python examples\ecosystem_blank_app.py --ui-backend tkinter")
        _write_line(report, "Designer shell + palette + placement + structural commands/shortcuts + preview sizing + pointer resize + numeric scrub/reset + live scrub preview + independent child sizing + hierarchy drag/reparent + inspector + clickable preview Dear PyGui smoke:")
        _write_line(report, r"  python examples\ecosystem_designer_shell.py --ui-backend dearpygui")
        _write_line(report, "Designer shell + palette + placement + structural commands/shortcuts + preview sizing + pointer resize + numeric scrub/reset + live scrub preview + independent child sizing + hierarchy drag/reparent + inspector + clickable preview Tkinter smoke:")
        _write_line(report, r"  python examples\ecosystem_designer_shell.py --ui-backend tkinter")
        _write_line(report, "SalixTorrent Dear PyGui smoke:")
        _write_line(report, "  python main.py")
        _write_line(report)

        if failed_labels:
            _write_line(report, "Failed sections:")
            for label in failed_labels:
                _write_line(report, f"  - {label}")
            _write_line(report)
            _write_line(report, "============================================================")
            _write_line(report, " TRANCHE VALIDATION FAILED")
            _write_line(report, "============================================================")
            _write_line(report, f"Finished   : {_timestamp()}")
            return 1

        _write_line(report, "============================================================")
        _write_line(report, " TRANCHE VALIDATION PASSED")
        _write_line(report, "============================================================")
        _write_line(report, f"Finished   : {_timestamp()}")
        return 0


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=default_report_path(),
        help="override the default Desktop console_output.txt destination",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_validation(args.report.resolve())
    print()
    print("Saved complete output to:")
    print(f"  {args.report.resolve()}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
