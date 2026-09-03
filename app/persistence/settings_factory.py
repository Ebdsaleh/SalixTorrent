"""Backend selection for SalixTorrent application-settings persistence."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from .settings import (
    AppSettingsStore,
    AppSettingsStoreError,
    FallbackAppSettingsStore,
    JsonAppSettingsStore,
)


SETTINGS_BACKEND_ENV = "SALIX_T_SETTINGS_BACKEND"
SETTINGS_URL_ENV = "SALIX_T_SETTINGS_URL"
SUPPORTED_SETTINGS_BACKENDS = ("json", "salixorm")
DEFAULT_SETTINGS_DATABASE = "settings.db"


def resolve_settings_backend(value: object | None = None) -> str:
    raw = value if value is not None else os.environ.get(SETTINGS_BACKEND_ENV, "json")
    backend = str(raw or "json").strip().lower()
    if backend not in SUPPORTED_SETTINGS_BACKENDS:
        raise AppSettingsStoreError(
            f"Unsupported application-settings backend {backend!r}; expected one of "
            + ", ".join(SUPPORTED_SETTINGS_BACKENDS)
        )
    return backend


def resolve_settings_target(
    state_dir: str | os.PathLike[str],
    value: object | None = None,
) -> str:
    raw = value if value is not None else os.environ.get(SETTINGS_URL_ENV, "")
    text = str(raw or "").strip()
    if text:
        return text
    return str(Path(state_dir).expanduser().resolve() / DEFAULT_SETTINGS_DATABASE)


def build_app_settings_store(
    state_dir: str | os.PathLike[str],
    *,
    backend: object | None = None,
    database_url: object | None = None,
) -> AppSettingsStore:
    """Build the configured settings store without eagerly importing SalixORM."""

    state_path = Path(state_dir).expanduser().resolve()
    json_store = JsonAppSettingsStore(state_path / "settings.json")
    selected = resolve_settings_backend(backend)
    if selected == "json":
        return json_store

    try:
        # Keep the optional backend out of the normal import graph. This is
        # deliberate for frozen builds: merely having SalixORM installed in a
        # development environment must not make it an accidental packaged
        # runtime dependency. Source/development runs opt in explicitly.
        module_name = ".".join(("app", "persistence", "settings_salixorm"))
        module = importlib.import_module(module_name)
        store_type = getattr(module, "SalixORMAppSettingsStore")
    except (AttributeError, ImportError, RuntimeError) as exc:
        raise AppSettingsStoreError(
            "The SalixORM application-settings backend requires SalixORM v0.2.0 or newer. "
            "For sibling source checkouts, install it into the SalixTorrent environment with "
            "`python -m pip install -e ..\\SalixORM`."
        ) from exc

    primary = store_type(resolve_settings_target(state_path, database_url))
    return FallbackAppSettingsStore(primary, json_store)
