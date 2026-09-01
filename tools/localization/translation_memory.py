"""Provider-neutral translation memory for SalixTorrent development tooling.

The initial storage backend is deterministic JSON so the translation pipeline can
remain independent of any ORM/database package.  The public service API is
deliberately storage-neutral so a future SQLite/SalixORM backend can replace the
JSON store without changing callers.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

try:
    from .contracts import placeholder_names, source_hash
except ImportError:
    from contracts import placeholder_names, source_hash


MEMORY_SCHEMA = 1
MEMORY_KIND = "salix-translation-memory"
SOURCE_LOCALE = "en-AU"
MEMORY_ENV = "SALIX_LOCALIZATION_MEMORY"


@dataclass(frozen=True)
class MemoryEntry:
    target_locale: str
    catalog: str
    source: str
    source_hash: str
    translation: str
    status: str = "machine"
    provider: str = ""
    model: str = ""
    placeholders: tuple[str, ...] = ()
    reusable: bool = True

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "source_hash": self.source_hash,
            "translation": self.translation,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "placeholders": list(self.placeholders),
            "reusable": bool(self.reusable),
        }


@dataclass(frozen=True)
class MemoryStats:
    path: str
    target_locales: int
    entries: int
    reusable: int
    reviewed: int
    machine: int
    seeded: int

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "target_locales": self.target_locales,
            "entries": self.entries,
            "reusable": self.reusable,
            "reviewed": self.reviewed,
            "machine": self.machine,
            "seeded": self.seeded,
        }


@dataclass(frozen=True)
class MemoryAudit:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


class TranslationMemoryStore(Protocol):
    def lookup(self, target_locale: str, catalog: str, source: str) -> MemoryEntry | None: ...
    def put(self, entry: MemoryEntry) -> None: ...
    def stats(self) -> MemoryStats: ...
    def save(self) -> None: ...


def _empty_memory() -> dict:
    return {
        "_meta": {
            "schema": MEMORY_SCHEMA,
            "kind": MEMORY_KIND,
            "source_locale": SOURCE_LOCALE,
        },
        "entries": {},
    }


def resolve_memory_path(
    explicit: str | os.PathLike[str] | None = None,
    *,
    cache_path: Path | None = None,
) -> Path:
    """Resolve memory path without hard-coding a repository location.

    Explicit argument wins, then SALIX_LOCALIZATION_MEMORY.  Otherwise the
    memory lives beside the translation cache.  The latter also keeps isolated
    tests isolated when they patch CACHE_PATH to a temporary directory.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = str(os.environ.get(MEMORY_ENV) or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if cache_path is None:
        cache_path = Path(__file__).resolve().with_name("translation_cache.json")
    return Path(cache_path).with_name("translation_memory.json")


class JsonTranslationMemory:
    """Deterministic JSON implementation of the translation-memory service."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_memory()
        if not isinstance(raw, dict):
            return _empty_memory()
        meta = raw.get("_meta", {})
        if not isinstance(meta, dict):
            return _empty_memory()
        if meta.get("kind") != MEMORY_KIND or meta.get("schema") != MEMORY_SCHEMA:
            return _empty_memory()
        if not isinstance(raw.get("entries"), dict):
            return _empty_memory()
        return raw

    @staticmethod
    def _entry_key(catalog: str, source: str) -> str:
        # Catalog is part of identity to avoid unsafe reuse of very short text
        # between unrelated semantic domains (e.g. UI label vs glossary prose).
        return f"{catalog}:{source_hash(source)}"

    def _decode_entry(self, target_locale: str, key: str, raw: object) -> MemoryEntry:
        if not isinstance(raw, dict):
            raise ValueError("entry is not an object")
        if ":" not in key:
            raise ValueError("entry key does not contain a catalog prefix")
        catalog, recorded_hash = key.split(":", 1)
        source = raw.get("source")
        translation = raw.get("translation")
        if not isinstance(source, str) or not source:
            raise ValueError("source is missing/invalid")
        if not isinstance(translation, str) or not translation.strip():
            raise ValueError("translation is missing/empty")
        expected_hash = source_hash(source)
        if recorded_hash != expected_hash or str(raw.get("source_hash") or "") != expected_hash:
            raise ValueError("source hash does not match canonical source text")
        expected_placeholders = tuple(sorted(placeholder_names(source)))
        stored_placeholders = tuple(sorted(str(x) for x in raw.get("placeholders", [])))
        if stored_placeholders != expected_placeholders:
            raise ValueError("placeholder metadata does not match source")
        if tuple(sorted(placeholder_names(translation))) != expected_placeholders:
            raise ValueError("translation placeholder contract does not match source")
        return MemoryEntry(
            target_locale=str(target_locale),
            catalog=catalog,
            source=source,
            source_hash=expected_hash,
            translation=translation,
            status=str(raw.get("status") or "machine"),
            provider=str(raw.get("provider") or ""),
            model=str(raw.get("model") or ""),
            placeholders=expected_placeholders,
            reusable=bool(raw.get("reusable", True)),
        )

    def lookup(self, target_locale: str, catalog: str, source: str) -> MemoryEntry | None:
        key = self._entry_key(catalog, source)
        raw = self._data.get("entries", {}).get(target_locale, {}).get(key)
        if raw is None:
            return None
        try:
            entry = self._decode_entry(target_locale, key, raw)
        except ValueError:
            return None
        return entry if entry.reusable else None

    def put(self, entry: MemoryEntry) -> None:
        if entry.source_hash != source_hash(entry.source):
            raise ValueError("translation-memory source hash does not match source text")
        expected = tuple(sorted(placeholder_names(entry.source)))
        if tuple(sorted(entry.placeholders)) != expected:
            raise ValueError("translation-memory placeholder metadata does not match source")
        if tuple(sorted(placeholder_names(entry.translation))) != expected:
            raise ValueError("translation-memory translation placeholder contract is invalid")
        key = self._entry_key(entry.catalog, entry.source)
        self._data.setdefault("entries", {}).setdefault(entry.target_locale, {})[key] = entry.as_dict()

    def audit(self) -> MemoryAudit:
        errors: list[str] = []
        meta = self._data.get("_meta", {})
        if not isinstance(meta, dict):
            errors.append("memory metadata is not an object")
        else:
            if meta.get("kind") != MEMORY_KIND:
                errors.append("memory kind is invalid")
            if meta.get("schema") != MEMORY_SCHEMA:
                errors.append("memory schema is unsupported")
            if meta.get("source_locale") != SOURCE_LOCALE:
                errors.append("memory source locale is not en-AU")
        entries = self._data.get("entries", {})
        if not isinstance(entries, dict):
            errors.append("memory entries is not an object")
            return MemoryAudit(tuple(errors))
        for locale, values in sorted(entries.items()):
            if not isinstance(values, dict):
                errors.append(f"{locale}: locale memory is not an object")
                continue
            for key, raw in sorted(values.items()):
                try:
                    self._decode_entry(str(locale), str(key), raw)
                except ValueError as exc:
                    errors.append(f"{locale}/{key}: {exc}")
        return MemoryAudit(tuple(errors))

    def merge_from(self, other_path: str | os.PathLike[str]) -> dict[str, int]:
        """Merge compatible entries from another memory without overwriting conflicts."""
        other = JsonTranslationMemory(other_path)
        added = reused = conflicts = 0
        for locale, values in other._data.get("entries", {}).items():
            if not isinstance(values, dict):
                continue
            for key, raw in values.items():
                try:
                    other._decode_entry(str(locale), str(key), raw)
                except ValueError as exc:
                    raise ValueError(f"Cannot merge invalid translation-memory entry {locale}/{key}: {exc}") from exc
                current = self._data.setdefault("entries", {}).setdefault(locale, {}).get(key)
                if current is None:
                    self._data["entries"][locale][key] = copy.deepcopy(raw)
                    added += 1
                elif current == raw:
                    reused += 1
                else:
                    # Never silently replace one candidate translation with another.
                    conflicts += 1
        return {"added": added, "reused": reused, "conflicts": conflicts}

    def stats(self) -> MemoryStats:
        entries = reusable = reviewed = machine = seeded = 0
        locales = 0
        for _locale, values in self._data.get("entries", {}).items():
            if not isinstance(values, dict):
                continue
            locales += 1
            for raw in values.values():
                if not isinstance(raw, dict):
                    continue
                entries += 1
                if bool(raw.get("reusable", True)):
                    reusable += 1
                status = str(raw.get("status") or "")
                if status in {"reviewed", "locked"}:
                    reviewed += 1
                elif status == "seeded-existing":
                    seeded += 1
                elif status:
                    machine += 1
        return MemoryStats(
            path=str(self.path),
            target_locales=locales,
            entries=entries,
            reusable=reusable,
            reviewed=reviewed,
            machine=machine,
            seeded=seeded,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.path)

    def snapshot(self) -> dict:
        return copy.deepcopy(self._data)


def memory_entry(
    *,
    target_locale: str,
    catalog: str,
    source: str,
    translation: str,
    status: str,
    provider: str = "",
    model: str = "",
    reusable: bool = True,
) -> MemoryEntry:
    return MemoryEntry(
        target_locale=target_locale,
        catalog=catalog,
        source=str(source),
        source_hash=source_hash(source),
        translation=str(translation),
        status=str(status),
        provider=str(provider),
        model=str(model),
        placeholders=tuple(sorted(placeholder_names(source))),
        reusable=bool(reusable),
    )
