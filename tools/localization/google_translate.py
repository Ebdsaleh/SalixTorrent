"""Build-time Google Cloud translation pipeline for SalixTorrent developers.

This module is *never* required by the released client.  It converts the
canonical en-AU catalogs into bundled locale catalogs during development and
keeps the result reproducible through a checked-in source-hash cache.
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Protocol

try:
    from .contracts import placeholder_names as placeholders, source_hash
except ImportError:  # direct script execution
    from contracts import placeholder_names as placeholders, source_hash


ROOT = Path(__file__).resolve().parents[2]
LOCALE_ROOT = ROOT / "app" / "localization" / "locales"
TOOLS_ROOT = Path(__file__).resolve().parent
CACHE_PATH = TOOLS_ROOT / "translation_cache.json"
MANIFEST_PATH = TOOLS_ROOT / "extraction_manifest.json"
PROTECTED_PATH = TOOLS_ROOT / "protected_terms.json"
OVERRIDES_ROOT = TOOLS_ROOT / "manual_overrides"
SOURCE_LOCALE = "en-AU"
CATALOGS = ("ui", "help", "glossary")
CACHE_SCHEMA = 2
DEFAULT_MODEL = "general/translation-llm"
DEFAULT_LOCATION = "global"
MAX_BATCH_ITEMS = 100
MAX_BATCH_CHARS = 24000
_MANIFEST_CACHE_KEY: tuple[str, int, int] | None = None
_MANIFEST_CACHE_VALUE: dict = {}

# Runtime locale -> Google Translation language code.  SalixTorrent owns its
# runtime BCP-47 locale names; provider mappings stay confined to this tool.
TARGET_CODES = {
    "en-GB": "en-GB",
    "en-US": "en-US",
    "pt-BR": "pt-BR",
    "fil-PH": "fil",
}


class TranslationProvider(Protocol):
    """Small provider contract used by the pipeline and regression tests."""

    provider_name: str
    model_name: str

    def translate_batch(self, texts: list[str], target_code: str) -> list[str]: ...


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _atomic_write_json(path: Path, value) -> None:
    """Write deterministic JSON through a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _protected_terms() -> list[str]:
    raw = _load_json(PROTECTED_PATH, {})
    values = raw.get("terms", []) if isinstance(raw, dict) else []
    return sorted({str(x) for x in values if str(x)}, key=len, reverse=True)


def protect_text(text: str) -> tuple[str, Dict[str, str]]:
    """Replace placeholders/technical vocabulary with opaque stable tokens."""
    protected: Dict[str, str] = {}
    output = str(text)

    # Exact Python format placeholders are protected first, preserving format
    # specifiers/conversions while keeping the provider away from the braces.
    fields = sorted(placeholders(output), key=len, reverse=True)
    for field in fields:
        pattern = re.compile(r"\{" + re.escape(field) + r"(?:![^}:]+)?(?::[^}]*)?\}")
        for match in list(pattern.finditer(output)):
            original = match.group(0)
            token = f"SALIXTOKEN{len(protected):04d}X"
            protected[token] = original
            output = output.replace(original, token)

    for term in _protected_terms():
        if term not in output:
            continue
        token = f"SALIXTOKEN{len(protected):04d}X"
        protected[token] = term
        output = output.replace(term, token)
    return output, protected


def restore_text(text: str, protected: Dict[str, str]) -> str:
    """Restore protected material or fail closed if the provider changed it."""
    output = html.unescape(str(text))
    for token, original in protected.items():
        if token not in output:
            raise ValueError(f"Translation provider lost protected token {token}")
        output = output.replace(token, original)
    return output


def _resolve_project_id(explicit: str | None = None) -> tuple[str, str]:
    """Resolve the Google project without reading project-specific files."""
    candidates = (
        ("argument", explicit),
        ("SALIX_T_GOOGLE_PROJECT", os.environ.get("SALIX_T_GOOGLE_PROJECT")),
        ("GOOGLE_CLOUD_PROJECT", os.environ.get("GOOGLE_CLOUD_PROJECT")),
        ("GCLOUD_PROJECT", os.environ.get("GCLOUD_PROJECT")),
    )
    for source, value in candidates:
        resolved = str(value or "").strip()
        if resolved:
            return resolved, source

    # Application Default Credentials can also provide the quota/project ID.
    try:
        import google.auth

        _credentials, discovered_project = google.auth.default()
    except Exception:
        discovered_project = None
    if discovered_project:
        return str(discovered_project), "Application Default Credentials"

    raise RuntimeError(
        "No Google Cloud project could be resolved. Set SALIX_T_GOOGLE_PROJECT "
        "(preferred) or GOOGLE_CLOUD_PROJECT, or configure Application Default "
        "Credentials with a project before running --translate."
    )


class GoogleTranslator:
    """Cloud Translation v3 adapter used only by the development pipeline."""

    provider_name = "google-cloud-translate-v3"

    def __init__(
        self,
        project_id: str | None = None,
        *,
        location: str | None = None,
        model: str | None = None,
        client=None,
        max_attempts: int = 4,
    ):
        self.project_id, self.project_source = _resolve_project_id(project_id)
        self.location = str(location or os.environ.get("SALIX_T_GOOGLE_LOCATION") or DEFAULT_LOCATION).strip()
        self.model_name = str(model or os.environ.get("SALIX_T_GOOGLE_MODEL") or DEFAULT_MODEL).strip()
        self.max_attempts = max(1, int(max_attempts))

        try:
            from google.cloud import translate_v3
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-translate is not installed. Run: "
                "python -m pip install -r requirements-localization.txt"
            ) from exc

        self._translate_v3 = translate_v3
        self.client = client or translate_v3.TranslationServiceClient()
        self.parent = f"projects/{self.project_id}/locations/{self.location}"
        self.model_resource = f"{self.parent}/models/{self.model_name}"

    def translate_batch(self, texts: list[str], target_code: str) -> list[str]:
        if not texts:
            return []

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.translate_text(
                    contents=texts,
                    parent=self.parent,
                    model=self.model_resource,
                    mime_type="text/plain",
                    source_language_code=SOURCE_LOCALE,
                    target_language_code=target_code,
                )
                values = [html.unescape(str(item.translated_text)) for item in response.translations]
                if len(values) != len(texts):
                    raise RuntimeError("Google returned an unexpected translation count")
                return values
            except Exception as exc:  # retry only errors classified as transient below
                last_error = exc
                if attempt >= self.max_attempts or not self._is_transient(exc):
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        try:
            from google.api_core import exceptions as google_exceptions

            transient = (
                google_exceptions.TooManyRequests,
                google_exceptions.ServiceUnavailable,
                google_exceptions.DeadlineExceeded,
                google_exceptions.InternalServerError,
            )
            return isinstance(exc, transient)
        except Exception:
            return False


@dataclass(frozen=True)
class TranslationStats:
    locale: str
    cached: int = 0
    overridden: int = 0
    translated: int = 0
    would_translate: int = 0
    missing: int = 0
    batches: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "locale": self.locale,
            "cached": self.cached,
            "overridden": self.overridden,
            "translated": self.translated,
            "would_translate": self.would_translate,
            "missing": self.missing,
            "batches": self.batches,
        }


def _catalog_strings(locale: str, catalog: str) -> Dict[str, str]:
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    raw = _load_json(path, {})
    values = raw.get("strings", {}) if isinstance(raw, dict) else {}
    return {str(k): str(v) for k, v in values.items() if isinstance(v, str)}


def _manual_override_records(locale: str) -> Dict[str, Dict[str, dict]]:
    """Load authoritative manual-review records without discarding metadata.

    Legacy string values remain supported. Stage 8A writes rich records carrying
    source hashes, review state, lock state, reviewer notes and timestamps.
    """
    raw = _load_json(OVERRIDES_ROOT / f"{locale}.json", {})
    result: Dict[str, Dict[str, dict]] = {}
    if not isinstance(raw, dict):
        return result
    for catalog, values in raw.items():
        if str(catalog).startswith("_") or not isinstance(values, dict):
            continue
        out: Dict[str, dict] = {}
        for key, value in values.items():
            if isinstance(value, str):
                out[str(key)] = {
                    "translation": value,
                    "status": "reviewed",
                    "locked": False,
                }
            elif isinstance(value, dict) and isinstance(value.get("translation"), str):
                record = dict(value)
                record["translation"] = str(value["translation"])
                out[str(key)] = record
        result[str(catalog)] = out
    return result


def _manual_overrides(locale: str) -> Dict[str, Dict[str, str]]:
    """Compatibility view returning only authoritative translation text."""
    records = _manual_override_records(locale)
    return {
        catalog: {key: str(record["translation"]) for key, record in values.items()}
        for catalog, values in records.items()
    }


def _manual_override_for_source(
    locale: str,
    catalog: str,
    key: str,
    source_text: str,
    records: Dict[str, Dict[str, dict]],
) -> str | None:
    """Return a manual translation, refusing known-stale reviewed records."""
    record = records.get(catalog, {}).get(key)
    if not isinstance(record, dict):
        return None
    recorded_hash = str(record.get("source_hash") or "")
    expected_hash = _manifest_hash(catalog, key, source_text)
    if recorded_hash and recorded_hash != expected_hash:
        raise ValueError(
            f"{locale}/{catalog}:{key}: manual override is stale; canonical source changed after review"
        )
    final = str(record.get("translation") or "")
    _validate_final(locale, catalog, key, source_text, final)
    return final


def _new_cache() -> dict:
    return {
        "_meta": {
            "schema": CACHE_SCHEMA,
            "source_locale": SOURCE_LOCALE,
            "provider": "google-cloud-translate-v3",
        },
        "entries": {},
    }


def _load_cache() -> dict:
    raw = _load_json(CACHE_PATH, _new_cache())
    if not isinstance(raw, dict):
        return _new_cache()
    if raw.get("_meta", {}).get("schema") == CACHE_SCHEMA and isinstance(raw.get("entries"), dict):
        return raw

    # Stage-1/4 used a flat ``locale:catalog:key`` cache.  Migrate it in memory
    # so old working copies remain compatible with Stage 5.
    migrated = _new_cache()
    entries = migrated["entries"]
    for flat_key, value in raw.items():
        if not isinstance(flat_key, str) or not isinstance(value, dict):
            continue
        parts = flat_key.split(":", 2)
        if len(parts) != 3:
            continue
        locale, catalog, key = parts
        entries.setdefault(locale, {}).setdefault(catalog, {})[key] = value
    return migrated


def _cache_entry(cache: dict, locale: str, catalog: str, key: str) -> dict:
    value = (
        cache.get("entries", {})
        .get(locale, {})
        .get(catalog, {})
        .get(key, {})
    )
    return value if isinstance(value, dict) else {}


def _set_cache_entry(cache: dict, locale: str, catalog: str, key: str, value: dict) -> None:
    cache.setdefault("entries", {}).setdefault(locale, {}).setdefault(catalog, {})[key] = value


def _manifest_data() -> dict:
    """Load extraction metadata once per on-disk manifest revision."""
    global _MANIFEST_CACHE_KEY, _MANIFEST_CACHE_VALUE
    try:
        stat = MANIFEST_PATH.stat()
        cache_key = (str(MANIFEST_PATH), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        cache_key = (str(MANIFEST_PATH), -1, -1)
    if cache_key != _MANIFEST_CACHE_KEY:
        raw = _load_json(MANIFEST_PATH, {})
        _MANIFEST_CACHE_VALUE = raw if isinstance(raw, dict) else {}
        _MANIFEST_CACHE_KEY = cache_key
    return _MANIFEST_CACHE_VALUE


def _manifest_hash(catalog: str, key: str, text: str) -> str:
    manifest = _manifest_data()
    try:
        value = manifest["catalogs"][catalog]["entries"][key]["source_hash"]
    except (KeyError, TypeError):
        value = source_hash(text)
    return str(value)


def _validate_final(locale: str, catalog: str, key: str, source_text: str, translated: str) -> None:
    if source_text.strip() and not translated.strip():
        raise ValueError(f"{locale}/{catalog}:{key}: translation is empty")
    if placeholders(translated) != placeholders(source_text):
        raise ValueError(
            f"{locale}/{catalog}:{key}: translated placeholders do not match source"
        )


def _chunks(
    items: list[tuple[str, str, Dict[str, str]]],
    *,
    max_chars: int = MAX_BATCH_CHARS,
    max_items: int = MAX_BATCH_ITEMS,
):
    batch: list[tuple[str, str, Dict[str, str]]] = []
    size = 0
    for item in items:
        item_size = len(item[1])
        if item_size > max_chars:
            raise ValueError(
                f"Localization entry {item[0]!r} is {item_size} characters; "
                f"the Stage-5 synchronous translation batch limit is {max_chars}."
            )
        if batch and (size + item_size > max_chars or len(batch) >= max_items):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += item_size
    if batch:
        yield batch


def bootstrap_translation_cache(*, write: bool = True) -> dict[str, int]:
    """Adopt the pre-Stage-5 bundled translations into the hash cache once.

    This preserves the 113 hand-seeded UI strings per target locale while
    making them subject to normal source-hash invalidation from now on.
    """
    cache = _load_cache()
    stats: dict[str, int] = {}
    for locale in sorted(TARGET_CODES):
        adopted = 0
        for catalog in CATALOGS:
            source = _catalog_strings(SOURCE_LOCALE, catalog)
            target = _catalog_strings(locale, catalog)
            for key, translation in target.items():
                if key not in source or _cache_entry(cache, locale, catalog, key):
                    continue
                _validate_final(locale, catalog, key, source[key], translation)
                _set_cache_entry(
                    cache,
                    locale,
                    catalog,
                    key,
                    {
                        "source_hash": _manifest_hash(catalog, key, source[key]),
                        "translation": translation,
                        "status": "seeded-existing",
                    },
                )
                adopted += 1
        stats[locale] = adopted
    if write:
        _atomic_write_json(CACHE_PATH, cache)
    return stats


def _prune_locale_cache(cache: dict, locale: str) -> None:
    locale_entries = cache.setdefault("entries", {}).setdefault(locale, {})
    for catalog in CATALOGS:
        source = _catalog_strings(SOURCE_LOCALE, catalog)
        values = locale_entries.setdefault(catalog, {})
        for key in list(values):
            if key not in source:
                del values[key]


def translation_plan(locale: str, *, force: bool = False) -> TranslationStats:
    """Return a deterministic plan without loading Google libraries or writing."""
    if locale not in TARGET_CODES:
        raise ValueError(f"Unsupported translation target {locale!r}")
    cache = _load_cache()
    override_records = _manual_override_records(locale)
    cached = overridden = would_translate = 0
    for catalog in CATALOGS:
        source = _catalog_strings(SOURCE_LOCALE, catalog)
        for key, source_text in source.items():
            manual = _manual_override_for_source(locale, catalog, key, source_text, override_records)
            if manual is not None:
                overridden += 1
                continue
            entry = _cache_entry(cache, locale, catalog, key)
            expected_hash = _manifest_hash(catalog, key, source_text)
            if (
                not force
                and entry.get("source_hash") == expected_hash
                and isinstance(entry.get("translation"), str)
            ):
                _validate_final(locale, catalog, key, source_text, entry["translation"])
                cached += 1
            else:
                would_translate += 1
    return TranslationStats(
        locale=locale,
        cached=cached,
        overridden=overridden,
        would_translate=would_translate,
    )


def translate_locale(
    locale: str,
    *,
    force: bool = False,
    no_network: bool = False,
    dry_run: bool = False,
    project_id: str | None = None,
    location: str | None = None,
    model: str | None = None,
    provider: TranslationProvider | None = None,
) -> dict[str, int | str]:
    """Build one locale from overrides/cache and optionally Google Cloud.

    No target or cache file is changed until *all* provider calls and contract
    checks for this locale have succeeded.  A provider/authentication failure
    therefore leaves the previously packaged locale intact.
    """
    if locale not in TARGET_CODES:
        raise ValueError(f"Unsupported translation target {locale!r}")

    if dry_run:
        return translation_plan(locale, force=force).as_dict()

    cache = _load_cache()
    override_records = _manual_override_records(locale)
    _prune_locale_cache(cache, locale)
    catalog_payloads: dict[str, dict] = {}
    cached = overridden = translated_count = missing = batches = 0

    # Instantiate Google lazily only if an entry actually needs the network.
    active_provider = provider

    for catalog in CATALOGS:
        source = _catalog_strings(SOURCE_LOCALE, catalog)
        pending: list[tuple[str, str, Dict[str, str]]] = []
        result: Dict[str, str] = {}

        for key, source_text in source.items():
            manual = _manual_override_for_source(locale, catalog, key, source_text, override_records)
            if manual is not None:
                result[key] = manual
                overridden += 1
                continue

            expected_hash = _manifest_hash(catalog, key, source_text)
            cached_entry = _cache_entry(cache, locale, catalog, key)
            if (
                not force
                and cached_entry.get("source_hash") == expected_hash
                and isinstance(cached_entry.get("translation"), str)
            ):
                final = str(cached_entry["translation"])
                _validate_final(locale, catalog, key, source_text, final)
                result[key] = final
                cached += 1
                continue

            protected_text, protected = protect_text(source_text)
            pending.append((key, protected_text, protected))

        if pending and no_network:
            # Deliberately *do not* trust old generated locale files: without a
            # matching source hash they may describe an older canonical string.
            # Missing entries stay absent and the runtime uses en-AU fallback.
            missing += len(pending)
        elif pending:
            if active_provider is None:
                active_provider = GoogleTranslator(
                    project_id=project_id,
                    location=location,
                    model=model,
                )
            for batch in _chunks(pending):
                batches += 1
                raw_translations = active_provider.translate_batch(
                    [item[1] for item in batch], TARGET_CODES[locale]
                )
                if len(raw_translations) != len(batch):
                    raise RuntimeError("Translation provider returned an unexpected translation count")
                for (key, _protected_text, protected), raw_translation in zip(batch, raw_translations):
                    final = restore_text(raw_translation, protected)
                    _validate_final(locale, catalog, key, source[key], final)
                    result[key] = final
                    _set_cache_entry(
                        cache,
                        locale,
                        catalog,
                        key,
                        {
                            "source_hash": _manifest_hash(catalog, key, source[key]),
                            "translation": final,
                            "status": "machine",
                            "provider": getattr(active_provider, "provider_name", "translation-provider"),
                            "model": getattr(active_provider, "model_name", "unknown"),
                        },
                    )
                    translated_count += 1

        catalog_payloads[catalog] = {
            "_meta": {
                "locale": locale,
                "source_locale": SOURCE_LOCALE,
                "catalog": catalog,
                "generated_by": "tools/localization/google_translate.py",
            },
            "strings": dict(sorted(result.items())),
        }

    # Provider work has completed successfully.  Commit deterministic artifacts
    # atomically one file at a time; cache is written last so an interrupted
    # locale write can only cause harmless retranslation on the next run.
    for catalog in CATALOGS:
        _atomic_write_json(LOCALE_ROOT / locale / f"{catalog}.json", catalog_payloads[catalog])
    _atomic_write_json(CACHE_PATH, cache)

    return TranslationStats(
        locale=locale,
        cached=cached,
        overridden=overridden,
        translated=translated_count,
        missing=missing,
        batches=batches,
    ).as_dict()
