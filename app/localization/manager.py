"""SalixTorrent compatibility facade over the framework-neutral runtime kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .framework import JsonCatalogRepository
from .locale_info import resolve_requested_locale
from .profile import CATALOG_NAMES, SALIXTORRENT_LOCALIZATION_PROFILE, salixtorrent_catalog_root
from .pseudo import pseudo_catalog
from .runtime import LocalizationRuntime, placeholder_names


class LocalizationManager(LocalizationRuntime):
    """Application singleton preserving the historical SalixTorrent API.

    All catalog/fallback/formatting behavior lives in ``LocalizationRuntime``.
    This subclass supplies only SalixTorrent resource and locale policy.
    """

    _instance: Optional["LocalizationManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        repository = JsonCatalogRepository(
            lambda locale: type(self).locale_root(locale),
            allowed_catalogs=CATALOG_NAMES,
        )
        super().__init__(
            profile=SALIXTORRENT_LOCALIZATION_PROFILE,
            repository=repository,
            locale_resolver=resolve_requested_locale,
            pseudo_catalog_factory=pseudo_catalog,
        )
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "LocalizationManager":
        return cls()

    @staticmethod
    def locale_root(locale_code: str) -> Path:
        # The generic runtime only sees a repository. Product bundle/resource
        # resolution remains inside this application adapter.
        return salixtorrent_catalog_root(locale_code)


_localization = LocalizationManager.get_instance()


def tr(key: str, default: Optional[str] = None, *, catalog: str = "ui", **values) -> str:
    return _localization.tr(key, default, catalog=catalog, **values)


def localization_manager() -> LocalizationManager:
    return _localization
