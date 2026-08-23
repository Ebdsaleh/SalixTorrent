# app/engine/master_viewport.py

import queue
import dearpygui.dearpygui as dpg
from app.engine.gui_engine import GuiEngine
from app.views.download_view import DownloadView


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

            dpg.add_separator()
            dpg.add_spacer(height=5)

            # Scene Container: DownloadView
            with dpg.group(tag="view_container_DownloadView"):
                download_view = DownloadView(ui_queue=self.ui_queue)
                download_view.build_view(parent_tag="view_container_DownloadView")
                self.gui.scene_mgr.register_scene("DownloadView", download_view)

        dpg.set_primary_window("primary_window", True)
        self.gui.switch_scene("DownloadView")

    def run(self):
        self.gui.run()
