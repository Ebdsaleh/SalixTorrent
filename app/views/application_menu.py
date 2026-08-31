# app/views/application_menu.py

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import dearpygui.dearpygui as dpg

from app.logic.network_binding import format_endpoint
from app.engine.responsive_layout import DialogMetrics, ResponsiveLayout
from app.logic.torrent_manager import TorrentManager
from app.version import APP_VERSION
from app.views.help_terms import add_help_tooltip, add_text_tooltip


class ApplicationMenu:
    """Traditional desktop application menu for SalixTorrent.

    The menu is a real ``mvMenuBar`` child of SalixTorrent's primary content
    window. Unlike a viewport overlay, a window menu bar participates in the
    layout and reserves its own vertical space, so the application toolbar is
    never hidden underneath it.

    All callbacks stay on SalixTorrent's existing Dear PyGui callback path, so
    the main-thread callback serialization added to GuiEngine still applies.
    """

    APP_VERSION = APP_VERSION
    _STATE_REFRESH_INTERVAL = 0.20

    def __init__(self, gui, download_view, create_torrent_view, settings_view, help_topics_view):
        self.gui = gui
        self.manager = TorrentManager.get_instance()
        self.download_view = download_view
        self.create_torrent_view = create_torrent_view
        self.settings_view = settings_view
        self.help_topics_view = help_topics_view

        self._last_state_signature = None
        self._last_state_refresh = 0.0
        self._shortcut_registry = None
        self.layout = ResponsiveLayout.get_instance()

        self._scene_items = {}
        self._detail_items = {}
        self._priority_items = {}
        self._torrent_action_items = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_menu_bar(self, parent: str = "primary_window"):
        """Create the menu bar as the first child of the primary window."""
        with dpg.menu_bar(tag="salix_application_menu_bar", parent=parent):
            self._build_file_menu()
            self._build_edit_menu()
            self._build_view_menu()
            self._build_transfers_menu()
            self._build_tools_menu()
            self._build_help_menu()

    def finish_build(self):
        """Build non-menu support widgets after all application views exist."""
        self._build_shortcut_handler()
        self._build_help_windows()
        self.update(force=True)

    def build(self, parent: str = "primary_window"):
        """Compatibility helper for callers that do not need two-phase build."""
        self.build_menu_bar(parent=parent)
        self.finish_build()

    def _build_file_menu(self):
        with dpg.menu(label="File"):
            open_torrent_item = dpg.add_menu_item(
                label="Open Torrent...",
                shortcut="Ctrl+O",
                callback=self._open_torrent,
            )
            add_help_tooltip(open_torrent_item, "OPEN_TORRENT")
            open_magnet_item = dpg.add_menu_item(
                label="Open Magnet Link...",
                shortcut="Ctrl+M",
                callback=self._open_magnet,
            )
            add_help_tooltip(open_magnet_item, "OPEN_MAGNET")
            dpg.add_separator()
            create_torrent_item = dpg.add_menu_item(
                label="Create Torrent...",
                shortcut="Ctrl+N",
                callback=lambda: self._switch_scene("CreateTorrentView"),
            )
            add_help_tooltip(create_torrent_item, "CREATE_TORRENT")
            dpg.add_separator()
            dpg.add_menu_item(
                label="Exit",
                shortcut="Alt+F4",
                callback=lambda: dpg.stop_dearpygui(),
            )

    def _build_edit_menu(self):
        with dpg.menu(label="Edit"):
            self._torrent_action_items["copy_hash"] = dpg.add_menu_item(
                label="Copy Info Hash",
                callback=self._copy_info_hash,
            )
            self._torrent_action_items["copy_magnet"] = dpg.add_menu_item(
                label="Copy Magnet Link",
                callback=self._copy_magnet,
            )
            add_help_tooltip(self._torrent_action_items["copy_hash"], "COPY_INFO_HASH")
            add_help_tooltip(self._torrent_action_items["copy_magnet"], "COPY_MAGNET")
            dpg.add_separator()
            find_item = dpg.add_menu_item(
                label="Find Torrents...",
                shortcut="Ctrl+F",
                callback=self._focus_torrent_search,
            )
            add_help_tooltip(find_item, "QUEUE_SEARCH")
            clear_item = dpg.add_menu_item(
                label="Clear Search / Filter",
                callback=self._clear_filters,
            )
            add_help_tooltip(clear_item, "QUEUE_STATUS_FILTER")
            restore_order_item = dpg.add_menu_item(
                label="Restore Queue Order",
                callback=self._restore_queue_order,
            )
            add_help_tooltip(restore_order_item, "QUEUE_ORDER")

    def _build_view_menu(self):
        with dpg.menu(label="View"):
            self._scene_items["DownloadView"] = dpg.add_menu_item(
                label="Active Transfers",
                shortcut="Ctrl+1",
                check=True,
                callback=lambda: self._switch_scene("DownloadView"),
            )
            self._scene_items["CreateTorrentView"] = dpg.add_menu_item(
                label="Create Torrent",
                shortcut="Ctrl+2",
                check=True,
                callback=lambda: self._switch_scene("CreateTorrentView"),
            )
            self._scene_items["SettingsView"] = dpg.add_menu_item(
                label="Preferences",
                shortcut="Ctrl+3",
                check=True,
                callback=lambda: self._switch_scene("SettingsView"),
            )
            add_help_tooltip(self._scene_items["DownloadView"], "ACTIVE_TRANSFERS_VIEW")
            add_help_tooltip(self._scene_items["CreateTorrentView"], "CREATE_TORRENT")
            add_help_tooltip(self._scene_items["SettingsView"], "PREFERENCES_VIEW")

            dpg.add_separator()
            with dpg.menu(label="Torrent Details"):
                for name in ("General", "Peers", "Pieces", "Files", "Sources", "Speed"):
                    self._detail_items[name] = dpg.add_menu_item(
                        label=name,
                        check=True,
                        callback=lambda s, a, u=name: self._show_detail_tab(u),
                    )
            detail_help = {
                "General": "Overall transfer, swarm, connectivity and torrent metadata for the selected torrent.",
                "Peers": "Live peer connections, client identity, discovery source, direction, rates and protocol state.",
                "Pieces": "Piece verification map, block progress and per-piece availability from connected peers.",
                "Files": "Per-file verified progress, storage information and selective-download priorities.",
                "Sources": "Trackers, DHT, PEX and Local Peer Discovery with live discovery diagnostics.",
                "Speed": "Rolling download/upload history with averages, peaks and transfer-limit reference lines.",
            }
            for name, item in self._detail_items.items():
                add_text_tooltip(item, f"{name} details\n\n{detail_help.get(name, '')}")

    def _build_transfers_menu(self):
        with dpg.menu(label="Transfers"):
            self._torrent_action_items["start"] = dpg.add_menu_item(
                label="Start",
                callback=self._start_selected,
            )
            self._torrent_action_items["pause"] = dpg.add_menu_item(
                label="Pause",
                callback=self._pause_selected,
            )
            self._torrent_action_items["resume"] = dpg.add_menu_item(
                label="Resume",
                callback=self._resume_selected,
            )
            self._torrent_action_items["stop"] = dpg.add_menu_item(
                label="Stop",
                callback=self._stop_selected,
            )
            self._torrent_action_items["retry"] = dpg.add_menu_item(
                label="Retry",
                callback=self._retry_selected,
            )

            dpg.add_separator()
            with dpg.menu(label="Priority"):
                for priority in ("High", "Normal", "Low"):
                    self._priority_items[priority] = dpg.add_menu_item(
                        label=priority,
                        check=True,
                        callback=lambda s, a, u=priority: self._set_priority(u),
                    )

            dpg.add_separator()
            self._torrent_action_items["announce"] = dpg.add_menu_item(
                label="Update / Announce Trackers",
                callback=self._update_trackers,
            )
            self._torrent_action_items["recheck"] = dpg.add_menu_item(
                label="Force Recheck...",
                callback=self._force_recheck,
            )
            self._torrent_action_items["open_folder"] = dpg.add_menu_item(
                label="Open Download Folder",
                callback=self._open_download_folder,
            )
            self._torrent_action_items["properties"] = dpg.add_menu_item(
                label="Properties...",
                callback=self._show_properties,
            )
            add_help_tooltip(self._torrent_action_items["start"], "START_RESUME")
            add_help_tooltip(self._torrent_action_items["pause"], "PAUSE_TORRENT")
            add_help_tooltip(self._torrent_action_items["resume"], "START_RESUME")
            add_help_tooltip(self._torrent_action_items["stop"], "STOP_TORRENT")
            add_help_tooltip(self._torrent_action_items["retry"], "RETRY_TORRENT")
            for priority_item in self._priority_items.values():
                add_help_tooltip(priority_item, "QUEUE_PRIORITY")
            add_help_tooltip(self._torrent_action_items["announce"], "UPDATE_TRACKERS")
            add_help_tooltip(self._torrent_action_items["recheck"], "FORCE_RECHECK")
            add_help_tooltip(self._torrent_action_items["open_folder"], "OPEN_FOLDER")
            add_help_tooltip(self._torrent_action_items["properties"], "PROPERTIES")

            dpg.add_separator()
            pause_all_item = dpg.add_menu_item(label="Pause All", callback=self.manager.pause_all)
            resume_all_item = dpg.add_menu_item(label="Resume All", callback=self.manager.resume_all)
            add_text_tooltip(pause_all_item, "Pause All\n\nRequests a paused state for every currently active torrent without removing them or deleting data.")
            add_text_tooltip(resume_all_item, "Resume All\n\nRequests that paused/eligible torrents become active again, still respecting the configured active-download slot limit and queue priorities.")

    def _build_tools_menu(self):
        with dpg.menu(label="Tools"):
            preferences_item = dpg.add_menu_item(
                label="Preferences...",
                shortcut="Ctrl+,",
                callback=lambda: self._switch_scene("SettingsView"),
            )
            add_help_tooltip(preferences_item, "PREFERENCES_VIEW")
            dpg.add_separator()
            remap_item = dpg.add_menu_item(
                label="Refresh / Remap Connectivity",
                callback=self._refresh_connectivity,
            )
            add_help_tooltip(remap_item, "PORT_MAPPING")
            app_data_item = dpg.add_menu_item(
                label="Open Application Data Folder",
                callback=self._open_application_data_folder,
            )
            add_text_tooltip(app_data_item, "Application data folder\n\nOpens SalixTorrent's persistent state directory containing files such as settings.json, session.json, cached .torrent metadata and ui_errors.log. This is separate from payload downloads.")

    def _build_help_menu(self):
        with dpg.menu(label="Help"):
            help_topics_item = dpg.add_menu_item(
                label="Help Topics...",
                shortcut="F1",
                callback=self._show_help_topics,
            )
            add_text_tooltip(
                help_topics_item,
                "Help Topics\n\nOpens SalixTorrent's built-in CHM-style manual: subjects on the left, detailed explanations on the right, searchable contents, and an A-Z glossary generated from the same definitions used by hover tooltips.",
            )
            glossary_item = dpg.add_menu_item(
                label="Glossary A-Z...",
                callback=self._show_glossary,
            )
            add_text_tooltip(
                glossary_item,
                "Glossary A-Z\n\nJumps directly to the alphabetized technical glossary inside Help Topics.",
            )
            dpg.add_separator()
            dpg.add_menu_item(
                label="Keyboard Shortcuts",
                callback=self._show_shortcuts,
            )
            diagnostics_item = dpg.add_menu_item(
                label="Diagnostics...",
                callback=self._show_diagnostics,
            )
            add_help_tooltip(diagnostics_item, "DIAGNOSTICS")
            dpg.add_separator()
            dpg.add_menu_item(
                label="About SalixTorrent",
                callback=self._show_about,
            )

    # ------------------------------------------------------------------
    # Global keyboard shortcuts
    # ------------------------------------------------------------------

    def _build_shortcut_handler(self):
        # The shortcut strings on menu items are presentation-only in Dear
        # PyGui. Bind the common accelerators explicitly so they really work.
        with dpg.handler_registry() as self._shortcut_registry:
            dpg.add_key_press_handler(key=dpg.mvKey_O, callback=lambda: self._ctrl_action(self._open_torrent))
            dpg.add_key_press_handler(key=dpg.mvKey_M, callback=lambda: self._ctrl_action(self._open_magnet))
            dpg.add_key_press_handler(key=dpg.mvKey_N, callback=lambda: self._ctrl_action(lambda: self._switch_scene("CreateTorrentView")))
            dpg.add_key_press_handler(key=dpg.mvKey_F, callback=lambda: self._ctrl_action(self._focus_torrent_search))
            dpg.add_key_press_handler(key=dpg.mvKey_Comma, callback=lambda: self._ctrl_action(lambda: self._switch_scene("SettingsView")))
            dpg.add_key_press_handler(key=dpg.mvKey_1, callback=lambda: self._ctrl_action(lambda: self._switch_scene("DownloadView")))
            dpg.add_key_press_handler(key=dpg.mvKey_2, callback=lambda: self._ctrl_action(lambda: self._switch_scene("CreateTorrentView")))
            dpg.add_key_press_handler(key=dpg.mvKey_3, callback=lambda: self._ctrl_action(lambda: self._switch_scene("SettingsView")))
            dpg.add_key_press_handler(key=dpg.mvKey_F1, callback=lambda: self._show_help_topics())

    @staticmethod
    def _ctrl_down() -> bool:
        try:
            return bool(
                dpg.is_key_down(dpg.mvKey_LControl)
                or dpg.is_key_down(dpg.mvKey_RControl)
            )
        except Exception:
            return False

    def _ctrl_action(self, callback):
        if self._ctrl_down():
            callback()

    # ------------------------------------------------------------------
    # Menu state
    # ------------------------------------------------------------------

    def update(self, force: bool = False):
        now = time.monotonic()
        if not force and now - self._last_state_refresh < self._STATE_REFRESH_INTERVAL:
            return
        self._last_state_refresh = now

        scene_name = self.gui.scene_mgr.current_scene or ""
        info_hash = str(self.download_view.active_info_hash or "")
        stats = self.download_view.latest_stats.get(info_hash, {}) if info_hash else {}
        state = str(stats.get("state") or "Idle")
        queue_priority = str(stats.get("queue_priority") or "Normal")
        detail_tab = str(getattr(self.download_view, "_active_detail_tab", "General") or "General")

        signature = (
            scene_name,
            info_hash,
            state,
            queue_priority,
            detail_tab,
            bool(stats.get("storage_path")),
            bool(stats.get("info_hash")),
            bool(stats.get("magnet_uri")),
        )
        if not force and signature == self._last_state_signature:
            return
        self._last_state_signature = signature

        for scene, item in self._scene_items.items():
            self._set_checked(item, scene == scene_name)

        for tab_name, item in self._detail_items.items():
            self._set_checked(item, tab_name == detail_tab)

        selected = bool(info_hash and stats)
        can_start = selected and state in self.download_view.STARTABLE_STATES and state != "Error"
        can_pause = selected and state in self.download_view.ACTIVE_PAUSABLE_STATES
        can_resume = selected and state == "Paused"
        can_stop = selected and state in self.download_view.STOPPABLE_STATES

        action_enabled = {
            "start": can_start,
            "pause": can_pause,
            "resume": can_resume,
            "stop": can_stop,
            "retry": selected and state == "Error",
            "announce": selected and state in {"Downloading", "Seeding"},
            "recheck": selected and state not in {"Checking", "Fast Resume", "Queued"},
            "open_folder": selected and bool(stats.get("storage_path")),
            "properties": selected,
            "copy_hash": selected and bool(stats.get("info_hash")),
            "copy_magnet": selected and bool(stats.get("magnet_uri")),
        }
        for name, enabled in action_enabled.items():
            item = self._torrent_action_items.get(name)
            if item is not None:
                self._set_enabled(item, enabled)

        for priority, item in self._priority_items.items():
            self._set_enabled(item, selected)
            self._set_checked(item, selected and priority == queue_priority)

    @staticmethod
    def _set_enabled(item, enabled: bool):
        try:
            dpg.configure_item(item, enabled=bool(enabled))
        except Exception:
            pass

    @staticmethod
    def _set_checked(item, checked: bool):
        try:
            dpg.set_value(item, bool(checked))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File/Edit/View callbacks
    # ------------------------------------------------------------------

    def _switch_scene(self, scene_name: str):
        self.gui.switch_scene(scene_name)
        self.update(force=True)

    def _show_help_topics(self):
        self.gui.switch_scene("HelpTopicsView")
        self.update(force=True)

    def _show_glossary(self):
        self.gui.switch_scene("HelpTopicsView", glossary=True)
        self.update(force=True)

    def _open_torrent(self):
        self._switch_scene("DownloadView")
        self.download_view._open_native_file_dialog()

    def _open_magnet(self):
        self._switch_scene("DownloadView")
        self.download_view._show_magnet_dialog()

    def _focus_torrent_search(self):
        self._switch_scene("DownloadView")
        try:
            dpg.focus_item(self.download_view.queue_search_input)
        except Exception:
            pass

    def _clear_filters(self):
        self._switch_scene("DownloadView")
        self.download_view._clear_queue_filter()

    def _restore_queue_order(self):
        self._switch_scene("DownloadView")
        self.download_view._clear_queue_sort()

    def _show_detail_tab(self, tab_name: str):
        self._switch_scene("DownloadView")
        for tab_id, name in self.download_view._detail_tab_ids.items():
            if name != tab_name:
                continue
            try:
                dpg.set_value(self.download_view.detail_tab_bar, tab_id)
            except Exception:
                pass
            self.download_view._on_detail_tab_changed(
                sender=self.download_view.detail_tab_bar,
                app_data=tab_id,
            )
            break
        self.update(force=True)

    # ------------------------------------------------------------------
    # Selected torrent callbacks
    # ------------------------------------------------------------------

    def _selected_hash(self) -> str:
        info_hash = str(self.download_view.active_info_hash or "")
        return info_hash if info_hash in self.download_view.latest_stats else ""

    def _start_selected(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_start(info_hash)

    def _pause_selected(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_pause(info_hash)

    def _resume_selected(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_resume(info_hash)

    def _stop_selected(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_stop(info_hash)

    def _retry_selected(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_retry(info_hash)

    def _set_priority(self, priority: str):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_set_priority(info_hash, priority)

    def _update_trackers(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_update_trackers(info_hash)

    def _force_recheck(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_force_recheck(info_hash)

    def _open_download_folder(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_open_folder(info_hash)

    def _show_properties(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_properties(info_hash)

    def _copy_info_hash(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_copy_info_hash(info_hash)

    def _copy_magnet(self):
        info_hash = self._selected_hash()
        if info_hash:
            self.download_view._context_copy_magnet(info_hash)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _refresh_connectivity(self):
        self.manager.refresh_connectivity()
        if self.gui.scene_mgr.current_scene == "SettingsView":
            try:
                self.settings_view._render_connectivity()
            except Exception:
                pass

    def _open_application_data_folder(self):
        path = Path(self.manager.settings_path).parent
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        self._open_path(path)

    @staticmethod
    def _open_path(path: Path) -> bool:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
                return True
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
                return True
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", str(path)])
                return True
            if shutil.which("gio"):
                subprocess.Popen(["gio", "open", str(path)])
                return True
        except (OSError, subprocess.SubprocessError):
            return False
        return False

    # ------------------------------------------------------------------
    # Help / support windows
    # ------------------------------------------------------------------

    def _build_help_windows(self):
        with dpg.window(
            label="Keyboard Shortcuts",
            modal=True,
            show=False,
            no_resize=True,
            width=520,
            height=330,
        ) as self.shortcuts_modal:
            dpg.add_text("KEYBOARD SHORTCUTS", color=(100, 180, 255))
            dpg.add_separator()
            dpg.add_text(
                "Ctrl+O    Open .torrent file\n"
                "Ctrl+M    Open magnet link\n"
                "Ctrl+N    Create torrent\n"
                "Ctrl+F    Find/filter torrents\n"
                "Ctrl+,    Preferences\n"
                "Ctrl+1    Active Transfers\n"
                "Ctrl+2    Create Torrent\n"
                "Ctrl+3    Preferences\n"
                "F1        Help Topics",
            )
            dpg.add_spacer(height=8)
            dpg.add_text(
                "The same commands are available from the traditional application menu.",
                color=(150, 150, 155),
                wrap=470,
            )
            dpg.add_spacer(height=8)
            dpg.add_button(
                label=" Close ",
                callback=lambda: dpg.hide_item(self.shortcuts_modal),
            )

        with dpg.window(
            label="SalixTorrent Diagnostics",
            modal=True,
            show=False,
            width=700,
            height=500,
            min_size=[620, 360],
        ) as self.diagnostics_modal:
            dpg.add_text("SALIXTORRENT DIAGNOSTICS", color=(255, 200, 100))
            dpg.add_separator()
            with dpg.child_window(height=385, width=-1, border=False) as self.diagnostics_body:
                self.diagnostics_text = dpg.add_text("", wrap=650)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=" Copy Diagnostics ",
                    callback=self._copy_diagnostics,
                )
                dpg.add_button(
                    label=" Open Application Data ",
                    callback=self._open_application_data_folder,
                )
                dpg.add_button(
                    label=" Close ",
                    callback=lambda: dpg.hide_item(self.diagnostics_modal),
                )

        with dpg.window(
            label="About SalixTorrent",
            modal=True,
            show=False,
            no_resize=True,
            width=610,
            height=365,
        ) as self.about_modal:
            dpg.add_text("SALIX_T // BITTORRENT CLIENT", color=(0, 255, 128))
            dpg.add_text(f"SalixTorrent v{self.APP_VERSION}")
            dpg.add_separator()
            dpg.add_text(
                "A lightweight BitTorrent client and protocol engine written in Python "
                "with a Dear PyGui desktop interface.",
                wrap=560,
            )
            dpg.add_spacer(height=8)
            dpg.add_text(
                "Core capabilities\n"
                "  - HTTP/UDP trackers with batched scrape statistics, DHT, PEX and LAN discovery\n"
                "  - Multi-peer downloading and seeding\n"
                "  - Fast resume and SHA-1 piece verification\n"
                "  - Magnet metadata exchange (BEP-9)\n"
                "  - Multi-file torrents and torrent creation\n"
                "  - Queue/file priorities and bandwidth controls\n"
                "  - UPnP/NAT-PMP connectivity support",
                color=(185, 185, 190),
            )
            dpg.add_spacer(height=10)
            dpg.add_button(
                label=" Close ",
                callback=lambda: dpg.hide_item(self.about_modal),
            )

        self.layout.watch_item(
            self.diagnostics_modal,
            ("application_menu", "diagnostics"),
            self._layout_diagnostics_modal,
        )

    def _layout_diagnostics_modal(self):
        self.layout.dialog(
            self.diagnostics_modal,
            self.diagnostics_body,
            metrics=DialogMetrics(
                reserved_height=115,
                minimum_content_height=180,
                horizontal_margin=50,
                minimum_wrap=520,
                maximum_wrap=1500,
            ),
            wrap_items=(self.diagnostics_text,),
        )

    def _center_modal(self, item, width: int, height: int):
        try:
            rendered_width, rendered_height = self.layout.item_size(item)
            width = rendered_width or int(width)
            height = rendered_height or int(height)
            x = max(0, (dpg.get_viewport_client_width() - width) // 2)
            y = max(0, (dpg.get_viewport_client_height() - height) // 2)
            dpg.set_item_pos(item, [x, y])
        except Exception:
            pass

    def _show_shortcuts(self):
        dpg.show_item(self.shortcuts_modal)
        self._center_modal(self.shortcuts_modal, 520, 330)

    def _show_about(self):
        dpg.show_item(self.about_modal)
        self._center_modal(self.about_modal, 610, 365)

    def _diagnostics_string(self) -> str:
        settings = self.manager.get_app_settings()
        aggregate_connectivity = self.manager.get_connectivity_snapshot()
        try:
            dpg_version = str(dpg.get_dearpygui_version())
        except Exception:
            dpg_version = "unknown"

        selected = self._selected_hash()
        selected_stats = self.download_view.latest_stats.get(selected, {}) if selected else {}
        selected_name = selected_stats.get("torrent_name", "--")
        selected_state = selected_stats.get("state_label", selected_stats.get("state", "--"))
        selected_listen_port = int(selected_stats.get("listen_port") or 0)
        if selected_listen_port:
            connectivity = self.manager.get_connectivity_snapshot(port=selected_listen_port)
        else:
            connectivity = {"status": "Not listening", "method": "None"}

        external_ip = str(connectivity.get("external_ip") or "")
        try:
            external_port = int(connectivity.get("external_port") or 0)
        except (TypeError, ValueError):
            external_port = 0
        external_scope = str(connectivity.get("external_scope") or "Unknown")
        external_endpoint = (
            f"{format_endpoint(external_ip, external_port)} ({external_scope})"
            if external_ip and external_port
            else "--"
        )

        return (
            f"SalixTorrent: v{self.APP_VERSION}\n"
            f"Python: {platform.python_version()}\n"
            f"Dear PyGui: {dpg_version}\n"
            f"Platform: {platform.platform()}\n"
            f"Executable: {sys.executable}\n\n"
            f"Current view: {self.gui.scene_mgr.current_scene or '--'}\n"
            f"Loaded torrents: {len(self.download_view.torrent_order)}\n"
            f"Selected torrent: {selected_name}\n"
            f"Selected state: {selected_state}\n\n"
            f"Listen port preference: {settings.get('listen_port', '--')}\n"
            f"Peer encryption: {settings.get('peer_encryption', 'Prefer Encryption')}\n"
            f"Network bind: {settings.get('network_bind_address') or 'Any interface (system routing)'}\n"
            f"Interface Lock: {'Enabled' if settings.get('interface_lock') else 'Disabled'}\n"
            f"Peer IP masking: {'Enabled' if settings.get('mask_peer_ips') else 'Disabled'}\n"
            f"Selected encrypted peers: {selected_stats.get('encrypted_peer_count', 0)}\n"
            f"Selected plaintext peers: {selected_stats.get('plaintext_peer_count', 0)}\n"
            f"Selected incoming peers: {selected_stats.get('incoming_peers', 0)} active / "
            f"{selected_stats.get('incoming_connections_total', 0)} this session\n"
            f"Selected upload requests: {selected_stats.get('upload_requests_served', 0)} served / "
            f"{selected_stats.get('upload_requests_received', 0)} received\n"
            f"Selected uploaded this session: {selected_stats.get('uploaded_this_session_bytes', 0)} bytes\n"
            f"Tracker scrape S/L/C: "
            f"{selected_stats.get('scrape_seeders') if selected_stats.get('scrape_seeders') is not None else '--'} / "
            f"{selected_stats.get('scrape_leechers') if selected_stats.get('scrape_leechers') is not None else '--'} / "
            f"{selected_stats.get('scrape_completed') if selected_stats.get('scrape_completed') is not None else '--'}\n"
            f"Tracker scrape source: {selected_stats.get('scrape_source') or '--'} | "
            f"age {self.download_view._format_age(selected_stats.get('scrape_age_seconds'))} | "
            f"batch {selected_stats.get('scrape_batch_size', 0) or 0} torrent(s)\n"
            f"Download scheduler: Rarest-first + bounded adaptive pipeline\n"
            f"Endgame: {'Active' if selected_stats.get('endgame_active') else 'Standby'} "
            f"({selected_stats.get('remaining_wanted_blocks', 0)} wanted blocks remain; "
            f"threshold {selected_stats.get('endgame_threshold_blocks', 32)})\n"
            f"Outstanding download requests: {selected_stats.get('outstanding_download_requests', 0)} "
            f"({selected_stats.get('duplicate_download_requests', 0)} endgame duplicates)\n"
            f"Request pipeline: adaptive {selected_stats.get('request_pipeline_min', 8)}-"
            f"{selected_stats.get('request_pipeline_max', 64)} per peer; "
            f"timeout {selected_stats.get('request_timeout_seconds', 30)}s\n"
            f"Disk writer: {'Active' if (selected_stats.get('disk_io') or {}).get('writer_active') else 'Idle'}\n"
            f"Disk buffer: {(selected_stats.get('disk_io') or {}).get('pending_bytes', 0)} / "
            f"{(selected_stats.get('disk_io') or {}).get('buffer_limit_bytes', 0)} bytes "
            f"({(selected_stats.get('disk_io') or {}).get('pending_writes', 0)} pending writes)\n"
            f"Disk writes: {(selected_stats.get('disk_io') or {}).get('writes_completed', 0)} completed / "
            f"{(selected_stats.get('disk_io') or {}).get('write_failures', 0)} failed; "
            f"average {(selected_stats.get('disk_io') or {}).get('write_latency_average_ms', 0.0):.2f} ms; "
            f"max {(selected_stats.get('disk_io') or {}).get('write_latency_max_ms', 0.0):.2f} ms\n"
            f"Disk backpressure: {(selected_stats.get('disk_io') or {}).get('backpressure_events', 0)} events / "
            f"{(selected_stats.get('disk_io') or {}).get('backpressure_seconds', 0.0):.3f}s waiting\n"
            f"Recent-piece cache: {(selected_stats.get('disk_io') or {}).get('cache_bytes', 0)} / "
            f"{(selected_stats.get('disk_io') or {}).get('cache_limit_bytes', 0)} bytes; "
            f"{(selected_stats.get('disk_io') or {}).get('cache_hits', 0)} hits / "
            f"{(selected_stats.get('disk_io') or {}).get('cache_misses', 0)} misses\n"
            f"Disk error: {(selected_stats.get('disk_io') or {}).get('error') or '--'}\n"
            f"DHT: {'Enabled' if settings.get('enable_dht') else 'Disabled'}\n"
            f"PEX: {'Enabled' if settings.get('enable_pex') else 'Disabled'}\n"
            f"LAN discovery: {'Enabled' if settings.get('enable_lan_discovery') else 'Disabled'}\n"
            f"Selected connectivity: {connectivity.get('status', '--')}\n"
            f"Selected mapping: {connectivity.get('method', '--')}\n"
            f"UPnP status: {connectivity.get('upnp_status', '--')}\n"
            f"UPnP stage/code: {connectivity.get('upnp_stage') or '--'} / {connectivity.get('upnp_code') or '--'}\n"
            f"UPnP detail: {connectivity.get('upnp_error') or '--'}\n"
            f"UPnP advice: {connectivity.get('upnp_advice') or '--'}\n"
            f"NAT-PMP status: {connectivity.get('natpmp_status', '--')}\n"
            f"NAT-PMP stage/code: {connectivity.get('natpmp_stage') or '--'} / {connectivity.get('natpmp_code') or '--'}\n"
            f"NAT-PMP detail: {connectivity.get('natpmp_error') or '--'}\n"
            f"NAT-PMP advice: {connectivity.get('natpmp_advice') or '--'}\n"
            f"Selected listener endpoint: {selected_stats.get('listener_address') or '--'}:"
            f"{selected_listen_port or '--'}\n"
            f"Router-mapping local endpoint: {connectivity.get('local_ip', '--')}:"
            f"{connectivity.get('internal_port', '--')}\n"
            f"Selected external endpoint: {external_endpoint}\n"
            f"Connectivity diagnosis: {connectivity.get('diagnosis') or '--'}\n"
            f"Suggested action: {connectivity.get('action_hint') or '--'}\n"
            f"Selected mapping notice: {connectivity.get('last_error') or '--'}\n"
            f"Selected mapping lease: {'permanent' if connectivity.get('mapping_permanent') else (str(connectivity.get('mapping_lease_seconds')) + 's' if connectivity.get('mapping_lease_seconds') is not None else '--')}\n"
            f"Active listener ports: {aggregate_connectivity.get('active_listener_ports') or '--'}\n"
            f"Mapped listener ports: {aggregate_connectivity.get('mapped_ports') or '--'}\n\n"
            f"Settings: {self.manager.settings_path}\n"
            f"Session state: {self.manager.session_state_path}\n"
            f"UI error log: {self.gui._ui_error_log_path()}\n"
        )

    def _show_diagnostics(self):
        text = self._diagnostics_string()
        dpg.set_value(self.diagnostics_text, text)
        dpg.show_item(self.diagnostics_modal)
        self._center_modal(self.diagnostics_modal, 700, 500)
        self.layout.trigger(("application_menu", "diagnostics"))

    def _copy_diagnostics(self):
        try:
            dpg.set_clipboard_text(self._diagnostics_string())
        except Exception:
            pass
