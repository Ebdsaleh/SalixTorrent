"""Compatibility facade plus SalixTorrent's concrete documentation renderer."""

from app.framework.documentation import *  # noqa: F401,F403
from app.framework.documentation import __all__ as _framework_all
from .renderer import DocumentationRenderer

__all__ = [*_framework_all, "DocumentationRenderer"]
