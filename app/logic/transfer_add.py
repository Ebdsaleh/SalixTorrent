"""Shared transfer-add request types for GUI, CLI, and future integrations.

The torrent engine should not care which presentation layer supplied an input.
This module provides a small, Dear-PyGui-free contract for adding either a
.torrent metainfo file or a BitTorrent magnet URI through one manager API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.logic.session import TorrentSession


class TransferSourceKind(str, Enum):
    TORRENT = "torrent"
    MAGNET = "magnet"


TORRENT_PROTOCOL_AUTO = "Auto / Best Compatible"
TORRENT_PROTOCOL_V1_ONLY = "BitTorrent v1 Only"
TORRENT_PROTOCOL_V2_ONLY = "BitTorrent v2 Only"
TORRENT_PROTOCOL_POLICIES = (
    TORRENT_PROTOCOL_AUTO,
    TORRENT_PROTOCOL_V1_ONLY,
    TORRENT_PROTOCOL_V2_ONLY,
)


def normalise_torrent_protocol_policy(value: object) -> str:
    """Return one stable presentation-neutral torrent generation policy."""
    text = str(value or TORRENT_PROTOCOL_AUTO).strip()
    aliases = {
        "auto": TORRENT_PROTOCOL_AUTO,
        "best": TORRENT_PROTOCOL_AUTO,
        "best compatible": TORRENT_PROTOCOL_AUTO,
        "auto / best compatible": TORRENT_PROTOCOL_AUTO,
        "v1": TORRENT_PROTOCOL_V1_ONLY,
        "v1 only": TORRENT_PROTOCOL_V1_ONLY,
        "bittorrent v1 only": TORRENT_PROTOCOL_V1_ONLY,
        "v2": TORRENT_PROTOCOL_V2_ONLY,
        "v2 only": TORRENT_PROTOCOL_V2_ONLY,
        "bittorrent v2 only": TORRENT_PROTOCOL_V2_ONLY,
    }
    return aliases.get(
        text.lower(),
        text if text in TORRENT_PROTOCOL_POLICIES else TORRENT_PROTOCOL_AUTO,
    )


def classify_transfer_source(source: object) -> TransferSourceKind:
    value = str(source or "").strip()
    if not value:
        raise ValueError("A .torrent path or magnet URI is required.")
    if value.lower().startswith("magnet:?"):
        return TransferSourceKind.MAGNET
    return TransferSourceKind.TORRENT


@dataclass(frozen=True)
class TransferAddRequest:
    """Presentation-neutral request to add one transfer to SalixTorrent."""

    source: str
    start: bool = True
    persist: bool = True
    max_peers: Optional[int] = None
    download_dir: Optional[str] = None
    protocol_policy: Optional[str] = None

    @property
    def kind(self) -> TransferSourceKind:
        return classify_transfer_source(self.source)

    @property
    def normalized_source(self) -> str:
        value = str(self.source or "").strip()
        if not value:
            raise ValueError("A .torrent path or magnet URI is required.")
        return value


@dataclass(frozen=True)
class TransferAddHandle:
    """Immediate result of submitting a transfer-add request.

    Magnet metadata resolution is asynchronous, so ``session`` is initially
    ``None`` for magnets.  ``info_hash`` is still available immediately and is
    used to correlate MAGNET_* and TRANSFER_STATS engine events.
    """

    kind: TransferSourceKind
    source: str
    info_hash: str
    session: Optional["TorrentSession"] = None


