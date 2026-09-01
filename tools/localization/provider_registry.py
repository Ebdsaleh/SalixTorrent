"""Provider-neutral registry for development-time translation services.

Providers are development-only services. Runtime localization must never import
or depend on this registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class TranslationProvider(Protocol):
    provider_name: str
    model_name: str

    def translate_batch(self, texts: list[str], target_code: str) -> list[str]: ...


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    description: str
    network: bool
    development_only: bool = True


_FACTORIES: dict[str, Callable[..., TranslationProvider]] = {}
_DESCRIPTORS: dict[str, ProviderDescriptor] = {}


def register_provider(
    name: str,
    factory: Callable[..., TranslationProvider],
    *,
    description: str,
    network: bool,
) -> None:
    key = str(name).strip().lower()
    if not key:
        raise ValueError("provider name cannot be empty")
    _FACTORIES[key] = factory
    _DESCRIPTORS[key] = ProviderDescriptor(
        name=key,
        description=str(description),
        network=bool(network),
    )


def provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    _ensure_builtins()
    return tuple(_DESCRIPTORS[name] for name in sorted(_DESCRIPTORS))


def create_provider(name: str, **kwargs) -> TranslationProvider:
    _ensure_builtins()
    key = str(name or "").strip().lower()
    try:
        factory = _FACTORIES[key]
    except KeyError as exc:
        available = ", ".join(sorted(_FACTORIES)) or "(none)"
        raise ValueError(f"Unknown translation provider {name!r}; available: {available}") from exc
    return factory(**kwargs)


def _google_factory(**kwargs):
    # Lazy import keeps Google packages out of ordinary tooling/runtime paths.
    try:
        from .google_translate import GoogleTranslator
    except ImportError:
        from google_translate import GoogleTranslator
    return GoogleTranslator(**kwargs)


def _ensure_builtins() -> None:
    if "google-cloud" not in _FACTORIES:
        register_provider(
            "google-cloud",
            _google_factory,
            description="Google Cloud Translation v3 / Translation LLM",
            network=True,
        )
