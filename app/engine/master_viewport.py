# app/engine/master_viewport.py

import queue

import dearpygui.dearpygui as dpg

from app.engine.gui_engine import GuiEngine
from app.views.create_torrent_view import CreateTorrentView
from app.views.download_view import DownloadView
from app.views.settings_view import SettingsView


class MasterViewport:
    def __init__(self, ui_queue: queue.Queue):
        self.gui = GuiEngine.get_instance()
        self.ui_queue = ui_queue
        self._setup_primary_layout()

    def _setup_primary_layout(self):
        with dpg.window(tag="primary_window", no_title_bar=True, no_resize=True):
            # Top Navigation Header
            with dpg.group(horizontal=True):
                dpg.add_text("SALIX_T // BITTORRENT CLIENT", color=(0, 255, 128))
                dpg.add_spacer(width=20)
                dpg.add_button(
                    label=" Active Transfers ",
                    callback=lambda: self.gui.switch_scene("DownloadView"),
                )
                dpg.add_button(
                    label=" Create Torrent ",
                    callback=lambda: self.gui.switch_scene("CreateTorrentView"),
                )
                dpg.add_button(
                    label=" Preferences ",
                    callback=lambda: self.gui.switch_scene("SettingsView"),
                )

            dpg.add_separator()
            dpg.add_spacer(height=5)

            with dpg.group(tag="view_container_DownloadView"):
                download_view = DownloadView(ui_queue=self.ui_queue)
                download_view.build_view(parent_tag="view_container_DownloadView")
                self.gui.scene_mgr.register_scene("DownloadView", download_view)

            with dpg.group(tag="view_container_CreateTorrentView"):
                create_torrent_view = CreateTorrentView()
                create_torrent_view.build_view(parent_tag="view_container_CreateTorrentView")
                self.gui.scene_mgr.register_scene(
                    "CreateTorrentView",
                    create_torrent_view,
                )

            with dpg.group(tag="view_container_SettingsView"):
                settings_view = SettingsView()
                settings_view.build_view(parent_tag="view_container_SettingsView")
                self.gui.scene_mgr.register_scene("SettingsView", settings_view)

        dpg.set_primary_window("primary_window", True)
        self.gui.switch_scene("DownloadView")

    def run(self):
        self.gui.run()
