"""SalixTorrent adapter for the framework-neutral localization contracts."""

from __future__ import annotations

from pathlib import Path

from app.engine.runtime_paths import resource_path

from .framework import LocaleDescriptor, LocalizationProfile
from .locale_info import AUTO_LOCALE, CANONICAL_LOCALE, SUPPORTED_LOCALES
from .pseudo import PSEUDO_ENV, PSEUDO_LOCALE


CATALOG_NAMES = ("ui", "help", "glossary")


def _runtime_locale_descriptors() -> dict[str, LocaleDescriptor]:
    return {
        code: LocaleDescriptor(
            code=info.code,
            display_name=info.display_name,
            native_name=info.native_name,
            script=info.script,
            text_direction=info.text_direction,
            font_profile=info.font_profile,
            support_status=info.support_status,
        )
        for code, info in SUPPORTED_LOCALES.items()
    }


SALIXTORRENT_LOCALIZATION_PROFILE = LocalizationProfile(
    application_id="salixtorrent",
    canonical_locale=CANONICAL_LOCALE,
    auto_locale=AUTO_LOCALE,
    catalog_names=CATALOG_NAMES,
    locales=_runtime_locale_descriptors(),
    pseudo_locale=PSEUDO_LOCALE,
    pseudo_environment=PSEUDO_ENV,
)


def salixtorrent_catalog_root(locale_code: str) -> Path:
    return resource_path(Path("app") / "localization" / "locales" / str(locale_code))


def salixtorrent_content_path(name: str) -> Path:
    return resource_path(Path("app") / "localization" / "content" / str(name))
