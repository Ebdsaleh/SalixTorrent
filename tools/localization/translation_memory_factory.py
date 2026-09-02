"""Development-time translation-memory backend selection.

The generic translation-memory contract remains storage-neutral. This module is the
single integration seam that selects concrete development storage backends.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from .translation_memory import (
        DEFAULT_SOURCE_LOCALE,
        JsonTranslationMemory,
        TranslationMemoryStore,
        resolve_memory_path,
    )
except ImportError:  # direct script execution
    from translation_memory import (
        DEFAULT_SOURCE_LOCALE,
        JsonTranslationMemory,
        TranslationMemoryStore,
        resolve_memory_path,
    )


DEFAULT_MEMORY_BACKEND = "json"
MEMORY_BACKEND_ENV = "SALIX_LOCALIZATION_MEMORY_BACKEND"
MEMORY_URL_ENV = "SALIX_LOCALIZATION_MEMORY_URL"
SUPPORTED_MEMORY_BACKENDS = ("json", "salixorm")


def resolve_memory_backend(explicit: str | None = None) -> str:
    backend = str(explicit or os.environ.get(MEMORY_BACKEND_ENV) or DEFAULT_MEMORY_BACKEND).strip().lower()
    if backend not in SUPPORTED_MEMORY_BACKENDS:
        raise ValueError(
            f"Unsupported translation-memory backend {backend!r}; expected one of "
            f"{', '.join(SUPPORTED_MEMORY_BACKENDS)}"
        )
    return backend


def resolve_salixorm_memory_target(
    *,
    explicit_url: str | None = None,
    explicit_path: str | os.PathLike[str] | None = None,
    cache_path: Path | None = None,
) -> str | Path:
    """Resolve a SalixORM SQLite target without reinterpreting the JSON path env.

    ``SALIX_LOCALIZATION_MEMORY`` remains the historical JSON-memory path. The
    SalixORM backend uses ``SALIX_LOCALIZATION_MEMORY_URL`` or an explicit
    ``--memory-url``. ``--memory-path`` is also accepted when the backend is
    explicitly selected as ``salixorm``.
    """
    url = str(explicit_url or os.environ.get(MEMORY_URL_ENV) or "").strip()
    if url:
        return url
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    if cache_path is None:
        cache_path = Path(__file__).resolve().with_name("translation_cache.json")
    return Path(cache_path).with_name("translation_memory.db").resolve()


def create_translation_memory_store(
    *,
    backend: str | None = None,
    memory_path: str | os.PathLike[str] | None = None,
    memory_url: str | None = None,
    cache_path: Path | None = None,
    source_locale: str = DEFAULT_SOURCE_LOCALE,
) -> TranslationMemoryStore:
    selected = resolve_memory_backend(backend)
    if selected == "json":
        if memory_url:
            raise ValueError("--memory-url is only valid with --memory-backend salixorm")
        return JsonTranslationMemory(
            resolve_memory_path(memory_path, cache_path=cache_path),
            source_locale=source_locale,
        )

    try:
        if __package__:
            from .translation_memory_salixorm import SalixORMTranslationMemory
        else:
            from translation_memory_salixorm import SalixORMTranslationMemory
    except ImportError as exc:
        raise RuntimeError(
            "The SalixORM translation-memory backend requires SalixORM v0.2.0 or newer. "
            "Install the released SalixORM package into this development environment "
            "before selecting --memory-backend salixorm."
        ) from exc

    target = resolve_salixorm_memory_target(
        explicit_url=memory_url,
        explicit_path=memory_path,
        cache_path=cache_path,
    )
    return SalixORMTranslationMemory(target, source_locale=source_locale)
