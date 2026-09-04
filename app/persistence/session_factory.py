"""Backend selection for SalixTorrent transfer/session persistence."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from .session_state import (
    FallbackSessionStateStore,
    JsonSessionStateStore,
    SessionStateStore,
    SessionStateStoreError,
)


SESSION_BACKEND_ENV = "SALIX_T_SESSION_BACKEND"
SESSION_URL_ENV = "SALIX_T_SESSION_URL"
SUPPORTED_SESSION_BACKENDS = ("json", "salixorm")
DEFAULT_SESSION_DATABASE = "session.db"


def resolve_session_backend(value: object | None = None) -> str:
    raw = value if value is not None else os.environ.get(SESSION_BACKEND_ENV, "json")
    backend = str(raw or "json").strip().lower()
    if backend not in SUPPORTED_SESSION_BACKENDS:
        raise SessionStateStoreError(
            f"Unsupported session-state backend {backend!r}; expected one of "
            + ", ".join(SUPPORTED_SESSION_BACKENDS)
        )
    return backend


def resolve_session_target(
    state_dir: str | os.PathLike[str],
    value: object | None = None,
) -> str:
    raw = value if value is not None else os.environ.get(SESSION_URL_ENV, "")
    text = str(raw or "").strip()
    if text:
        return text
    return str(Path(state_dir).expanduser().resolve() / DEFAULT_SESSION_DATABASE)


def build_session_state_store(
    state_dir: str | os.PathLike[str],
    *,
    backend: object | None = None,
    database_url: object | None = None,
) -> SessionStateStore:
    """Build the configured session store without eagerly importing SalixORM."""

    state_path = Path(state_dir).expanduser().resolve()
    json_store = JsonSessionStateStore(state_path / "session.json")
    selected = resolve_session_backend(backend)
    if selected == "json":
        return json_store

    try:
        module_name = ".".join(("app", "persistence", "session_salixorm"))
        module = importlib.import_module(module_name)
        store_type = getattr(module, "SalixORMSessionStateStore")
    except (AttributeError, ImportError, RuntimeError) as exc:
        raise SessionStateStoreError(
            "The SalixORM session-state backend requires SalixORM v0.2.0 or newer. "
            "For sibling source checkouts, install it into the SalixTorrent environment with "
            "`python -m pip install -e ..\\SalixORM`."
        ) from exc

    primary = store_type(resolve_session_target(state_path, database_url))
    return FallbackSessionStateStore(primary, json_store)
