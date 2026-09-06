# app/views/create_torrent_view.py

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog


from app.localization import canonical_choice, localized_choices, tr, tr_value

from app.framework.components import (
    action_callback,
    Button,
    CheckBox,
    ComboBox,
    ComponentGroup,
    ControlColumn,
    ControlRow,
    Label,
    ProgressBar,
    SectionPanel,
    Spacer,
    TextInput,
)
from app.engine.responsive_layout import ResponsiveLayout, clamp
from app.engine.ui_component_attachments import help_tooltip, text_tooltip
from app.logic.torrent_creator import (
    TORRENT_GENERATION_HYBRID,
    TORRENT_GENERATIONS,
    TorrentCreationCancelled,
    TorrentCreationProgress,
    TorrentCreator,
)
from app.logic.torrent_file import FALLBACK_TRACKERS
from app.logic.torrent_manager import TorrentManager


class CreateTorrentView:
    PIECE_SIZE_OPTIONS = {
        "Auto": None,
        "256 KiB": 256 * 1024,
        "512 KiB": 512 * 1024,
        "1 MiB": 1 * 1024 * 1024,
        "2 MiB": 2 * 1024 * 1024,
        "4 MiB": 4 * 1024 * 1024,
        "8 MiB": 8 * 1024 * 1024,
        "16 MiB": 16 * 1024 * 1024,
    }

    def __init__(self):
        self.manager = TorrentManager.get_instance()
        self.source_path = ""
        self.output_path = ""
        self._created_source_path = ""
        self._created_torrent_path = ""
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._output_was_user_chosen = False
        self.layout = ResponsiveLayout.get_instance()
        self._layout_root = None

    @staticmethod
    def _native_root():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        return root

    def build_view(self, parent_tag: str | int = "primary_window"):
        self.create_root = ControlColumn()
        with self.create_root.context(parent=parent_tag):
            self.create_heading_component = Label(
                tr('view.create_torrent_view.create_torrent', "CREATE TORRENT"),
                color=(0, 255, 128),
            ).attach(help_tooltip("CREATE_TORRENT"))
            self.create_heading = self.create_heading_component.build()

            self.create_intro_component = Label(
                tr(
                    'view.create_torrent_view.create_a_bittorrent_v1_v2_or_hybrid',
                    "Create a BitTorrent v1, v2, or hybrid .torrent from a file, archive, or folder.",
                ),
                color=(170, 170, 170),
            ).attach(help_tooltip("CREATE_TORRENT"))
            self.create_intro = self.create_intro_component.build()
            Spacer(profile_key="create_torrent.section_gap").build()

            self.source_section = SectionPanel(
                tr('view.create_torrent_view.source', "SOURCE"),
                heading_color=(100, 180, 255),
                profile_key="create_torrent.source_panel",
            )
            with self.source_section.context() as self.source_panel:
                self.source_action_row = ControlRow()
                with self.source_action_row.context():
                    self.select_file_component = Button(
                        tr('view.create_torrent_view.select_file_archive', " Select File / Archive "),
                        callback=action_callback(self._select_file_source),
                    ).attach(help_tooltip("TORRENT_SOURCE_FILE"))
                    self.select_file_button = self.select_file_component.build()

                    self.select_folder_component = Button(
                        tr('view.create_torrent_view.select_folder', " Select Folder "),
                        callback=action_callback(self._select_folder_source),
                    ).attach(help_tooltip("TORRENT_SOURCE_FOLDER"))
                    self.select_folder_button = self.select_folder_component.build()

                self.source_text_component = Label(
                    tr('view.create_torrent_view.no_source_selected', "No source selected"),
                    wrap=1000,
                ).attach(text_tooltip(
                    tr(
                        'view.create_torrent_view.selected_source_path_this_is_the_file',
                        "Selected source path\n\nThis is the file or folder whose bytes will be hashed into the new torrent. Torrent creation reads this source; it does not modify or move it.",
                    )
                ))
                self.source_text = self.source_text_component.build()

                self.source_summary_component = Label(
                    tr(
                        'view.create_torrent_view.files_such_as_zip_7z_and_iso',
                        "Files such as .zip, .7z and .iso are normal single-file torrents.",
                    ),
                    color=(160, 160, 160),
                    wrap=1000,
                ).attach(text_tooltip(
                    tr(
                        'view.create_torrent_view.source_summary_describes_whether_the_current_source',
                        "Source summary\n\nDescribes whether the current source will become a single-file or multi-file torrent and, when known, its payload size. The source itself remains untouched during torrent creation.",
                    )
                ))
                self.source_summary = self.source_summary_component.build()

            Spacer(profile_key="create_torrent.section_gap").build()

            self.output_section = SectionPanel(
                tr('view.create_torrent_view.output', "OUTPUT"),
                heading_color=(100, 180, 255),
                profile_key="create_torrent.output_panel",
            )
            with self.output_section.context() as self.output_panel:
                self.output_action_row = ControlRow()
                with self.output_action_row.context():
                    self.choose_output_component = Button(
                        tr('view.create_torrent_view.choose_save_location', " Choose Save Location "),
                        callback=action_callback(self._choose_output),
                    ).attach(help_tooltip("TORRENT_OUTPUT"))
                    self.choose_output_button = self.choose_output_component.build()

                    self.output_text_component = Label(
                        tr('view.create_torrent_view.no_output_selected', "No output selected"),
                        wrap=830,
                    ).attach(help_tooltip("TORRENT_OUTPUT"))
                    self.output_text = self.output_text_component.build()

                self.generation_row = ControlRow()
                with self.generation_row.context():
                    self.generation_label_component = Label(
                        tr('view.create_torrent_view.torrent_generation', "Torrent Generation")
                    ).attach(help_tooltip("TORRENT_GENERATION"))
                    self.generation_label = self.generation_label_component.build()
                    self.generation_component = ComboBox(
                        localized_choices(TORRENT_GENERATIONS),
                        default_value=tr_value(TORRENT_GENERATION_HYBRID),
                        profile_key="create_torrent.generation",
                    ).attach(help_tooltip("TORRENT_GENERATION"))
                    self.generation_combo = self.generation_component.build()

                self.piece_size_row = ControlRow()
                with self.piece_size_row.context():
                    self.piece_size_label_component = Label(
                        tr('view.create_torrent_view.piece_size', "Piece Size")
                    ).attach(help_tooltip("PIECE_SIZE"))
                    self.piece_size_label = self.piece_size_label_component.build()
                    self.piece_size_component = ComboBox(
                        [tr_value("Auto"), *[label for label in self.PIECE_SIZE_OPTIONS if label != "Auto"]],
                        default_value=tr_value("Auto"),
                        profile_key="create_torrent.piece_size",
                    ).attach(help_tooltip("PIECE_SIZE"))
                    self.piece_size_combo = self.piece_size_component.build()
                    self.private_component = CheckBox(
                        tr('view.create_torrent_view.private_torrent', "Private torrent"),
                        default_value=False,
                    ).attach(help_tooltip("PRIVATE_TORRENT"))
                    self.private_checkbox = self.private_component.build()

                self.comment_component = TextInput(
                    label=tr('view.create_torrent_view.comment', "Comment"),
                    hint=tr(
                        'view.create_torrent_view.optional_comment_stored_in_the_torrent_metadata',
                        "Optional comment stored in the .torrent metadata",
                    ),
                    profile_key="create_torrent.comment",
                ).attach(help_tooltip("TORRENT_COMMENT"))
                self.comment_input = self.comment_component.build()

            Spacer(profile_key="create_torrent.section_gap").build()

            self.trackers_section = SectionPanel(
                tr('view.create_torrent_view.trackers', "TRACKERS"),
                heading_color=(255, 200, 100),
                separated=False,
                profile_key="create_torrent.trackers_panel",
            )
            with self.trackers_section.context() as self.trackers_panel:
                self.trackers_note_component = Label(
                    tr(
                        'view.create_torrent_view.one_tracker_url_per_line_blank_lines',
                        "One tracker URL per line. Blank lines and lines beginning with # are ignored.",
                    ),
                    color=(160, 160, 160),
                ).attach(help_tooltip("TRACKER_LIST"))
                self.trackers_note = self.trackers_note_component.build()

                self.trackers_component = TextInput(
                    multiline=True,
                    default_value="\n".join(FALLBACK_TRACKERS),
                    profile_key="create_torrent.trackers_input",
                ).attach(help_tooltip("TRACKER_LIST"))
                self.trackers_input = self.trackers_component.build()

            Spacer(profile_key="create_torrent.section_gap").build()

            self.creation_progress_section = SectionPanel(
                tr('view.create_torrent_view.creation_progress', "CREATION PROGRESS"),
                heading_color=(180, 160, 255),
                profile_key="create_torrent.progress_panel",
            )
            with self.creation_progress_section.context() as self.creation_progress_panel:
                self.progress_component = ProgressBar(
                    default_value=0.0,
                    profile_key="create_torrent.progress_bar",
                ).attach(help_tooltip("CREATION_PROGRESS"))
                self.progress_bar = self.progress_component.build()

                self.status_component = Label(
                    tr('view.create_torrent_view.ready', "Ready")
                ).attach(help_tooltip("CREATION_PROGRESS"))
                self.status_text = self.status_component.build()

                self.detail_component = Label("", wrap=1000).attach(
                    help_tooltip("CREATION_PROGRESS")
                )
                self.detail_text = self.detail_component.build()

                self.creation_action_row = ControlRow()
                with self.creation_action_row.context():
                    self.create_component = Button(
                        tr('view.create_torrent_view.create_torrent_da3ef520', " Create Torrent "),
                        callback=action_callback(self._start_creation),
                    ).attach(help_tooltip("CREATE_TORRENT"))
                    self.create_button = self.create_component.build()

                    self.cancel_component = Button(
                        tr('view.create_torrent_view.cancel', " Cancel "),
                        callback=action_callback(self._cancel_creation),
                        enabled=False,
                    ).attach(text_tooltip(
                        tr(
                            'view.create_torrent_view.cancel_torrent_creation_requests_cancellation_of_the',
                            "Cancel torrent creation\n\nRequests cancellation of the background hashing job. SalixTorrent does not replace the chosen output with a half-written .torrent file.",
                        )
                    ))
                    self.cancel_button = self.cancel_component.build()

                    self.start_seeding_component = Button(
                        tr('view.create_torrent_view.start_seeding', " Start Seeding "),
                        callback=action_callback(self._start_seeding_created_torrent),
                        enabled=False,
                        show=False,
                    ).attach(help_tooltip("START_SEEDING"))
                    self.start_seeding_button = self.start_seeding_component.build()

        self.creation_editable_components = ComponentGroup(
            self.select_file_component,
            self.select_folder_component,
            self.choose_output_component,
            self.generation_component,
            self.piece_size_component,
            self.private_component,
            self.comment_component,
            self.trackers_component,
            self.create_component,
        )

        self._layout_root = parent_tag
        self.layout.watch_item(
            parent_tag,
            ("create_torrent", "root"),
            self._layout_create_view,
        )

    def _layout_create_view(self):
        width, height = self.layout.item_size(self._layout_root)
        if width <= 1 or height <= 1:
            return

        # Source/output/progress stay compact; the tracker editor absorbs extra
        # vertical room because it is the genuinely expandable workspace here.
        tracker_height = clamp(height - 540, 175, 430)
        self.layout.height(self.trackers_panel, tracker_height)
        self.layout.height(self.trackers_input, max(105, tracker_height - 70))

        wrap_width = clamp(width - 42, 560, 1400)
        self.layout.wrap(self.create_intro, wrap_width)
        self.layout.wrap(self.source_text, wrap_width)
        self.layout.wrap(self.source_summary, wrap_width)
        self.layout.wrap(self.detail_text, wrap_width)

    def _set_source(self, path: str):
        if not path:
            return

        self.source_path = os.path.abspath(path)
        self._created_source_path = ""
        self._created_torrent_path = ""
        if hasattr(self, "start_seeding_component"):
            self.start_seeding_component.set_enabled(False)
            self.start_seeding_component.set_visible(False)
        self.source_text_component.set_text(self.source_path)

        if os.path.isfile(self.source_path):
            size = os.path.getsize(self.source_path)
            self.source_summary_component.set_text(
                tr('view.create_torrent_view.single_file_torrent_source_value_mib', 'Single-file torrent source - {value0:,.2f} MiB', value0=size / (1024 * 1024)),
            )
            default_output = f"{self.source_path}.torrent"
        else:
            self.source_summary_component.set_text(
                tr('view.create_torrent_view.folder_selected_files_are_scanned_and_hashed', "Folder selected - files are scanned and hashed in the background when creation starts."),
            )
            default_output = os.path.join(
                os.path.dirname(self.source_path),
                f"{os.path.basename(self.source_path.rstrip(os.sep))}.torrent",
            )

        if not self._output_was_user_chosen:
            self.output_path = default_output
            self.output_text_component.set_text(self.output_path)

        self.status_component.set_text(tr('view.create_torrent_view.ready', "Ready"))
        self.detail_component.set_text("")
        self.progress_component.set_value(0.0)

    def _select_file_source(self):
        root = self._native_root()
        try:
            path = filedialog.askopenfilename(
                title=tr('view.create_torrent_view.select_file_or_archive_to_torrent', "Select File or Archive to Torrent"),
                filetypes=[(tr("view.create_torrent_view.all_files", "All Files"), "*.*")],
            )
        finally:
            root.destroy()
        self._set_source(path)

    def _select_folder_source(self):
        root = self._native_root()
        try:
            path = filedialog.askdirectory(
                title=tr('view.create_torrent_view.select_folder_to_torrent', "Select Folder to Torrent"),
                mustexist=True,
            )
        finally:
            root.destroy()
        self._set_source(path)

    def _choose_output(self):
        initial_dir = os.path.dirname(self.output_path or self.source_path) or os.getcwd()
        initial_file = os.path.basename(self.output_path) if self.output_path else "new.torrent"

        root = self._native_root()
        try:
            path = filedialog.asksaveasfilename(
                title=tr('view.create_torrent_view.save_torrent_file', "Save Torrent File"),
                initialdir=initial_dir,
                initialfile=initial_file,
                defaultextension=".torrent",
                filetypes=[(tr("view.create_torrent_view.torrent_files", "Torrent Files"), "*.torrent"), (tr("view.create_torrent_view.all_files", "All Files"), "*.*")],
            )
        finally:
            root.destroy()

        if path:
            if not path.lower().endswith(".torrent"):
                path += ".torrent"
            self.output_path = os.path.abspath(path)
            self._output_was_user_chosen = True
            self.output_text_component.set_text(self.output_path)

    def _trackers(self):
        raw = self.trackers_component.get_value() or ""
        return raw.splitlines()


    def _set_creation_controls_busy(self, busy: bool):
        self.creation_editable_components.set_enabled(not busy)
        self.cancel_component.set_enabled(busy)

    def _start_creation(self):
        if self._worker and self._worker.is_alive():
            return

        if not self.source_path or not os.path.exists(self.source_path):
            self.status_component.set_text(tr('view.create_torrent_view.select_a_valid_source_first', "Select a valid source first."))
            return

        if not self.output_path:
            self.status_component.set_text(tr('view.create_torrent_view.choose_where_to_save_the_torrent_file', "Choose where to save the .torrent file."))
            return

        generation = canonical_choice(self.generation_component.get_value(), TORRENT_GENERATIONS, TORRENT_GENERATION_HYBRID)
        piece_label = canonical_choice(self.piece_size_component.get_value(), tuple(self.PIECE_SIZE_OPTIONS), "Auto")
        piece_length = self.PIECE_SIZE_OPTIONS.get(piece_label)
        comment = self.comment_component.get_value() or ""
        private = bool(self.private_component.get_value())
        trackers = self._trackers()

        source_path = self.source_path
        output_path = self.output_path
        self._cancel_event = threading.Event()
        self._created_source_path = ""
        self._created_torrent_path = ""
        self.start_seeding_component.set_enabled(False)
        self.start_seeding_component.set_visible(False)
        self._set_creation_controls_busy(True)
        self.progress_component.set_value(0.0)
        self.status_component.set_text(tr('view.create_torrent_view.starting', "Starting..."))
        self.detail_component.set_text("")

        def on_progress(progress: TorrentCreationProgress):
            self._events.put(("progress", progress))

        def worker():
            try:
                result = TorrentCreator.create(
                    source_path=source_path,
                    output_path=output_path,
                    trackers=trackers,
                    piece_length=piece_length,
                    comment=comment,
                    private=private,
                    generation=generation,
                    cancel_event=self._cancel_event,
                    progress_callback=on_progress,
                )
                self._events.put(("complete", result))
            except TorrentCreationCancelled:
                self._events.put(("cancelled", None))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        self._worker = threading.Thread(
            target=worker,
            daemon=True,
            name="SalixTorrentCreator",
        )
        self._worker.start()

    def _start_seeding_created_torrent(self):
        if not self._created_torrent_path or not self._created_source_path:
            return

        try:
            session = self.manager.add_seed_torrent(
                self._created_torrent_path,
                self._created_source_path,
            )
            info_hash = session.torrent.hex_info_hash
            self.manager.set_selected_torrent(info_hash)
            self.manager.start_torrent(info_hash)

            self.status_component.set_text(
                tr('view.create_torrent_view.added_to_active_transfers_verifying_source_for', "Added to Active Transfers - verifying source for seeding"),
            )
            self.detail_component.set_text(
                (
                    tr('view.create_torrent_view.source_is_seeded_in_place_no_copy_to', 'Source is seeded in place (no copy to downloads):\n{created_source_path}', created_source_path=self._created_source_path)
                ),
            )
            self.start_seeding_component.set_enabled(False)

            # Switch to the transfer queue so Checking -> Seeding is visible.
            from app.engine.gui_engine import GuiEngine
            GuiEngine.get_instance().switch_scene("DownloadView")

        except Exception as exc:
            self.status_component.set_text(tr('view.create_torrent_view.could_not_start_seeding', "Could not start seeding"))
            self.detail_component.set_text(str(exc))

    def _cancel_creation(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.status_component.set_text(tr('view.create_torrent_view.cancelling', "Cancelling..."))
            self.cancel_component.set_enabled(False)

    @staticmethod
    def _piece_size_text(piece_length: int) -> str:
        if piece_length >= 1024 * 1024:
            return f"{piece_length / (1024 * 1024):g} MiB"
        return f"{piece_length / 1024:g} KiB"

    def _handle_progress(self, progress: TorrentCreationProgress):
        self.progress_component.set_value(progress.fraction)

        if progress.phase == "Hashing":
            self.status_component.set_text(
                tr('view.create_torrent_view.hashing_value', 'Hashing {value0:.1f}%', value0=progress.fraction * 100),
            )
            mib_done = progress.bytes_hashed / (1024 * 1024)
            mib_total = progress.total_bytes / (1024 * 1024)
            current = tr("view.create_torrent_view.current_file_suffix", " - {file}", file=progress.current_file) if progress.current_file else ""
            self.detail_component.set_text(
                (
                    tr('view.create_torrent_view.value_value_mib_hashed_value_pieces_value', '{mib_done:,.1f} / {mib_total:,.1f} MiB hashed | {pieces_hashed:,} pieces{current}', mib_done=mib_done, mib_total=mib_total, pieces_hashed=progress.pieces_hashed, current=current)
                ),
            )
        else:
            self.status_component.set_text(tr_value(progress.phase))

    def update(self, delta_time: float):
        del delta_time

        while True:
            try:
                event_type, payload = self._events.get_nowait()
            except queue.Empty:
                break

            if event_type == "progress":
                self._handle_progress(payload)

            elif event_type == "complete":
                result = payload
                self.output_path = result.output_path
                self._created_source_path = os.path.abspath(self.source_path)
                self._created_torrent_path = os.path.abspath(result.output_path)
                self.output_text_component.set_text(result.output_path)
                self.progress_component.set_value(1.0)
                self.status_component.set_text(tr('view.create_torrent_view.torrent_created_successfully', "Torrent created successfully"))
                mode = tr_value("folder / multi-file" if result.is_multi_file else "single-file")
                skipped = (
                    tr("view.create_torrent_view.symlinks_skipped_suffix", " | {count} symlink(s) skipped", count=result.skipped_symlinks)
                    if result.skipped_symlinks
                    else ""
                )
                self.detail_component.set_text(
                    (
                        tr('view.create_torrent_view.value_value_value_file_s_value_mib_value', '{torrent_name} | {mode} | {file_count:,} file(s) | {value3:,.2f} MiB | {piece_count:,} pieces @ {value5} | {generation} | Info Hash: {info_hash}{skipped}\nSaved: {output_path}', torrent_name=result.torrent_name, mode=mode, file_count=result.file_count, value3=result.total_bytes / (1024 * 1024), piece_count=result.piece_count, value5=self._piece_size_text(result.piece_length), generation=result.generation, info_hash=result.info_hash, skipped=skipped, output_path=result.output_path)
                    ),
                )
                self._set_creation_controls_busy(False)
                self.start_seeding_component.set_enabled(True)
                self.start_seeding_component.set_visible(True)

            elif event_type == "cancelled":
                self.status_component.set_text(tr('view.create_torrent_view.creation_cancelled', "Creation cancelled"))
                self.detail_component.set_text(tr('view.create_torrent_view.no_torrent_file_was_replaced', "No .torrent file was replaced."))
                self._set_creation_controls_busy(False)

            elif event_type == "error":
                self.status_component.set_text(tr('view.create_torrent_view.creation_failed', "Creation failed"))
                self.detail_component.set_text(str(payload))
                self._set_creation_controls_busy(False)


