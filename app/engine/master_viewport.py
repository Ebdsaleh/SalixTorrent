# app/engine/master_viewport.py

import queue

import dearpygui.dearpygui as dpg

from app.engine.gui_engine import GuiEngine
from app.views.application_menu import ApplicationMenu
from app.views.create_torrent_view import CreateTorrentView
from app.views.download_view import DownloadView
from app.views.settings_view import SettingsView
from app.views.help_topics_view import HelpTopicsView
from app.views.help_terms import add_help_tooltip, add_text_tooltip


class MasterViewport:
    def __init__(self, ui_queue: queue.Queue):
        self.gui = GuiEngine.get_instance()
        self.ui_queue = ui_queue
        self.application_menu = None
        self._setup_primary_layout()

    def _setup_primary_layout(self):
        # Construct the view objects first so the application menu can route
        # commands to the same live scene instances.
        download_view = DownloadView(ui_queue=self.ui_queue)
        create_torrent_view = CreateTorrentView()
        settings_view = SettingsView()
        help_topics_view = HelpTopicsView()

        self.application_menu = ApplicationMenu(
            gui=self.gui,
            download_view=download_view,
            create_torrent_view=create_torrent_view,
            settings_view=settings_view,
            help_topics_view=help_topics_view,
        )

        with dpg.window(tag="primary_window", no_title_bar=True, no_resize=True):
            # Build the menu first so it owns its own layout row rather than
            # overlaying the SALIX_T toolbar beneath the native title bar.
            self.application_menu.build_menu_bar(parent="primary_window")

            # Fast navigation remains available under the traditional menu bar.
            # It acts like a small application toolbar while File/Edit/View/...
            # provide the complete desktop-style command surface.
            with dpg.group(horizontal=True, tag="salix_toolbar"):
                brand_item = dpg.add_text("SALIX_T // BITTORRENT CLIENT", color=(0, 255, 128))
                add_text_tooltip(
                    brand_item,
                    "SalixTorrent (Salix_T)\n\nA BitTorrent v1 desktop client. Hover technical labels, table cells and controls throughout the application for contextual explanations of what SalixTorrent is doing.",
                )
                dpg.add_spacer(width=20)
                active_button = dpg.add_button(
                    label=" Active Transfers ",
                    callback=lambda: self.gui.switch_scene("DownloadView"),
                )
                add_help_tooltip(active_button, "ACTIVE_TRANSFERS_VIEW")
                create_button = dpg.add_button(
                    label=" Create Torrent ",
                    callback=lambda: self.gui.switch_scene("CreateTorrentView"),
                )
                add_help_tooltip(create_button, "CREATE_TORRENT")
                preferences_button = dpg.add_button(
                    label=" Preferences ",
                    callback=lambda: self.gui.switch_scene("SettingsView"),
                )
                add_help_tooltip(preferences_button, "PREFERENCES_VIEW")

            dpg.add_separator()
            dpg.add_spacer(height=5)

            with dpg.group(tag="view_container_DownloadView"):
                download_view.build_view(parent_tag="view_container_DownloadView")
                self.gui.scene_mgr.register_scene("DownloadView", download_view)

            with dpg.group(tag="view_container_CreateTorrentView"):
                create_torrent_view.build_view(parent_tag="view_container_CreateTorrentView")
                self.gui.scene_mgr.register_scene(
                    "CreateTorrentView",
                    create_torrent_view,
                )

            with dpg.group(tag="view_container_SettingsView"):
                settings_view.build_view(parent_tag="view_container_SettingsView")
                self.gui.scene_mgr.register_scene("SettingsView", settings_view)

            with dpg.group(tag="view_container_HelpTopicsView"):
                help_topics_view.build_view(parent_tag="view_container_HelpTopicsView")
                self.gui.scene_mgr.register_scene("HelpTopicsView", help_topics_view)

        # Help/diagnostic windows and global key handlers are created only
        # after the view tree is complete.
        self.application_menu.finish_build()
        self.gui.set_application_menu(self.application_menu)

        dpg.set_primary_window("primary_window", True)
        self.gui.switch_scene("DownloadView")
        self.application_menu.update(force=True)

    def run(self):
        self.gui.run()
