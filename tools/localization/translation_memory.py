"""Provider-neutral, storage-neutral translation memory.

The default/reference backend is deterministic JSON. The service contract intentionally has
no application, GUI, ORM, or translation-provider dependency so alternate storage
backends can replace it without changing translation-pipeline callers.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Protocol

try:
    from .contracts import placeholder_names, source_hash
except ImportError:
    from contracts import placeholder_names, source_hash


MEMORY_SCHEMA = 1
MEMORY_KIND = "salix-translation-memory"
DEFAULT_SOURCE_LOCALE = "en-AU"
SOURCE_LOCALE = DEFAULT_SOURCE_LOCALE  # backward-compatible public alias
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
    source_locale: str
    target_locales: int
    entries: int
    reusable: int
    reviewed: int
    machine: int
    seeded: int

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "source_locale": self.source_locale,
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
    """Complete storage contract consumed by localization development tooling."""

    source_locale: str

    def lookup(self, target_locale: str, catalog: str, source: str) -> MemoryEntry | None: ...
    def put(self, entry: MemoryEntry) -> None: ...
    def iter_entries(self) -> Iterable[MemoryEntry]: ...
    def stats(self) -> MemoryStats: ...
    def audit(self) -> MemoryAudit: ...
    def save(self) -> None: ...


def validate_memory_entry(entry: MemoryEntry) -> MemoryEntry:
    """Validate one backend-neutral translation-memory entry.

    Storage adapters call this before accepting a write and again when decoding
    persisted state. Database constraints remain authoritative for physical
    integrity; these checks protect the semantic source/placeholder contract.
    """
    if not isinstance(entry.target_locale, str) or not entry.target_locale.strip():
        raise ValueError("translation-memory target locale cannot be empty")
    if not isinstance(entry.catalog, str) or not entry.catalog.strip():
        raise ValueError("translation-memory catalog cannot be empty")
    if not isinstance(entry.source, str) or not entry.source:
        raise ValueError("translation-memory source is missing/invalid")
    if not isinstance(entry.translation, str) or not entry.translation.strip():
        raise ValueError("translation-memory translation is missing/empty")

    expected_hash = source_hash(entry.source)
    if entry.source_hash != expected_hash:
        raise ValueError("translation-memory source hash does not match source text")

    expected_placeholders = tuple(sorted(placeholder_names(entry.source)))
    if tuple(sorted(str(x) for x in entry.placeholders)) != expected_placeholders:
        raise ValueError("translation-memory placeholder metadata does not match source")
    if tuple(sorted(placeholder_names(entry.translation))) != expected_placeholders:
        raise ValueError("translation-memory translation placeholder contract is invalid")
    return entry


def memory_identity(entry: MemoryEntry) -> tuple[str, str, str]:
    """Return the portable storage identity for one memory entry."""
    validate_memory_entry(entry)
    return (entry.target_locale, entry.catalog, entry.source_hash)


def merge_memory_stores(
    target: TranslationMemoryStore,
    source: TranslationMemoryStore,
) -> dict[str, int]:
    """Merge one compatible store into another without overwriting conflicts."""
    if str(target.source_locale) != str(source.source_locale):
        raise ValueError(
            f"translation-memory source locale {source.source_locale!r} does not match "
            f"target {target.source_locale!r}"
        )

    current = {memory_identity(entry): entry for entry in target.iter_entries()}
    added = reused = conflicts = 0
    for candidate in source.iter_entries():
        identity = memory_identity(candidate)
        existing = current.get(identity)
        if existing is None:
            target.put(candidate)
            current[identity] = candidate
            added += 1
        elif existing == candidate:
            reused += 1
        else:
            # Never silently replace one candidate translation with another.
            conflicts += 1
    return {"added": added, "reused": reused, "conflicts": conflicts}


def _empty_memory(source_locale: str = DEFAULT_SOURCE_LOCALE) -> dict:
    locale = str(source_locale or "").strip()
    if not locale:
        raise ValueError("translation-memory source locale cannot be empty")
    return {
        "_meta": {
            "schema": MEMORY_SCHEMA,
            "kind": MEMORY_KIND,
            "source_locale": locale,
        },
        "entries": {},
    }


def resolve_memory_path(
    explicit: str | os.PathLike[str] | None = None,
    *,
    cache_path: Path | None = None,
) -> Path:
    """Resolve JSON memory path without hard-coding a repository location.

    Explicit argument wins, then SALIX_LOCALIZATION_MEMORY. Otherwise the
    memory lives beside the translation cache. The latter also keeps isolated
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

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        source_locale: str = DEFAULT_SOURCE_LOCALE,
    ):
        self.path = Path(path)
        self.source_locale = str(source_locale or "").strip()
        if not self.source_locale:
            raise ValueError("translation-memory source locale cannot be empty")
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_memory(self.source_locale)
        if not isinstance(raw, dict):
            return _empty_memory(self.source_locale)
        meta = raw.get("_meta", {})
        if not isinstance(meta, dict):
            return _empty_memory(self.source_locale)
        if meta.get("kind") != MEMORY_KIND or meta.get("schema") != MEMORY_SCHEMA:
            return _empty_memory(self.source_locale)
        declared_source = str(meta.get("source_locale") or "").strip()
        if not declared_source:
            return _empty_memory(self.source_locale)
        if declared_source != self.source_locale:
            raise ValueError(
                f"translation-memory source locale {declared_source!r} does not match requested {self.source_locale!r}"
            )
        if not isinstance(raw.get("entries"), dict):
            return _empty_memory(self.source_locale)
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
        entry = MemoryEntry(
            target_locale=str(target_locale),
            catalog=catalog,
            source=source,
            source_hash=expected_hash,
            translation=translation,
            status=str(raw.get("status") or "machine"),
            provider=str(raw.get("provider") or ""),
            model=str(raw.get("model") or ""),
            placeholders=tuple(sorted(str(x) for x in raw.get("placeholders", []))),
            reusable=bool(raw.get("reusable", True)),
        )
        validate_memory_entry(entry)
        return entry

    def lookup(self, target_locale: str, catalog: str, source: str) -> MemoryEntry | None:
        key = self._entry_key(catalog, source)
        raw = self._data.get("entries", {}).get(target_locale, {}).get(key)
        if raw is None:
            return None
        try:
            entry = self._decode_entry(target_locale, key, raw)
        except ValueError:
            return None
        # The exact source text is checked in addition to the hash so a hash
        # collision/corrupt record can never be reused as another string.
        if entry.source != source:
            return None
        return entry if entry.reusable else None

    def put(self, entry: MemoryEntry) -> None:
        validate_memory_entry(entry)
        key = self._entry_key(entry.catalog, entry.source)
        self._data.setdefault("entries", {}).setdefault(entry.target_locale, {})[key] = entry.as_dict()

    def iter_entries(self) -> Iterator[MemoryEntry]:
        entries = self._data.get("entries", {})
        if not isinstance(entries, dict):
            raise ValueError("memory entries is not an object")
        for locale, values in sorted(entries.items()):
            if not isinstance(values, dict):
                raise ValueError(f"{locale}: locale memory is not an object")
            for key, raw in sorted(values.items()):
                yield self._decode_entry(str(locale), str(key), raw)

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
            source_locale = str(meta.get("source_locale") or "").strip()
            if not source_locale:
                errors.append("memory source locale is missing")
            elif source_locale != self.source_locale:
                errors.append(
                    f"memory source locale {source_locale!r} does not match requested {self.source_locale!r}"
                )
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
        """Merge compatible JSON memory without overwriting conflicts."""
        other = JsonTranslationMemory(other_path, source_locale=self.source_locale)
        return merge_memory_stores(self, other)

    def stats(self) -> MemoryStats:
        entries = reusable = reviewed = machine = seeded = 0
        locales: set[str] = set()
        for entry in self.iter_entries():
            locales.add(entry.target_locale)
            entries += 1
            if entry.reusable:
                reusable += 1
            if entry.status in {"reviewed", "locked"}:
                reviewed += 1
            elif entry.status == "seeded-existing":
                seeded += 1
            elif entry.status:
                machine += 1
        return MemoryStats(
            path=str(self.path),
            source_locale=self.source_locale,
            target_locales=len(locales),
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
