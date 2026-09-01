"""Development pseudo-localization helpers.

``en-XA`` is not a production language pack.  It is generated in memory from
canonical en-AU text so developers can spot untranslated strings and exercise
text expansion without any network translation service.
"""

from __future__ import annotations

import re

PSEUDO_LOCALE = "en-XA"
PSEUDO_ENV = "SALIX_T_PSEUDO_LOCALE"

# Readable Latin substitutions deliberately expand the visual texture while
# remaining recognizable to an English-speaking developer.
_ACCENTS = str.maketrans(
    {
        "a": "à", "b": "ƀ", "c": "ç", "d": "đ", "e": "ë", "f": "ƒ",
        "g": "ğ", "h": "ħ", "i": "ï", "j": "ĵ", "k": "ķ", "l": "ľ",
        "m": "ɱ", "n": "ñ", "o": "ö", "p": "þ", "q": "ʠ", "r": "ŕ",
        "s": "š", "t": "ŧ", "u": "ü", "v": "ṽ", "w": "ŵ", "x": "ẋ",
        "y": "ÿ", "z": "ž",
        "A": "À", "B": "Ɓ", "C": "Ç", "D": "Đ", "E": "Ë", "F": "Ƒ",
        "G": "Ğ", "H": "Ħ", "I": "Ï", "J": "Ĵ", "K": "Ķ", "L": "Ľ",
        "M": "Ṁ", "N": "Ñ", "O": "Ö", "P": "Þ", "Q": "Ɋ", "R": "Ŕ",
        "S": "Š", "T": "Ŧ", "U": "Ü", "V": "Ṽ", "W": "Ŵ", "X": "Ẋ",
        "Y": "Ÿ", "Z": "Ž",
    }
)

# The runtime uses named ``str.format`` fields. Match only single-brace
# fields; escaped literal braces (``{{`` / ``}}``) remain untouched.
_FORMAT_FIELD = re.compile(r"(?<!\{)\{[^{}]+\}(?!\})")


def _accent_segment(text: str) -> str:
    return text.translate(_ACCENTS)


def pseudo_localize(text: object, *, expansion: float = 0.30) -> str:
    """Return deterministic, placeholder-safe pseudo-localized text.

    The result is accented, visibly bracketed and padded by roughly 30% so
    fixed-width assumptions and clipping are easier to discover. Format fields
    are byte-for-byte preserved for the normal runtime formatting contract.
    """
    source = str(text or "")
    if not source:
        return source

    pieces: list[str] = []
    cursor = 0
    visible_letters = 0
    for match in _FORMAT_FIELD.finditer(source):
        literal = source[cursor:match.start()]
        pieces.append(_accent_segment(literal))
        visible_letters += sum(char.isalpha() for char in literal)
        pieces.append(match.group(0))
        cursor = match.end()
    literal = source[cursor:]
    pieces.append(_accent_segment(literal))
    visible_letters += sum(char.isalpha() for char in literal)

    transformed = "".join(pieces)
    # Two-character pad units make the expansion intentionally noticeable. The
    # minimum unit also makes very short button labels easy to identify.
    target_extra = max(2, int(round(max(1, visible_letters) * max(0.0, expansion))))
    pad_units = max(1, (target_extra + 1) // 2)
    padding = " ·" * pad_units
    return f"[!! {transformed}{padding} !!]"


def pseudo_catalog(strings: dict[str, str]) -> dict[str, str]:
    return {str(key): pseudo_localize(value) for key, value in strings.items()}


