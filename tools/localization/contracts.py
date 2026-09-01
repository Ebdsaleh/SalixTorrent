"""Framework-neutral source-contract helpers for localization tooling."""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaceholderContract:
    """Normalized named-format contract discovered in one source string."""

    names: tuple[str, ...]
    fields: tuple[str, ...]
    malformed: bool = False


def source_hash(text: object) -> str:
    """Return the stable SHA-256 identity for canonical source text."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def placeholder_contract(text: object) -> PlaceholderContract:
    """Discover Python ``str.format`` fields without rendering the string.

    ``names`` contains the root names used for runtime compatibility checks,
    while ``fields`` retains the complete field expressions (including format
    specifications/conversions) for developer reports.
    """
    names: set[str] = set()
    fields: list[str] = []
    malformed = False
    try:
        for _literal, field, spec, conversion in string.Formatter().parse(str(text)):
            if not field:
                continue
            root = field.split(".", 1)[0].split("[", 1)[0]
            if root:
                names.add(root)
            rendered = "{" + field
            if conversion:
                rendered += f"!{conversion}"
            if spec:
                rendered += f":{spec}"
            rendered += "}"
            fields.append(rendered)
    except ValueError:
        malformed = True
    return PlaceholderContract(
        names=tuple(sorted(names)),
        fields=tuple(fields),
        malformed=malformed,
    )


def placeholder_names(text: object) -> set[str]:
    contract = placeholder_contract(text)
    if contract.malformed:
        return {"<malformed-format-string>"}
    return set(contract.names)


