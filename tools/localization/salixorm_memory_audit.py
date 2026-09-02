"""Offline parity validation for the SalixORM translation-memory adapter."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from .translation_memory import JsonTranslationMemory, merge_memory_stores
    from .translation_memory_salixorm import SalixORMTranslationMemory
except ImportError:  # direct script execution
    from translation_memory import JsonTranslationMemory, merge_memory_stores
    from translation_memory_salixorm import SalixORMTranslationMemory


DEFAULT_JSON_MEMORY = Path(__file__).resolve().with_name("translation_memory.json")


@dataclass(frozen=True)
class SalixORMMemoryParityAudit:
    errors: tuple[str, ...]
    json_entries: int = 0
    salixorm_entries: int = 0
    added: int = 0
    reused: int = 0
    conflicts: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def salixorm_memory_parity_audit(
    source_path: str | Path | None = None,
) -> SalixORMMemoryParityAudit:
    """Import the project JSON memory into a temporary SalixORM DB and compare."""
    source = JsonTranslationMemory(source_path or DEFAULT_JSON_MEMORY)
    source_audit = source.audit()
    if not source_audit.ok:
        return SalixORMMemoryParityAudit(
            errors=tuple(f"JSON memory: {error}" for error in source_audit.errors),
        )

    source_entries = tuple(source.iter_entries())
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "translation_memory.db"
        target = SalixORMTranslationMemory(path, source_locale=source.source_locale)
        merged = merge_memory_stores(target, source)
        if merged["conflicts"]:
            return SalixORMMemoryParityAudit(
                errors=("unexpected conflict while importing canonical JSON memory",),
                json_entries=len(source_entries),
                added=merged["added"],
                reused=merged["reused"],
                conflicts=merged["conflicts"],
            )
        target.save()

        reopened = SalixORMTranslationMemory(path, source_locale=source.source_locale)
        target_audit = reopened.audit()
        errors = list(target_audit.errors)
        target_entries = tuple(reopened.iter_entries())
        if target_entries != source_entries:
            errors.append("SalixORM memory entries do not round-trip identically to JSON memory")
        # Compare semantic counters while ignoring backend-specific storage paths.
        left = reopened.stats().as_dict()
        right = source.stats().as_dict()
        left.pop("path", None)
        right.pop("path", None)
        if left != right:
            errors.append("SalixORM memory statistics do not match JSON memory statistics")

        return SalixORMMemoryParityAudit(
            errors=tuple(errors),
            json_entries=len(source_entries),
            salixorm_entries=len(target_entries),
            added=merged["added"],
            reused=merged["reused"],
            conflicts=merged["conflicts"],
        )
