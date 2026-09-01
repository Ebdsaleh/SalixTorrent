"""Framework-neutral localization contracts and JSON catalog loading.

This module is intentionally independent of any product, GUI toolkit, runtime-path
helper, and translation provider.  It is the first runtime localization module
that can be lifted unchanged into the future Salix application framework.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol


@dataclass(frozen=True)
class LocaleDescriptor:
    """Provider-neutral runtime metadata for one locale."""

    code: str
    display_name: str
    native_name: str
    script: str = "Latn"
    text_direction: str = "ltr"
    font_profile: str = "latin"
    support_status: str = "partial"


@dataclass(frozen=True)
class LocalizationProfile:
    """Application-supplied policy consumed by reusable localization services.

    A profile contains only runtime/application policy. Translation-provider
    language codes deliberately do not belong here.
    """

    application_id: str
    canonical_locale: str
    auto_locale: str
    catalog_names: tuple[str, ...]
    locales: Mapping[str, LocaleDescriptor]
    pseudo_locale: str = ""
    pseudo_environment: str = ""

    def __post_init__(self) -> None:
        app_id = str(self.application_id or "").strip()
        canonical = str(self.canonical_locale or "").strip()
        catalogs = tuple(str(name).strip() for name in self.catalog_names if str(name).strip())
        if not app_id:
            raise ValueError("localization profile application_id cannot be empty")
        if not canonical:
            raise ValueError("localization profile canonical_locale cannot be empty")
        if not catalogs:
            raise ValueError("localization profile requires at least one catalog")
        if len(catalogs) != len(set(catalogs)):
            raise ValueError("localization profile catalog names must be unique")
        locale_map = dict(self.locales)
        if canonical not in locale_map:
            raise ValueError("canonical locale must exist in localization profile locales")
        for code, info in locale_map.items():
            if str(code) != info.code:
                raise ValueError(f"locale mapping key {code!r} does not match descriptor code {info.code!r}")
            if info.text_direction not in {"ltr", "rtl"}:
                raise ValueError(f"locale {code!r} has unsupported text direction {info.text_direction!r}")
        object.__setattr__(self, "application_id", app_id)
        object.__setattr__(self, "canonical_locale", canonical)
        object.__setattr__(self, "catalog_names", catalogs)
        object.__setattr__(self, "locales", MappingProxyType(locale_map))

    def locale(self, code: object) -> LocaleDescriptor:
        return self.locales.get(str(code), self.locales[self.canonical_locale])


class CatalogRepository(Protocol):
    """Storage boundary used by runtime localization catalog consumers."""

    def read(self, locale_code: str, catalog_name: str) -> dict[str, str]: ...


CatalogRootResolver = Callable[[str], Path]


class JsonCatalogRepository:
    """Read deterministic JSON locale catalogs from an injected root resolver."""

    def __init__(
        self,
        root_resolver: CatalogRootResolver,
        *,
        allowed_catalogs: tuple[str, ...] | None = None,
    ) -> None:
        self._root_resolver = root_resolver
        self._allowed_catalogs = tuple(allowed_catalogs or ())

    def catalog_path(self, locale_code: str, catalog_name: str) -> Path:
        locale = str(locale_code).strip()
        catalog = str(catalog_name).strip()
        if not locale:
            raise ValueError("locale code cannot be empty")
        if not catalog:
            raise ValueError("catalog name cannot be empty")
        if self._allowed_catalogs and catalog not in self._allowed_catalogs:
            raise ValueError(f"unsupported catalog {catalog!r}")
        return Path(self._root_resolver(locale)) / f"{catalog}.json"

    def read(self, locale_code: str, catalog_name: str) -> dict[str, str]:
        path = self.catalog_path(locale_code, catalog_name)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        meta = raw.get("_meta", {})
        if meta and not isinstance(meta, dict):
            raise ValueError(f"{path} has invalid _meta")
        if isinstance(meta, dict):
            declared_locale = str(meta.get("locale") or "")
            declared_catalog = str(meta.get("catalog") or "")
            if declared_locale and declared_locale != str(locale_code):
                raise ValueError(
                    f"{path} declares locale {declared_locale!r}, expected {locale_code!r}"
                )
            if declared_catalog and declared_catalog != str(catalog_name):
                raise ValueError(
                    f"{path} declares catalog {declared_catalog!r}, expected {catalog_name!r}"
                )
        strings = raw.get("strings", raw)
        if not isinstance(strings, dict):
            raise ValueError(f"{path} does not contain a string mapping")
        out: dict[str, str] = {}
        for key, value in strings.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"{path} catalog entries must map strings to strings")
            out[key] = value
        return out
