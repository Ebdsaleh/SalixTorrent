# app/views/help_terms.py

from __future__ import annotations

from typing import Iterable, Optional

from app.engine.components.renderer import get_default_renderer

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
    """Attach arbitrary explanatory text through the active GUI renderer.

    The renderer owns backend-specific tooltip creation and failure isolation,
    keeping application Help/Glossary adapters independent of Dear PyGui's
    container-stack behavior.
    """
    return get_default_renderer().attach_tooltip(item, str(text), wrap=wrap)


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




