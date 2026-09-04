"""Shared filesystem helpers for the maintained regression suite."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(*parts: str) -> Path:
    """Return a path rooted at the SalixTorrent repository checkout."""
    return PROJECT_ROOT.joinpath(*parts)
