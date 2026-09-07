"""Headless presentation profile."""

from app.runtime.presentation import HEADLESS_PRESENTATION, PresentationBackend


def create_headless_backend() -> PresentationBackend:
    return HEADLESS_PRESENTATION
