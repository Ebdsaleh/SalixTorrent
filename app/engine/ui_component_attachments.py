"""SalixTorrent adapters for reusable GUI component attachments.

The generic component layer knows only about renderer-neutral tooltip text.
This application adapter translates SalixTorrent Help/Glossary terms into that
contract without teaching framework controls about torrent-specific semantics.

Names in the GUI/RAD extraction remain provisional until the reusable framework
boundary and public API are complete.
"""

from __future__ import annotations

from app.engine.components.attachments import Tooltip
from app.localization.documents import canonical_glossary_entries, glossary_entry


_HELP_TERMS = canonical_glossary_entries()


def _help_text(term: str) -> str:
    key = str(term or "").upper()
    entry = _HELP_TERMS.get(key)
    if not entry:
        return ""
    title, body = glossary_entry(key, entry)
    return f"{title}\n\n{body}"


def help_tooltip(term: str, *, wrap: int = 450) -> Tooltip:
    return Tooltip(_help_text(term), wrap=wrap)


def text_tooltip(text: str, *, wrap: int = 450) -> Tooltip:
    return Tooltip(str(text), wrap=wrap)
