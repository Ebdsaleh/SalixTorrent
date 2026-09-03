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
]
