"""Compatibility imports for the reusable framework property cascade.

New framework-facing code should import :mod:`app.framework.property_cascade`.
This module remains temporarily so established SalixTorrent imports keep
working during the physical extraction.
"""

from app.framework.property_cascade import *  # noqa: F401,F403
