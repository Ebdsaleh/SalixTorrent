"""Application persistence boundaries for SalixTorrent."""

from .settings import (
    AppSettingsStore,
    AppSettingsStoreError,
    FallbackAppSettingsStore,
    JsonAppSettingsStore,
)
from .settings_factory import (
    SETTINGS_BACKEND_ENV,
    SETTINGS_URL_ENV,
    SUPPORTED_SETTINGS_BACKENDS,
    build_app_settings_store,
    resolve_settings_backend,
    resolve_settings_target,
)
from .session_state import (
    CURRENT_SESSION_STATE_VERSION,
    FallbackSessionStateStore,
    JsonSessionStateStore,
    SessionStateStore,
    SessionStateStoreError,
)
from .session_factory import (
    SESSION_BACKEND_ENV,
    SESSION_URL_ENV,
    SUPPORTED_SESSION_BACKENDS,
    build_session_state_store,
    resolve_session_backend,
    resolve_session_target,
)

__all__ = [
    "AppSettingsStore",
    "AppSettingsStoreError",
    "FallbackAppSettingsStore",
    "JsonAppSettingsStore",
    "SETTINGS_BACKEND_ENV",
    "SETTINGS_URL_ENV",
    "SUPPORTED_SETTINGS_BACKENDS",
    "build_app_settings_store",
    "resolve_settings_backend",
    "resolve_settings_target",
    "CURRENT_SESSION_STATE_VERSION",
    "FallbackSessionStateStore",
    "JsonSessionStateStore",
    "SessionStateStore",
    "SessionStateStoreError",
    "SESSION_BACKEND_ENV",
    "SESSION_URL_ENV",
    "SUPPORTED_SESSION_BACKENDS",
    "build_session_state_store",
    "resolve_session_backend",
    "resolve_session_target",
]
