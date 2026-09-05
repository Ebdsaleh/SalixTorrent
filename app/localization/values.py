"""Presentation-only translations for stable internal enum/state values.

The torrent engine keeps canonical English protocol/state tokens so persistence,
networking and comparisons never depend on the selected UI language.  Views use
these helpers only when rendering those values or when mapping a localized combo
selection back to its canonical value.
"""

from __future__ import annotations

import re
from typing import Iterable

from .manager import localization_manager


COMMON_VALUE_SOURCES = {
    "All": "All",
    "Active": "Active",
    "Auto": "Auto",
    "Available": "Available",
    "Unavailable": "Unavailable",
    "Supported": "Supported",
    "Unsupported": "Unsupported",
    "Running": "Running",
    "Enabled": "Enabled",
    "Disabled": "Disabled",
    "Yes": "Yes",
    "No": "No",
    "None": "None",
    "Registered": "Registered",
    "Not registered": "Not registered",
    "Idle": "Idle",
    "Waiting": "Waiting",
    "Starting": "Starting",
    "Checking": "Checking",
    "Fast Resume": "Fast Resume",
    "Queued": "Queued",
    "Downloading": "Downloading",
    "Seeding": "Seeding",
    "Seed Indefinitely": "Seed Indefinitely",
    "Stop at Ratio": "Stop at Ratio",
    "Stop after Time": "Stop after Time",
    "Stop at Ratio or Time": "Stop at Ratio or Time",
    "Paused": "Paused",
    "Stopped": "Stopped",
    "Completed": "Completed",
    "Error": "Error",
    "Failed": "Failed",
    "Mapped": "Mapped",
    "Unmapped": "Unmapped",
    "IPv6 Direct": "IPv6 Direct",
    "High": "High",
    "Normal": "Normal",
    "Low": "Low",
    "Don't Download": "Don't Download",
    "Verified": "Verified",
    "Requested": "Requested",
    "Mixed": "Mixed",
    "Missing": "Missing",
    "No known source": "No known source",
    "No Peers": "No Peers",
    "Timeout": "Timeout",
    "Cancelled": "Cancelled",
    "Tracker": "Tracker",
    "LAN": "LAN",
    "Plaintext": "Plaintext",
    "Incoming": "Incoming",
    "Outgoing": "Outgoing",
    "Prefer Encryption": "Prefer Encryption",
    "Require Encryption": "Require Encryption",
    "Disable Encryption": "Disable Encryption",
    "Auto / Best Compatible": "Auto / Best Compatible",
    "BitTorrent v1 Only": "BitTorrent v1 Only",
    "BitTorrent v2 Only": "BitTorrent v2 Only",
    "Hybrid v1/v2 (Recommended)": "Hybrid v1/v2 (Recommended)",
    "BitTorrent v1": "BitTorrent v1",
    "BitTorrent v2": "BitTorrent v2",
    "External Seed": "External Seed",
    "single-file": "single-file",
    "folder / multi-file": "folder / multi-file",
    "Standby": "Standby",
    "Healthy": "Healthy",
    "Hashing": "Hashing",
    "30 seconds": "30 seconds",
    "1 minute": "1 minute",
    "2 minutes": "2 minutes",
}


def _value_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_") or "value"
    return f"value.{slug}"


def tr_value(value: object) -> str:
    """Translate a known presentation value without changing its canonical token."""
    text = str(value or "")
    source = COMMON_VALUE_SOURCES.get(text)
    if source is None:
        return text
    return localization_manager().tr(_value_key(text), source)


def localized_choices(values: Iterable[str]) -> list[str]:
    return [tr_value(value) for value in values]


def canonical_choice(label: object, values: Iterable[str], default: str) -> str:
    """Map a localized combo label back to one canonical stored value."""
    rendered = str(label or "")
    choices = tuple(str(value) for value in values)
    if rendered in choices:
        return rendered
    for value in choices:
        if tr_value(value) == rendered:
            return value
    return default
