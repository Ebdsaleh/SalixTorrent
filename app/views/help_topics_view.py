# app/views/help_topics_view.py

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import dearpygui.dearpygui as dpg

from app.engine.documentation import (
    DOCUMENTATION_SCALE_LABELS,
    DOCUMENTATION_SCALES,
    DocLink,
    DocLinks,
    DocPage,
    DocParagraph,
    DocRole,
    DocSection,
    DocumentationLayoutTheme,
    DocumentationRenderer,
    documentation_scale_from_label,
    documentation_scale_label,
    role_font_size,
)
from app.engine.responsive_layout import ResponsiveLayout, clamp, split_widths
from app.engine.ui_typography import UiTypography
from app.logic.torrent_manager import TorrentManager
from app.localization import tr
from app.localization.documents import (
    HelpTopic,
    canonical_help_topics,
    glossary_entry,
    localize_help_topic,
    localized_glossary_entries,
    localized_help_topics,
)
from app.views.help_terms import HELP_TERMS, add_text_tooltip


# SalixTorrent's application theme deliberately widens the framework's
# conservative 980 px documentation default.  Individual DocPage instances can
# still override any of these values through their sparse DocLayout policy.
SALIX_DOCUMENTATION_LAYOUT_THEME = DocumentationLayoutTheme(
    maximum_width=1180,
    margin_left=8,
    margin_right=8,
    padding_left=18,
    padding_right=18,
)


HELP_TOPICS: Tuple[HelpTopic, ...] = canonical_help_topics()


TOPIC_BY_KEY: Dict[str, HelpTopic] = {topic.key: topic for topic in HELP_TOPICS}

# Map glossary entries back to the most useful explanatory article. Terms not
# explicitly listed fall back to BitTorrent Basics or SalixTorrent Controls.
TERM_TOPIC_MAP: Dict[str, str] = {}
for _topic in HELP_TOPICS:
    for _term in _topic.related_terms:
        TERM_TOPIC_MAP.setdefault(_term, _topic.key)


class HelpTopicsView:
    """Responsive offline manual rendered by the Documentation subsystem.

    Navigation/search remain ordinary application controls. The article pane is
    intentionally semantic: topic/glossary content is converted to ``DocPage``
    objects and the shared renderer owns typography, readable content width,
    parent-relative alignment and future rich-media behavior.
    """

    def __init__(self):
        self.parent_tag = None
        self.manager = TorrentManager.get_instance()
        self.typography = UiTypography.get_instance()
        self.layout = ResponsiveLayout.get_instance()

        self.search_input = None
        self.search_status = None
        self.documentation_scale_combo = None
        self.left_tab_bar = None
        self.contents_tab = None
        self.glossary_tab = None
        self.left_pane = None
        self.right_pane = None
        self.renderer = None
        self._layout_root = None

        self._topic_items: Dict[str, int] = {}
        self._term_items: Dict[str, int] = {}
        self._glossary_letter_groups: Dict[str, int] = {}
        self._glossary_letter_items: Dict[str, int] = {}
        self._term_letters: Dict[str, str] = {}
        self._current_topic = "basics"
        self._current_term = ""

        self.help_heading = None
        self.help_intro = None
        self.contents_heading = None
        self.glossary_heading = None

    @staticmethod
    def _localized_topics():
        return localized_help_topics(HELP_TOPICS)

    @staticmethod
    def _localized_terms():
        return localized_glossary_entries(HELP_TERMS)

    @staticmethod
    def _topic_by_key(topic_key: str):
        canonical = TOPIC_BY_KEY.get(str(topic_key))
        return localize_help_topic(canonical) if canonical is not None else None

    @staticmethod
    def _term_entry(term_key: str):
        key = str(term_key or "").upper()
        entry = HELP_TERMS.get(key)
        return glossary_entry(key, entry) if entry else None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_view(self, parent_tag: str):
        self.parent_tag = parent_tag
        scale = int(self.manager.get_app_settings().get("documentation_scale", 100))

        self.help_heading = dpg.add_text(
            tr("help.heading", "SALIXTORRENT HELP & GLOSSARY"),
            color=(0, 255, 128),
            parent=parent_tag,
        )
        self.help_intro = dpg.add_text(
            tr(
                "help.intro",
                "Built-in offline reference for BitTorrent concepts, SalixTorrent controls and "
                "the technical detail behind the live interface.",
            ),
            color=(165, 165, 170),
            parent=parent_tag,
            wrap=1000,
        )
        dpg.add_spacer(height=5, parent=parent_tag)

        search_row = dpg.add_group(horizontal=True, parent=parent_tag)
        dpg.add_text(tr("help.search", "Search"), parent=search_row)
        self.search_input = dpg.add_input_text(
            hint=tr("help.search_hint", "Search topics and glossary..."),
            width=430,
            parent=search_row,
            callback=self._on_search_changed,
        )
        clear_button = dpg.add_button(
            label=tr("help.clear", " Clear "),
            parent=search_row,
            callback=self._clear_search,
        )
        dpg.add_spacer(width=12, parent=search_row)
        dpg.add_text(tr("help.documentation", "Documentation"), parent=search_row)
        self.documentation_scale_combo = dpg.add_combo(
            items=[DOCUMENTATION_SCALE_LABELS[value] for value in DOCUMENTATION_SCALES],
            default_value=documentation_scale_label(scale),
            width=190,
            parent=search_row,
            callback=self._on_documentation_scale_changed,
        )
        self.search_status = dpg.add_text("", color=(140, 180, 220), parent=search_row)
        add_text_tooltip(
            self.search_input,
            tr('view.help_topics_view.help_search_filters_both_the_subject_list', "Help search\n\nFilters both the subject list and the A-Z glossary. Search by full words, acronyms such as DHT/PEX/LPD, or concepts such as port mapping, pieces, privacy or magnet links."),
        )
        add_text_tooltip(
            clear_button,
            tr('view.help_topics_view.clear_help_search_restores_the_complete_contents', "Clear help search\n\nRestores the complete Contents and Glossary A-Z lists."),
        )
        add_text_tooltip(
            self.documentation_scale_combo,
            self._term_entry("DOCUMENTATION_SCALE")[1],
        )

        dpg.add_separator(parent=parent_tag)
        dpg.add_spacer(height=3, parent=parent_tag)

        split = dpg.add_group(horizontal=True, parent=parent_tag)
        self.left_pane = dpg.add_child_window(width=340, height=-1, border=True, parent=split)
        self.right_pane = dpg.add_child_window(width=-1, height=-1, border=True, parent=split)

        self.left_tab_bar = dpg.add_tab_bar(parent=self.left_pane)
        self.contents_tab = dpg.add_tab(label=tr("help.contents", "Contents"), parent=self.left_tab_bar)
        self.glossary_tab = dpg.add_tab(label=tr("help.glossary", "Glossary A-Z"), parent=self.left_tab_bar)

        self._build_contents_index()
        self._build_glossary_index()

        self.renderer = DocumentationRenderer(
            self.right_pane,
            layout=self.layout,
            layout_theme=SALIX_DOCUMENTATION_LAYOUT_THEME,
            scale_percent=scale,
            on_link=self._on_document_link,
            tooltip=add_text_tooltip,
        )
        self._show_topic("basics")
        self._apply_shell_typography()

        self._layout_root = parent_tag
        self.layout.watch_item(
            parent_tag,
            ("help_topics", "root"),
            self._layout_help_view,
        )

    def _layout_help_view(self):
        width, _height = self.layout.item_size(self._layout_root)
        if width <= 1:
            return

        left_width, right_width = split_widths(
            width - 16,
            (0.26, 0.74),
            minimums=(260, 520),
            gap=8,
        )
        self.layout.width(self.left_pane, left_width)
        self.layout.width(self.right_pane, right_width)
        self.layout.width(self.search_input, clamp(width * 0.34, 260, 620))
        self.layout.wrap(self.help_intro, clamp(width - 28, 540, 1150))
        if self.renderer is not None:
            self.renderer.reflow(right_width, force=True)

    def _apply_shell_typography(self):
        scale = int(self.manager.get_app_settings().get("documentation_scale", 100))
        if self.help_heading is not None:
            self.typography.bind_item_font(
                self.help_heading,
                role_font_size(DocRole.SECTION_TITLE, self.typography.current_size, scale),
            )
        if self.contents_heading is not None:
            self.typography.bind_item_font(
                self.contents_heading,
                role_font_size(DocRole.INDEX_HEADING, self.typography.current_size, scale),
            )
        if self.glossary_heading is not None:
            self.typography.bind_item_font(
                self.glossary_heading,
                role_font_size(DocRole.INDEX_HEADING, self.typography.current_size, scale),
            )
        for item in tuple(self._glossary_letter_items.values()):
            self.typography.bind_item_font(
                item,
                role_font_size(DocRole.INDEX_HEADING, self.typography.current_size, scale),
            )

    def _build_contents_index(self):
        self.contents_heading = dpg.add_text(
            tr("help.contents_heading", "CONTENTS"), color=(100, 180, 255), parent=self.contents_tab
        )
        add_text_tooltip(
            self.contents_heading,
            tr('view.help_topics_view.help_contents_the_main_salixtorrent_manual_arranged', "Help Contents\n\nThe main SalixTorrent manual arranged by subject, similar to the Contents pane in traditional Windows CHM help files."),
        )
        dpg.add_separator(parent=self.contents_tab)

        for topic in self._localized_topics():
            item = dpg.add_selectable(
                label=topic.title,
                parent=self.contents_tab,
                callback=self._on_topic_selected,
                user_data=topic.key,
            )
            self._topic_items[topic.key] = item
            add_text_tooltip(item, tr('view.help_topics_view.value_value', '{title}\n\n{summary}', title=topic.title, summary=topic.summary))

    @staticmethod
    def _glossary_sort_key(entry: Tuple[str, Tuple[str, str]]):
        key, value = entry
        title = str(value[0] if value else key)
        return title.casefold()

    def _build_glossary_index(self):
        self.glossary_heading = dpg.add_text(
            tr("help.glossary_heading", "GLOSSARY A-Z"), color=(100, 180, 255), parent=self.glossary_tab
        )
        add_text_tooltip(
            self.glossary_heading,
            tr('view.help_topics_view.glossary_a_z_alphabetical_index_generated_from', "Glossary A-Z\n\nAlphabetical index generated from the same definitions used by SalixTorrent's contextual hover help."),
        )
        dpg.add_separator(parent=self.glossary_tab)

        current_group = None
        last_letter = ""
        localized_terms = self._localized_terms()
        for key, (title, body) in sorted(localized_terms.items(), key=self._glossary_sort_key):
            letter = self._index_letter(title)
            if letter != last_letter:
                current_group = dpg.add_group(parent=self.glossary_tab)
                self._glossary_letter_groups[letter] = current_group
                dpg.add_spacer(height=5, parent=current_group)
                letter_item = dpg.add_text(
                    letter, color=(255, 200, 100), parent=current_group
                )
                self._glossary_letter_items[letter] = letter_item
                last_letter = letter

            item = dpg.add_selectable(
                label=title,
                parent=current_group or self.glossary_tab,
                callback=self._on_term_selected,
                user_data=key,
            )
            self._term_items[key] = item
            self._term_letters[key] = letter
            add_text_tooltip(item, tr('view.help_topics_view.value_value_d29b16d8', '{title}\n\n{body}', title=title, body=body))

    @staticmethod
    def _index_letter(title: str) -> str:
        for ch in str(title).strip():
            if ch.isalpha():
                return ch.upper()
            if ch.isdigit():
                return "#"
        return "#"

    # ------------------------------------------------------------------
    # Dear PyGui callbacks
    # ------------------------------------------------------------------

    def _on_topic_selected(self, sender=None, app_data=None, user_data=None):
        if user_data is not None:
            self._show_topic(str(user_data))

    def _on_term_selected(self, sender=None, app_data=None, user_data=None):
        if user_data is not None:
            self._show_term(str(user_data))

    def _on_document_link(self, target: str):
        kind, separator, value = str(target or "").partition(":")
        if not separator:
            return
        if kind == "term":
            self._open_glossary_term(value)
        elif kind == "topic":
            self._open_contents_topic(value)

    def _on_documentation_scale_changed(self, sender=None, app_data=None, user_data=None):
        del sender, user_data
        try:
            raw = dpg.get_value(self.documentation_scale_combo)
        except Exception:
            raw = app_data
        scale = self.manager.set_documentation_scale(
            documentation_scale_from_label(raw)
        )
        try:
            dpg.set_value(self.documentation_scale_combo, documentation_scale_label(scale))
        except Exception:
            pass
        if self.renderer is not None:
            # set_scale() already refreshes semantic fonts and performs one
            # forced reflow; avoid duplicate geometry/font work in the callback.
            self.renderer.set_scale(scale)
        self._apply_shell_typography()

    # ------------------------------------------------------------------
    # Semantic document rendering
    # ------------------------------------------------------------------

    def _set_selections(self, topic_key: str = "", term_key: str = ""):
        for key, item in self._topic_items.items():
            try:
                dpg.set_value(item, key == topic_key)
            except Exception:
                pass
        for key, item in self._term_items.items():
            try:
                dpg.set_value(item, key == term_key)
            except Exception:
                pass

    def _topic_page(self, topic: HelpTopic) -> DocPage:
        sections = [
            DocSection(
                title=heading,
                blocks=(DocParagraph(body),),
            )
            for heading, body in topic.sections
        ]

        links = []
        for term_key in topic.related_terms:
            entry = self._term_entry(term_key)
            if not entry:
                continue
            links.append(
                DocLink(
                    label=entry[0],
                    target=f"term:{term_key}",
                    tooltip=tr(
                        "help.open_glossary_entry_tooltip",
                        "Open glossary entry\n\n{title}\n\n{body}",
                        title=entry[0],
                        body=entry[1],
                    ),
                )
            )
        if links:
            sections.append(
                DocSection(
                    title=tr("help.related_terms", "Related glossary terms"),
                    blocks=(DocLinks(title="", links=tuple(links)),),
                )
            )

        if topic.key == "glossary":
            sections.append(
                DocSection(
                    title=tr("help.browse_glossary_index", "Browse the alphabetical index"),
                    blocks=(
                        DocLinks(
                            title="",
                            links=(
                                DocLink(
                                    label=tr(
                                        "help.open_glossary_index",
                                        "Open Glossary A-Z",
                                    ),
                                    target="topic:__open_glossary__",
                                    tooltip=tr(
                                        "help.open_glossary_index_tooltip",
                                        "Switch the navigator to the alphabetized glossary index.",
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )
        return DocPage(title=topic.title, lead=topic.summary, sections=tuple(sections))

    def _show_topic(self, topic_key: str):
        if topic_key == "__open_glossary__":
            self._open_glossary_tab()
            return
        topic = self._topic_by_key(str(topic_key))
        if topic is None or self.renderer is None:
            return
        self._current_topic = topic.key
        self._current_term = ""
        self._set_selections(topic_key=topic.key)
        self.renderer.render_page(self._topic_page(topic))
        self._scroll_document_to_top()

    def _show_term(self, term_key: str):
        key = str(term_key or "").upper()
        entry = self._term_entry(key)
        if not entry or self.renderer is None:
            return

        title, body = entry
        self._current_term = key
        self._set_selections(term_key=key)

        sections = []
        topic_key = TERM_TOPIC_MAP.get(key, "basics")
        topic = self._topic_by_key(topic_key)
        if topic:
            sections.append(
                DocSection(
                    title=tr("help.related_topic", "Related help topic"),
                    blocks=(
                        DocLinks(
                            title="",
                            links=(
                                DocLink(
                                    label=topic.title,
                                    target=f"topic:{topic.key}",
                                    tooltip=tr(
                                        "help.open_help_topic_tooltip",
                                        "Open help topic\n\n{title}\n\n{summary}",
                                        title=topic.title,
                                        summary=topic.summary,
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )

        page = DocPage(
            title=title,
            lead=tr("help.glossary_definition", "Glossary definition"),
            blocks=(DocParagraph(body),),
            sections=tuple(sections),
        )
        self.renderer.render_page(page)
        self._scroll_document_to_top()

    def _scroll_document_to_top(self):
        try:
            dpg.set_y_scroll(self.right_pane, 0.0)
        except Exception:
            pass

    def _open_contents_topic(self, topic_key: str):
        if topic_key == "__open_glossary__":
            self._open_glossary_tab()
            return
        try:
            dpg.set_value(self.left_tab_bar, self.contents_tab)
        except Exception:
            pass
        self._show_topic(topic_key)

    def _open_glossary_term(self, term_key: str):
        try:
            dpg.set_value(self.left_tab_bar, self.glossary_tab)
        except Exception:
            pass
        self._show_term(term_key)

    def _open_glossary_tab(self, sender=None, app_data=None, user_data=None):
        del sender, app_data, user_data
        try:
            dpg.set_value(self.left_tab_bar, self.glossary_tab)
        except Exception:
            pass
        if self._current_term:
            self._show_term(self._current_term)
        else:
            glossary = self._topic_by_key("glossary")
            if glossary is not None and self.renderer is not None:
                self.renderer.render_page(self._topic_page(glossary))
                self._scroll_document_to_top()

    def open_glossary(self):
        self._open_glossary_tab()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @staticmethod
    def _matches(query: str, values: Iterable[str]) -> bool:
        if not query:
            return True
        needle = query.casefold()
        return any(needle in str(value).casefold() for value in values)

    def _on_search_changed(self, sender=None, app_data=None, user_data=None):
        del sender, user_data
        try:
            query = str(dpg.get_value(self.search_input) or "").strip()
        except Exception:
            query = str(app_data or "").strip()

        visible_topics = 0
        for topic in self._localized_topics():
            values: List[str] = [topic.title, topic.summary]
            for heading, body in topic.sections:
                values.extend((heading, body))
            for term_key in topic.related_terms:
                entry = self._term_entry(term_key)
                if entry:
                    values.extend(entry)
            show = self._matches(query, values)
            visible_topics += int(show)
            try:
                dpg.configure_item(self._topic_items[topic.key], show=show)
            except Exception:
                pass

        visible_terms = 0
        visible_letters = set()
        for key, (title, body) in self._localized_terms().items():
            show = self._matches(query, (key, title, body))
            visible_terms += int(show)
            if show:
                visible_letters.add(self._term_letters.get(key, ""))
            try:
                dpg.configure_item(self._term_items[key], show=show)
            except Exception:
                pass

        for letter, group in self._glossary_letter_groups.items():
            try:
                dpg.configure_item(group, show=(not query or letter in visible_letters))
            except Exception:
                pass

        if query:
            dpg.set_value(
                self.search_status,
                tr(
                    "help.search_results",
                    "{topics} topic(s), {terms} glossary term(s)",
                    topics=visible_topics,
                    terms=visible_terms,
                ),
            )
        else:
            dpg.set_value(self.search_status, "")

    def _clear_search(self, sender=None, app_data=None, user_data=None):
        del sender, app_data, user_data
        try:
            dpg.set_value(self.search_input, "")
        except Exception:
            pass
        self._on_search_changed()

    # Scene hooks -------------------------------------------------------

    def on_show(self, **kwargs):
        scale = int(self.manager.get_app_settings().get("documentation_scale", 100))
        try:
            dpg.set_value(self.documentation_scale_combo, documentation_scale_label(scale))
        except Exception:
            pass
        if self.renderer is not None:
            self.renderer.set_scale(scale)
            self.renderer.refresh_typography()
        self._apply_shell_typography()
        self.layout.trigger(("help_topics", "root"))
        if kwargs.get("glossary"):
            self.open_glossary()
        elif kwargs.get("topic"):
            self._open_contents_topic(str(kwargs["topic"]))

    def update(self, dt: float):
        # Documentation layout is resize-event driven; there is intentionally no
        # per-frame geometry/typography polling in the Help view.
        del dt




