"""Windows .torrent and magnet shell registration for Phase 10.

Registration is intentionally per-user (HKCU\\Software\\Classes) so portable
builds do not require elevation. The .torrent handler is advertised through a
unique ProgID/OpenWithProgids entry instead of silently stealing another
client's default. The magnet scheme is single-owner on Windows, so SalixTorrent
backs up the previous handler and restores it only when it still owns the
scheme at unregister time.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

from app.engine.runtime_paths import application_directory, is_frozen, state_directory


TORRENT_PROGID = "SalixTorrent.Torrent"
TORRENT_EXTENSION = ".torrent"
MAGNET_SCHEME = "magnet"
_CLASSES_ROOT = r"Software\Classes"
_BACKUP_FILE = "shell_integration_backup.json"


def _quoted(value: object) -> str:
    text = str(value)
    # Windows filenames cannot contain a literal quote, so conventional shell
    # registry quoting is sufficient and preserves spaces and URI '&' content.
    return f'"{text}"'


def launch_prefix() -> tuple[str, ...]:
    """Return the executable/script sequence Windows should launch."""
    if is_frozen():
        return (str(Path(sys.executable).resolve()),)
    main_script = application_directory() / "main.py"
    return (str(Path(sys.executable).resolve()), str(main_script.resolve()))


def open_command(target_placeholder: str = "%1") -> str:
    return " ".join(_quoted(part) for part in (*launch_prefix(), target_placeholder))


def icon_command() -> str:
    return f"{_quoted(launch_prefix()[0])},0"


@dataclass(frozen=True)
class ShellIntegrationStatus:
    supported: bool
    torrent_handler_registered: bool
    magnet_handler_registered: bool
    launch_command: str
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ShellIntegration:
    """Small dependency-free Windows shell-registration service."""

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    @staticmethod
    def _backup_path() -> Path:
        return state_directory() / _BACKUP_FILE

    @staticmethod
    def _normalise_command(value: object) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @classmethod
    def _command_matches_current_app(cls, value: object) -> bool:
        return cls._normalise_command(value) == cls._normalise_command(open_command())

    @staticmethod
    def _winreg():
        if os.name != "nt":
            return None
        import winreg
        return winreg

    @classmethod
    def _read_default(cls, subkey: str) -> Optional[str]:
        winreg = cls._winreg()
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES_ROOT}\\{subkey}") as key:
                value, _kind = winreg.QueryValueEx(key, "")
                return str(value)
        except OSError:
            return None

    @classmethod
    def _value_exists(cls, subkey: str, value_name: str) -> bool:
        winreg = cls._winreg()
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES_ROOT}\\{subkey}") as key:
                winreg.QueryValueEx(key, value_name)
            return True
        except OSError:
            return False

    @classmethod
    def _set_string(cls, subkey: str, value_name: str, value: str):
        winreg = cls._winreg()
        if winreg is None:
            raise RuntimeError("Windows shell integration is not available on this platform.")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES_ROOT}\\{subkey}") as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(value))

    @classmethod
    def _delete_value(cls, subkey: str, value_name: str):
        winreg = cls._winreg()
        if winreg is None:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                f"{_CLASSES_ROOT}\\{subkey}",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, value_name)
        except OSError:
            pass

    @classmethod
    def _delete_tree(cls, subkey: str):
        winreg = cls._winreg()
        if winreg is None:
            return
        path = f"{_CLASSES_ROOT}\\{subkey}"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                path,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE,
            ) as key:
                children = []
                index = 0
                while True:
                    try:
                        children.append(winreg.EnumKey(key, index))
                        index += 1
                    except OSError:
                        break
            for child in children:
                cls._delete_tree(f"{subkey}\\{child}")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    @classmethod
    def _notify_shell_changed(cls):
        if os.name != "nt":
            return
        try:
            import ctypes

            SHCNE_ASSOCCHANGED = 0x08000000
            SHCNF_IDLIST = 0x0000
            ctypes.windll.shell32.SHChangeNotify(
                SHCNE_ASSOCCHANGED,
                SHCNF_IDLIST,
                None,
                None,
            )
        except Exception:
            pass

    def status(self) -> ShellIntegrationStatus:
        if not self.supported:
            return ShellIntegrationStatus(
                supported=False,
                torrent_handler_registered=False,
                magnet_handler_registered=False,
                launch_command=open_command(),
                message="Windows shell registration is available only on Windows.",
            )

        torrent_command = self._read_default(f"{TORRENT_PROGID}\\shell\\open\\command")
        torrent_openwith = self._value_exists(
            f"{TORRENT_EXTENSION}\\OpenWithProgids",
            TORRENT_PROGID,
        )
        magnet_command = self._read_default(f"{MAGNET_SCHEME}\\shell\\open\\command")
        return ShellIntegrationStatus(
            supported=True,
            torrent_handler_registered=bool(
                torrent_openwith and self._command_matches_current_app(torrent_command)
            ),
            magnet_handler_registered=self._command_matches_current_app(magnet_command),
            launch_command=open_command(),
        )

    def register_torrent_handler(self) -> bool:
        if not self.supported:
            return False
        self._set_string(TORRENT_PROGID, "", "BitTorrent Metainfo")
        self._set_string(f"{TORRENT_PROGID}\\DefaultIcon", "", icon_command())
        self._set_string(
            f"{TORRENT_PROGID}\\shell\\open\\command",
            "",
            open_command(),
        )
        self._set_string(
            f"{TORRENT_EXTENSION}\\OpenWithProgids",
            TORRENT_PROGID,
            "",
        )
        self._notify_shell_changed()
        return True

    def unregister_torrent_handler(self) -> bool:
        if not self.supported:
            return False
        command = self._read_default(f"{TORRENT_PROGID}\\shell\\open\\command")
        if self._command_matches_current_app(command):
            self._delete_value(f"{TORRENT_EXTENSION}\\OpenWithProgids", TORRENT_PROGID)
            self._delete_tree(TORRENT_PROGID)
            self._notify_shell_changed()
        return True

    @classmethod
    def _read_magnet_backup(cls) -> Dict[str, object]:
        path = cls._backup_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return dict(raw) if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    @classmethod
    def _write_magnet_backup(cls, data: Dict[str, object]):
        path = cls._backup_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            pass

    def _capture_existing_magnet_handler(self):
        current = self._read_default(f"{MAGNET_SCHEME}\\shell\\open\\command")
        if not current or self._command_matches_current_app(current):
            return
        # Preserve the small standard URL-protocol surface SalixTorrent changes.
        backup = {
            "description": self._read_default(MAGNET_SCHEME),
            "url_protocol_present": self._value_exists(MAGNET_SCHEME, "URL Protocol"),
            "icon": self._read_default(f"{MAGNET_SCHEME}\\DefaultIcon"),
            "command": current,
        }
        self._write_magnet_backup(backup)

    def register_magnet_handler(self) -> bool:
        if not self.supported:
            return False
        self._capture_existing_magnet_handler()
        self._set_string(MAGNET_SCHEME, "", "URL:Magnet Protocol")
        self._set_string(MAGNET_SCHEME, "URL Protocol", "")
        self._set_string(f"{MAGNET_SCHEME}\\DefaultIcon", "", icon_command())
        self._set_string(
            f"{MAGNET_SCHEME}\\shell\\open\\command",
            "",
            open_command(),
        )
        self._notify_shell_changed()
        return True

    def unregister_magnet_handler(self) -> bool:
        if not self.supported:
            return False
        current = self._read_default(f"{MAGNET_SCHEME}\\shell\\open\\command")
        if not self._command_matches_current_app(current):
            return True

        backup = self._read_magnet_backup()
        previous_command = str(backup.get("command") or "").strip()
        if previous_command:
            self._set_string(MAGNET_SCHEME, "", str(backup.get("description") or "URL:Magnet Protocol"))
            if backup.get("url_protocol_present", True):
                self._set_string(MAGNET_SCHEME, "URL Protocol", "")
            else:
                self._delete_value(MAGNET_SCHEME, "URL Protocol")
            previous_icon = str(backup.get("icon") or "").strip()
            if previous_icon:
                self._set_string(f"{MAGNET_SCHEME}\\DefaultIcon", "", previous_icon)
            else:
                self._delete_tree(f"{MAGNET_SCHEME}\\DefaultIcon")
            self._set_string(
                f"{MAGNET_SCHEME}\\shell\\open\\command",
                "",
                previous_command,
            )
        else:
            self._delete_tree(MAGNET_SCHEME)

        try:
            self._backup_path().unlink(missing_ok=True)
        except OSError:
            pass
        self._notify_shell_changed()
        return True
