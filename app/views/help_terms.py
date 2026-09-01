# app/views/help_terms.py

from __future__ import annotations

from typing import Iterable, Optional

import dearpygui.dearpygui as dpg

from app.localization.documents import canonical_glossary_entries, glossary_entry


# Canonical glossary wording now lives in the renderer-neutral semantic source
# document under app/localization/content/glossary.json.  Keep this compatibility
# mapping for existing tooltip call sites; the view no longer owns the English.
HELP_TERMS = canonical_glossary_entries()


def help_text(term: str) -> str:
    entry = HELP_TERMS.get(str(term or "").upper())
    if not entry:
        return ""
    title, body = glossary_entry(str(term or "").upper(), entry)
    return f"{title}\n\n{body}"


def contextual_text(
    title: str,
    body: str,
    facts: Optional[Iterable[str]] = None,
    footer: str = "",
) -> str:
    """Build a consistent long-form tooltip with optional live facts."""
    parts = [str(title).strip(), "", str(body).strip()]
    clean_facts = [str(x).strip() for x in (facts or ()) if str(x).strip()]
    if clean_facts:
        parts.extend(["", *clean_facts])
    if str(footer or "").strip():
        parts.extend(["", str(footer).strip()])
    return "\n".join(parts)


def add_text_tooltip(item, text: str, wrap: int = 450):
    """Attach arbitrary explanatory text to a Dear PyGui item safely.

    Some Dear PyGui item types (notably table columns and a few container-like
    items) cannot own a tooltip.  Using the ``with dpg.tooltip(...)`` context
    manager for one of those items can raise during ``__enter__`` after Dear
    PyGui has already touched its internal container stack.  Catching that
    exception is therefore not enough: later widgets may be parented to the
    wrong container.

    Create the tooltip and its text with explicit parent IDs instead.  Failed
    tooltip attachment then remains non-fatal *and* cannot disturb the active
    layout/container stack.  Tooltips are help-only, so unsupported targets are
    intentionally skipped.
    """
    if not item or not str(text or "").strip():
        return None

    tooltip_id = None
    try:
        tooltip_id = dpg.add_tooltip(parent=item)
        return dpg.add_text(str(text), parent=tooltip_id, wrap=wrap)
    except Exception:
        # If the tooltip container itself was accepted but adding its content
        # failed, clean it up so no empty/orphan help item is left behind.
        try:
            if tooltip_id and dpg.does_item_exist(tooltip_id):
                dpg.delete_item(tooltip_id)
        except Exception:
            pass
        return None


def add_help_tooltip(item, term: str, wrap: int = 450):
    """Attach a consistent glossary tooltip to an existing DPG item."""
    return add_text_tooltip(item, help_text(term), wrap=wrap)


def add_context_tooltip(
    item,
    title: str,
    body: str,
    facts: Optional[Iterable[str]] = None,
    footer: str = "",
    wrap: int = 470,
):
    """Attach an explanatory tooltip containing optional live/current values."""
    return add_text_tooltip(
        item,
        contextual_text(title, body, facts=facts, footer=footer),
        wrap=wrap,
    )




