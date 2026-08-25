# app/views/settings_view.py

import os
import tkinter as tk
from tkinter import filedialog

import dearpygui.dearpygui as dpg

from app.logic.torrent_manager import TorrentManager


class SettingsView:
    """Application preferences that are safe to change without dependencies."""

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.settings = self.manager.get_app_settings()

    def build_view(self, parent_tag):
        with dpg.group(parent=parent_tag):
            dpg.add_text("PREFERENCES", color=(0, 255, 128))
            dpg.add_text(
                "Defaults apply to newly added torrents. Existing torrents keep their own "
                "storage path, limits and file priorities.",
                color=(155, 155, 160),
            )
            dpg.add_spacer(height=6)

            with dpg.child_window(height=115, border=True):
                dpg.add_text("DOWNLOADS", color=(100, 180, 255))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    dpg.add_text("Default download directory")
                    self.download_dir_input = dpg.add_input_text(
                        default_value=self.settings["download_dir"],
                        width=700,
                    )
                    dpg.add_button(label=" Choose Folder ", callback=self._choose_download_dir)

            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                with dpg.child_window(width=520, height=210, border=True):
                    dpg.add_text("QUEUE & CONNECTIONS", color=(255, 200, 100))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text("Active download slots")
                        self.active_slots_input = dpg.add_input_int(
                            default_value=int(self.settings["max_active_downloads"]),
                            min_value=0,
                            min_clamped=True,
                            width=90,
                        )
                        dpg.add_text("0 = Unlimited", color=(150, 150, 150))

                    with dpg.group(horizontal=True):
                        dpg.add_text("Default max peers")
                        self.max_peers_input = dpg.add_input_int(
                            default_value=int(self.settings["default_max_peers"]),
                            min_value=1,
                            max_value=500,
                            min_clamped=True,
                            max_clamped=True,
                            width=90,
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_text("Default queue priority")
                        self.default_priority_combo = dpg.add_combo(
                            items=["High", "Normal", "Low"],
                            default_value=self.settings["default_queue_priority"],
                            width=130,
                        )

                    self.auto_resume_checkbox = dpg.add_checkbox(
                        label="Resume torrents that were active when SalixTorrent closed",
                        default_value=bool(self.settings["auto_resume_active"]),
                    )
                    self.completion_notifications_checkbox = dpg.add_checkbox(
                        label="Show in-app download completion notices",
                        default_value=bool(self.settings["completion_notifications"]),
                    )

                with dpg.child_window(width=-1, height=210, border=True):
                    dpg.add_text("NEW TORRENT TRANSFER DEFAULTS", color=(180, 160, 255))
                    dpg.add_separator()
                    dpg.add_text(
                        "These are per-torrent defaults. 0 means Unlimited.",
                        color=(150, 150, 150),
                    )
                    with dpg.group(horizontal=True):
                        dpg.add_text("Download")
                        self.download_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["default_download_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.download_limit_unit = dpg.add_combo(
                            items=["KB/s", "MB/s", "kbps", "Mbps"],
                            default_value=self.settings["default_download_limit_unit"],
                            width=90,
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_text("Upload   ")
                        self.upload_limit_input = dpg.add_input_float(
                            default_value=float(self.settings["default_upload_limit_value"]),
                            min_value=0.0,
                            min_clamped=True,
                            format="%.2f",
                            width=110,
                        )
                        self.upload_limit_unit = dpg.add_combo(
                            items=["KB/s", "MB/s", "kbps", "Mbps"],
                            default_value=self.settings["default_upload_limit_unit"],
                            width=90,
                        )

            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_button(label=" Save Preferences ", callback=self._save)
                dpg.add_button(label=" Restore Defaults ", callback=self._restore_defaults)
                self.status_text = dpg.add_text("", color=(0, 255, 128))

            dpg.add_spacer(height=10)
            dpg.add_text(
                f"Settings file: {self.manager.settings_path}",
                color=(130, 130, 135),
            )

    def _choose_download_dir(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = str(dpg.get_value(self.download_dir_input) or os.getcwd())
        folder = filedialog.askdirectory(
            title="Choose Default Download Directory",
            initialdir=initial if os.path.isdir(initial) else os.getcwd(),
        )
        root.destroy()
        if folder:
            dpg.set_value(self.download_dir_input, os.path.abspath(folder))

    def _collect(self) -> dict:
        return {
            "download_dir": str(dpg.get_value(self.download_dir_input) or "downloads"),
            "default_max_peers": int(dpg.get_value(self.max_peers_input) or 25),
            "max_active_downloads": int(dpg.get_value(self.active_slots_input) or 0),
            "auto_resume_active": bool(dpg.get_value(self.auto_resume_checkbox)),
            "completion_notifications": bool(
                dpg.get_value(self.completion_notifications_checkbox)
            ),
            "default_download_limit_value": float(
                dpg.get_value(self.download_limit_input) or 0.0
            ),
            "default_download_limit_unit": str(
                dpg.get_value(self.download_limit_unit) or "KB/s"
            ),
            "default_upload_limit_value": float(
                dpg.get_value(self.upload_limit_input) or 0.0
            ),
            "default_upload_limit_unit": str(
                dpg.get_value(self.upload_limit_unit) or "KB/s"
            ),
            "default_queue_priority": str(
                dpg.get_value(self.default_priority_combo) or "Normal"
            ),
        }

    def _sync_controls(self, settings: dict):
        self.settings = dict(settings)
        dpg.set_value(self.download_dir_input, settings["download_dir"])
        dpg.set_value(self.max_peers_input, settings["default_max_peers"])
        dpg.set_value(self.active_slots_input, settings["max_active_downloads"])
        dpg.set_value(self.auto_resume_checkbox, settings["auto_resume_active"])
        dpg.set_value(
            self.completion_notifications_checkbox,
            settings["completion_notifications"],
        )
        dpg.set_value(
            self.download_limit_input,
            settings["default_download_limit_value"],
        )
        dpg.set_value(
            self.download_limit_unit,
            settings["default_download_limit_unit"],
        )
        dpg.set_value(self.upload_limit_input, settings["default_upload_limit_value"])
        dpg.set_value(self.upload_limit_unit, settings["default_upload_limit_unit"])
        dpg.set_value(self.default_priority_combo, settings["default_queue_priority"])

    def _save(self):
        settings = self.manager.update_app_settings(self._collect())
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Preferences saved")

    def _restore_defaults(self):
        settings = self.manager.reset_app_settings()
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "Defaults restored")

    def on_show(self, **kwargs):
        settings = self.manager.get_app_settings()
        settings["max_active_downloads"] = self.manager.get_max_active_downloads()
        self._sync_controls(settings)
        dpg.set_value(self.status_text, "")

    def update(self, delta_time: float):
        pass
