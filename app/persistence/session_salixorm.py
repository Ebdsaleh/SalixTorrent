"""Optional SalixORM/SQLite transfer/session-state storage backend.

The adapter stores one coherent desktop transfer-queue snapshot per explicit
transaction.  Cached metainfo and payload data remain external files; the
database owns only application/session metadata required to reconstruct the
queue and user lifecycle intent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from .session_state import CURRENT_SESSION_STATE_VERSION, SessionStateStoreError

try:
    import salixorm
    from salixorm import (
        Database,
        DatabaseConfig,
        Float,
        Integer,
        Migration,
        MigrationManager,
        MigrationRegistry,
        Model,
        SchemaBuilder,
        Session,
        Text,
        Unique,
    )
    from salixorm.backends.sqlite.dialect import SQLiteDialect
except ImportError as exc:
    raise ImportError(
        "SalixORM is required for the SalixORM session-state backend"
    ) from exc


MINIMUM_SALIXORM_VERSION = (0, 2, 0)
SESSION_KIND = "salix-session-state"
SESSION_SCHEMA = 1
MIGRATION_REVISION = "session-state-0001"
META_TABLE = "salix_session_meta"
TORRENTS_TABLE = "salix_session_torrents"
MIGRATION_TABLE = "_salixorm_migrations"
_VALID_INTENTS = {"active", "paused", "stopped", "idle"}


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in str(value).split("."):
        number = "".join(ch for ch in token if ch.isdigit())
        if not number:
            break
        parts.append(int(number))
    return tuple(parts)


if _version_tuple(getattr(salixorm, "__version__", "0")) < MINIMUM_SALIXORM_VERSION:
    raise RuntimeError(
        "The SalixORM session-state backend requires SalixORM v0.2.0 or newer; "
        f"found {getattr(salixorm, '__version__', 'unknown')!r}."
    )


class _SessionMetaRow(Model):
    __table__ = META_TABLE

    id = Integer(primary_key=True)
    kind = Text(nullable=False)
    schema_version = Integer(nullable=False)
    snapshot_version = Integer(nullable=False)
    selected_info_hash = Text(nullable=False)


class _SessionTorrentRow(Model):
    __table__ = TORRENTS_TABLE

    id = Integer(primary_key=True, auto=True)
    info_hash = Text(nullable=False)
    queue_position = Integer(nullable=False)
    torrent_path = Text(nullable=False)
    cached_torrent_path = Text(nullable=False)
    max_peers = Integer(nullable=False)
    download_dir = Text(nullable=False)
    intent = Text(nullable=False)
    paused_from_state = Text(nullable=False)
    download_limit_value = Float(nullable=False)
    download_limit_unit = Text(nullable=False)
    upload_limit_value = Float(nullable=False)
    upload_limit_unit = Text(nullable=False)
    uploaded_bytes = Integer(nullable=False)
    seed_source_path = Text(nullable=False)
    protocol_policy = Text(nullable=False)
    file_priorities_json = Text(nullable=False)
    queue_priority = Text(nullable=False)

    class Meta:
        unique_constraints = [
            Unique("info_hash", name="uq_salix_session_info_hash"),
            Unique("queue_position", name="uq_salix_session_queue_position"),
        ]


class _CreateSessionStateSchema(Migration):
    revision = MIGRATION_REVISION
    parent = None

    def upgrade(self, op):
        builder = SchemaBuilder(SQLiteDialect())
        op.create_table(builder.model_to_table_schema(_SessionMetaRow.__meta__))
        op.create_table(builder.model_to_table_schema(_SessionTorrentRow.__meta__))

    def downgrade(self, op):
        op.drop_table(TORRENTS_TABLE)
        op.drop_table(META_TABLE)


MIGRATION_REGISTRY = MigrationRegistry([_CreateSessionStateSchema])


def _sqlite_url_for_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    posix = resolved.as_posix()
    if os.name == "nt" or (len(posix) >= 2 and posix[1] == ":"):
        return f"sqlite:///{posix}"
    return "sqlite:////" + posix.lstrip("/")


def _normalize_target(target: str | os.PathLike[str]) -> tuple[str, str, Path]:
    if isinstance(target, os.PathLike):
        path = Path(target).expanduser().resolve()
        return _sqlite_url_for_path(path), str(path), path

    raw = str(target or "").strip()
    if not raw:
        raise ValueError("SalixORM session-state target cannot be empty")
    if "://" not in raw:
        path = Path(raw).expanduser().resolve()
        return _sqlite_url_for_path(path), str(path), path

    config = DatabaseConfig.from_url(raw)
    if config.scheme != "sqlite":
        raise ValueError(
            "The current SalixORM session-state adapter is intentionally SQLite-only."
        )
    if config.is_memory:
        raise ValueError(
            "Session state requires a file-backed SQLite database; in-memory databases "
            "cannot preserve the transfer queue between launches."
        )
    path = Path(config.database).expanduser().resolve()
    return raw, str(path), path


def _string(value: object) -> str:
    return str(value or "")


def _int(value: object, *, minimum: int | None = None, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SessionStateStoreError(f"Session field {field!r} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise SessionStateStoreError(
            f"Session field {field!r} must be >= {minimum}"
        )
    return result


def _float(value: object, *, minimum: float | None = None, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SessionStateStoreError(f"Session field {field!r} must be numeric") from exc
    if minimum is not None and result < minimum:
        raise SessionStateStoreError(
            f"Session field {field!r} must be >= {minimum}"
        )
    return result


def _encode_priorities(value: object) -> str:
    if value is None:
        priorities: list[object] = []
    elif isinstance(value, list):
        priorities = list(value)
    else:
        raise SessionStateStoreError("Session file_priorities must be a list")
    try:
        return json.dumps(
            priorities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SessionStateStoreError(
            f"Session file_priorities are not deterministically JSON-serializable: {exc}"
        ) from exc


def _decode_priorities(value: object, info_hash: str) -> list:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise SessionStateStoreError(
            f"Persisted session file priorities for {info_hash!r} contain invalid JSON"
        ) from exc
    if not isinstance(decoded, list):
        raise SessionStateStoreError(
            f"Persisted session file priorities for {info_hash!r} are not a list"
        )
    return decoded


def _prepare_snapshot(snapshot: Mapping[str, object]) -> tuple[str, list[dict]]:
    data = dict(snapshot)
    if data.get("version") != CURRENT_SESSION_STATE_VERSION:
        raise SessionStateStoreError(
            "SalixORM session saves require the current session-state version"
        )
    raw_entries = data.get("torrents", [])
    if not isinstance(raw_entries, list):
        raise SessionStateStoreError("Session snapshot torrents must be a list")

    selected = _string(data.get("selected_info_hash")).strip()
    entries: list[dict] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise SessionStateStoreError("Every session torrent entry must be an object")
        info_hash = _string(raw.get("info_hash")).strip()
        if not info_hash:
            raise SessionStateStoreError("Session torrent entry is missing info_hash")
        if info_hash in seen:
            raise SessionStateStoreError(
                f"Session snapshot contains duplicate info_hash {info_hash!r}"
            )
        seen.add(info_hash)

        intent = _string(raw.get("intent")).strip().lower()
        if intent not in _VALID_INTENTS:
            raise SessionStateStoreError(
                f"Session torrent {info_hash!r} has invalid intent {intent!r}"
            )

        entries.append(
            {
                "info_hash": info_hash,
                "queue_position": position,
                "torrent_path": _string(raw.get("torrent_path")),
                "cached_torrent_path": _string(raw.get("cached_torrent_path")),
                "max_peers": _int(raw.get("max_peers", 25), minimum=1, field="max_peers"),
                "download_dir": _string(raw.get("download_dir")),
                "intent": intent,
                "paused_from_state": _string(raw.get("paused_from_state")),
                "download_limit_value": _float(
                    raw.get("download_limit_value", 0.0),
                    minimum=0.0,
                    field="download_limit_value",
                ),
                "download_limit_unit": _string(raw.get("download_limit_unit") or "KB/s"),
                "upload_limit_value": _float(
                    raw.get("upload_limit_value", 0.0),
                    minimum=0.0,
                    field="upload_limit_value",
                ),
                "upload_limit_unit": _string(raw.get("upload_limit_unit") or "KB/s"),
                "uploaded_bytes": _int(
                    raw.get("uploaded_bytes", 0), minimum=0, field="uploaded_bytes"
                ),
                "seed_source_path": _string(raw.get("seed_source_path")),
                "protocol_policy": _string(raw.get("protocol_policy")),
                "file_priorities_json": _encode_priorities(raw.get("file_priorities", [])),
                "queue_priority": _string(raw.get("queue_priority")),
            }
        )

    if selected and selected not in seen:
        raise SessionStateStoreError(
            "Session selected_info_hash does not refer to a persisted torrent"
        )
    return selected, entries


class SalixORMSessionStateStore:
    """File-backed transfer/session store implemented through SalixORM."""

    def __init__(self, target: str | os.PathLike[str]) -> None:
        try:
            self.database_url, self.path, self._database_path = _normalize_target(target)
        except (TypeError, ValueError) as exc:
            raise SessionStateStoreError(str(exc)) from exc

    @property
    def backend(self) -> str:
        return "salixorm"

    @property
    def location(self) -> str:
        return self.path

    def _new_database(self) -> Database:
        return Database(
            self.database_url,
            options={"foreign_keys": True, "busy_timeout_ms": 5000},
        )

    @staticmethod
    def _table_names(db: Database) -> set[str]:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        return {str(row[0]) for row in rows}

    def _schema_state(self, db: Database) -> str:
        names = self._table_names(db)
        application_tables = {META_TABLE, TORRENTS_TABLE}
        present_application = names & application_tables
        has_ledger = MIGRATION_TABLE in names

        if not present_application:
            if not has_ledger:
                return "empty"
            row = db.execute(
                f"SELECT revision FROM {MIGRATION_TABLE} ORDER BY applied_at DESC LIMIT 1;"
            ).fetchone()
            if row is None:
                return "ledger_only"
            raise SessionStateStoreError(
                "session-state migration ledger records an applied revision but the "
                "session tables are missing"
            )

        if present_application != application_tables or not has_ledger:
            missing = set(application_tables - present_application)
            if not has_ledger:
                missing.add(MIGRATION_TABLE)
            raise SessionStateStoreError(
                "session-state database schema is incomplete; missing: "
                + ", ".join(sorted(missing))
            )

        row = db.execute(
            f"SELECT revision FROM {MIGRATION_TABLE} ORDER BY applied_at DESC LIMIT 1;"
        ).fetchone()
        revision = str(row[0]) if row else ""
        if revision != MIGRATION_REVISION:
            raise SessionStateStoreError(
                f"session-state database revision {revision!r} does not match required "
                f"{MIGRATION_REVISION!r}"
            )
        return "initialized"

    @staticmethod
    def _metadata_row(session: Session) -> _SessionMetaRow | None:
        rows = session.query(_SessionMetaRow).all()
        if len(rows) > 1:
            raise SessionStateStoreError("session-state metadata contains multiple rows")
        return rows[0] if rows else None

    @staticmethod
    def _validate_metadata(row: _SessionMetaRow | None) -> None:
        if row is None:
            raise SessionStateStoreError("session-state metadata row is missing")
        if row.id != 1:
            raise SessionStateStoreError("session-state metadata singleton id is invalid")
        if row.kind != SESSION_KIND:
            raise SessionStateStoreError("session-state metadata kind is invalid")
        if row.schema_version != SESSION_SCHEMA:
            raise SessionStateStoreError("session-state semantic schema is unsupported")
        if row.snapshot_version != CURRENT_SESSION_STATE_VERSION:
            raise SessionStateStoreError("session-state snapshot version is unsupported")

    def _ensure_schema(self, db: Database) -> None:
        state = self._schema_state(db)
        manager = MigrationManager(db)
        if state in {"empty", "ledger_only"}:
            manager.upgrade_to(MIGRATION_REGISTRY, MIGRATION_REVISION)
        else:
            manager.validate_history(MIGRATION_REGISTRY)
            manager.require_schema(MIGRATION_REVISION, registry=MIGRATION_REGISTRY)

    def load(self) -> dict | None:
        if not self._database_path.is_file():
            return None

        try:
            with self._new_database() as db:
                state = self._schema_state(db)
                if state in {"empty", "ledger_only"}:
                    return None

                with Session(db) as session:
                    meta = self._metadata_row(session)
                    rows = session.query(_SessionTorrentRow).all()
                    if meta is None:
                        if not rows:
                            return None
                        raise SessionStateStoreError(
                            "session-state metadata is missing while torrent rows exist"
                        )
                    self._validate_metadata(meta)

                    positions: set[int] = set()
                    info_hashes: set[str] = set()
                    entries: list[tuple[int, dict]] = []
                    for row in rows:
                        info_hash = _string(row.info_hash).strip()
                        if not info_hash:
                            raise SessionStateStoreError(
                                "session-state database contains an empty info_hash"
                            )
                        position = _int(
                            row.queue_position, minimum=0, field="queue_position"
                        )
                        if info_hash in info_hashes:
                            raise SessionStateStoreError(
                                f"session-state database contains duplicate info_hash {info_hash!r}"
                            )
                        if position in positions:
                            raise SessionStateStoreError(
                                f"session-state database contains duplicate queue position {position}"
                            )
                        info_hashes.add(info_hash)
                        positions.add(position)
                        intent = _string(row.intent).strip().lower()
                        if intent not in _VALID_INTENTS:
                            raise SessionStateStoreError(
                                f"session torrent {info_hash!r} has invalid intent {intent!r}"
                            )
                        entries.append(
                            (
                                position,
                                {
                                    "info_hash": info_hash,
                                    "torrent_path": _string(row.torrent_path),
                                    "cached_torrent_path": _string(row.cached_torrent_path),
                                    "max_peers": _int(
                                        row.max_peers, minimum=1, field="max_peers"
                                    ),
                                    "download_dir": _string(row.download_dir),
                                    "intent": intent,
                                    "paused_from_state": _string(row.paused_from_state) or None,
                                    "download_limit_value": _float(
                                        row.download_limit_value,
                                        minimum=0.0,
                                        field="download_limit_value",
                                    ),
                                    "download_limit_unit": _string(row.download_limit_unit),
                                    "upload_limit_value": _float(
                                        row.upload_limit_value,
                                        minimum=0.0,
                                        field="upload_limit_value",
                                    ),
                                    "upload_limit_unit": _string(row.upload_limit_unit),
                                    "uploaded_bytes": _int(
                                        row.uploaded_bytes,
                                        minimum=0,
                                        field="uploaded_bytes",
                                    ),
                                    "seed_source_path": _string(row.seed_source_path),
                                    "protocol_policy": _string(row.protocol_policy),
                                    "file_priorities": _decode_priorities(
                                        row.file_priorities_json, info_hash
                                    ),
                                    "queue_priority": _string(row.queue_priority),
                                },
                            )
                        )

                    expected_positions = set(range(len(entries)))
                    if positions != expected_positions:
                        raise SessionStateStoreError(
                            "session-state queue positions are not contiguous"
                        )
                    entries.sort(key=lambda item: item[0])
                    selected = _string(meta.selected_info_hash).strip()
                    if selected and selected not in info_hashes:
                        raise SessionStateStoreError(
                            "session-state selected_info_hash does not refer to a stored torrent"
                        )
                    return {
                        "version": CURRENT_SESSION_STATE_VERSION,
                        "selected_info_hash": selected,
                        "torrents": [entry for _, entry in entries],
                    }
        except SessionStateStoreError:
            raise
        except Exception as exc:
            raise SessionStateStoreError(
                f"Could not load SalixORM session state from {self.path}: {exc}"
            ) from exc

    def save(self, snapshot: Mapping[str, object]) -> None:
        selected, entries = _prepare_snapshot(snapshot)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self._new_database() as db:
                self._ensure_schema(db)
                with Session(db) as session:
                    with session.transaction():
                        meta = self._metadata_row(session)
                        if meta is None:
                            session.add(
                                _SessionMetaRow(
                                    id=1,
                                    kind=SESSION_KIND,
                                    schema_version=SESSION_SCHEMA,
                                    snapshot_version=CURRENT_SESSION_STATE_VERSION,
                                    selected_info_hash=selected,
                                )
                            )
                        else:
                            self._validate_metadata(meta)
                            meta.snapshot_version = CURRENT_SESSION_STATE_VERSION
                            meta.selected_info_hash = selected

                        for row in session.query(_SessionTorrentRow).all():
                            session.delete(row)
                        # Force old rows out before inserting the replacement snapshot.
                        # Queue positions are unique by design; without this flush, a UOW
                        # may attempt an INSERT before the corresponding DELETE and hit a
                        # transient uniqueness conflict inside an otherwise valid snapshot.
                        session.flush()

                        for entry in entries:
                            session.add(_SessionTorrentRow(**entry))

                integrity = db.integrity_check()
                if not integrity.ok:
                    raise SessionStateStoreError(
                        "SalixORM session-state save completed but SQLite integrity validation "
                        "failed: " + "; ".join(integrity.messages)
                    )
                foreign_keys = db.foreign_key_check()
                if not foreign_keys.ok:
                    raise SessionStateStoreError(
                        "SalixORM session-state save completed but SQLite foreign-key "
                        "validation failed"
                    )
        except SessionStateStoreError:
            raise
        except Exception as exc:
            raise SessionStateStoreError(
                f"Could not save SalixORM session state to {self.path}: {exc}"
            ) from exc
