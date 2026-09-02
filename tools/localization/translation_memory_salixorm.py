"""SalixORM-backed SQLite translation-memory storage adapter.

This module is development tooling, not runtime localization infrastructure. It keeps
SalixORM/SQLite dependencies outside the generic translation-memory contract and stages
entry mutations in memory until ``save()`` commits them atomically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

try:
    from .translation_memory import (
        DEFAULT_SOURCE_LOCALE,
        MEMORY_KIND,
        MEMORY_SCHEMA,
        MemoryAudit,
        MemoryEntry,
        MemoryStats,
        memory_identity,
        validate_memory_entry,
    )
except ImportError:  # direct script execution
    from translation_memory import (
        DEFAULT_SOURCE_LOCALE,
        MEMORY_KIND,
        MEMORY_SCHEMA,
        MemoryAudit,
        MemoryEntry,
        MemoryStats,
        memory_identity,
        validate_memory_entry,
    )

try:
    from .contracts import source_hash
except ImportError:
    from contracts import source_hash

try:
    import salixorm
    from salixorm import (
        Boolean,
        Database,
        DatabaseConfig,
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
except ImportError as exc:  # surfaced by the factory with a user-facing message
    raise ImportError("SalixORM is required for the SalixORM translation-memory backend") from exc


MINIMUM_SALIXORM_VERSION = (0, 2, 0)
MIGRATION_REVISION = "translation-memory-0001"
META_TABLE = "salix_translation_memory_meta"
ENTRY_TABLE = "salix_translation_memory_entries"
MIGRATION_TABLE = "_salixorm_migrations"


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
        "The SalixORM translation-memory backend requires SalixORM v0.2.0 or newer; "
        f"found {getattr(salixorm, '__version__', 'unknown')!r}."
    )


class _MemoryMetaRow(Model):
    __table__ = META_TABLE

    id = Integer(primary_key=True)
    kind = Text(nullable=False)
    schema_version = Integer(nullable=False)
    source_locale = Text(nullable=False)


class _MemoryEntryRow(Model):
    __table__ = ENTRY_TABLE

    id = Integer(primary_key=True, auto=True)
    target_locale = Text(nullable=False)
    catalog = Text(nullable=False)
    source_hash = Text(nullable=False)
    source = Text(nullable=False)
    translation = Text(nullable=False)
    status = Text(nullable=False)
    provider = Text(nullable=False)
    model = Text(nullable=False)
    placeholders_json = Text(nullable=False)
    reusable = Boolean(nullable=False)

    class Meta:
        unique_constraints = [
            Unique(
                "target_locale",
                "catalog",
                "source_hash",
                name="uq_salix_translation_memory_identity",
            )
        ]


class _CreateTranslationMemorySchema(Migration):
    revision = MIGRATION_REVISION
    parent = None

    def upgrade(self, op):
        builder = SchemaBuilder(SQLiteDialect())
        op.create_table(builder.model_to_table_schema(_MemoryMetaRow.__meta__))
        op.create_table(builder.model_to_table_schema(_MemoryEntryRow.__meta__))

    def downgrade(self, op):
        op.drop_table(ENTRY_TABLE)
        op.drop_table(META_TABLE)


MIGRATION_REGISTRY = MigrationRegistry([_CreateTranslationMemorySchema])


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
        raise ValueError("SalixORM translation-memory target cannot be empty")
    if "://" not in raw:
        path = Path(raw).expanduser().resolve()
        return _sqlite_url_for_path(path), str(path), path

    config = DatabaseConfig.from_url(raw)
    if config.scheme != "sqlite":
        raise ValueError(
            "The current SalixORM translation-memory adapter is intentionally SQLite-only."
        )
    if config.is_memory:
        raise ValueError(
            "The translation-memory adapter requires a file-backed SQLite database; "
            "in-memory databases cannot preserve development memory between operations."
        )
    path = Path(config.database).expanduser().resolve()
    return raw, str(path), path


def _row_to_entry(row: _MemoryEntryRow) -> MemoryEntry:
    try:
        raw_placeholders = json.loads(row.placeholders_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted placeholder metadata is not valid JSON") from exc
    if not isinstance(raw_placeholders, list) or not all(isinstance(item, str) for item in raw_placeholders):
        raise ValueError("persisted placeholder metadata is not a string list")
    entry = MemoryEntry(
        target_locale=row.target_locale,
        catalog=row.catalog,
        source=row.source,
        source_hash=row.source_hash,
        translation=row.translation,
        status=row.status,
        provider=row.provider,
        model=row.model,
        placeholders=tuple(sorted(raw_placeholders)),
        reusable=bool(row.reusable),
    )
    return validate_memory_entry(entry)


class SalixORMTranslationMemory:
    """File-backed SQLite translation memory implemented through SalixORM v0.2+."""

    def __init__(
        self,
        target: str | os.PathLike[str],
        *,
        source_locale: str = DEFAULT_SOURCE_LOCALE,
    ) -> None:
        self.source_locale = str(source_locale or "").strip()
        if not self.source_locale:
            raise ValueError("translation-memory source locale cannot be empty")
        self.database_url, self.path, self._database_path = _normalize_target(target)
        self._entries: dict[tuple[str, str, str], MemoryEntry] = {}
        self._dirty: dict[tuple[str, str, str], MemoryEntry] = {}
        if self._database_path.is_file():
            self._load_existing()

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
        application_tables = {META_TABLE, ENTRY_TABLE}
        present_application = names & application_tables
        has_ledger = MIGRATION_TABLE in names

        if not present_application:
            if not has_ledger:
                return "empty"
            # MigrationManager creates its ledger before applying the first
            # migration. A failed first migration may therefore leave an empty
            # ledger behind; that state is safe to retry. A ledger claiming an
            # applied revision while both application tables are absent is not.
            row = db.execute(
                f"SELECT revision FROM {MIGRATION_TABLE} ORDER BY applied_at DESC LIMIT 1;"
            ).fetchone()
            if row is None:
                return "ledger_only"
            raise ValueError(
                "translation-memory migration ledger records an applied revision "
                "but the application tables are missing"
            )

        if present_application != application_tables or not has_ledger:
            missing = set(application_tables - present_application)
            if not has_ledger:
                missing.add(MIGRATION_TABLE)
            raise ValueError(
                "translation-memory database schema is incomplete; missing: "
                + ", ".join(sorted(missing))
            )

        row = db.execute(
            f"SELECT revision FROM {MIGRATION_TABLE} ORDER BY applied_at DESC LIMIT 1;"
        ).fetchone()
        revision = str(row[0]) if row else ""
        if revision != MIGRATION_REVISION:
            raise ValueError(
                f"translation-memory database revision {revision!r} does not match "
                f"required {MIGRATION_REVISION!r}"
            )
        return "initialized"

    def _metadata_row(self, session: Session) -> _MemoryMetaRow | None:
        rows = session.query(_MemoryMetaRow).all()
        if len(rows) > 1:
            raise ValueError("translation-memory metadata contains multiple rows")
        return rows[0] if rows else None

    def _validate_metadata(self, row: _MemoryMetaRow | None) -> None:
        if row is None:
            raise ValueError("translation-memory metadata row is missing")
        if row.id != 1:
            raise ValueError("translation-memory metadata singleton id is invalid")
        if row.kind != MEMORY_KIND:
            raise ValueError("translation-memory kind is invalid")
        if row.schema_version != MEMORY_SCHEMA:
            raise ValueError("translation-memory schema is unsupported")
        if row.source_locale != self.source_locale:
            raise ValueError(
                f"translation-memory source locale {row.source_locale!r} does not match "
                f"requested {self.source_locale!r}"
            )

    def _load_existing(self) -> None:
        with self._new_database() as db:
            state = self._schema_state(db)
            if state in {"empty", "ledger_only"}:
                return
            with Session(db) as session:
                metadata = self._metadata_row(session)
                if metadata is None:
                    # The physical schema migration commits before the first
                    # semantic data transaction. If that first data transaction
                    # is interrupted, a schema-only database is recoverable as
                    # long as no entry rows escaped without metadata.
                    if session.query(_MemoryEntryRow).first() is None:
                        return
                    raise ValueError(
                        "translation-memory metadata row is missing while entry rows exist"
                    )
                self._validate_metadata(metadata)
                for row in session.query(_MemoryEntryRow).all():
                    entry = _row_to_entry(row)
                    identity = memory_identity(entry)
                    current = self._entries.get(identity)
                    if current is not None and current != entry:
                        raise ValueError(
                            "translation-memory database contains conflicting duplicate identities"
                        )
                    self._entries[identity] = entry

    def lookup(self, target_locale: str, catalog: str, source: str) -> MemoryEntry | None:
        identity = (str(target_locale), str(catalog), source_hash(source))
        entry = self._entries.get(identity)
        if entry is None or entry.source != source or not entry.reusable:
            return None
        try:
            return validate_memory_entry(entry)
        except ValueError:
            return None

    def put(self, entry: MemoryEntry) -> None:
        validate_memory_entry(entry)
        identity = memory_identity(entry)
        self._entries[identity] = entry
        self._dirty[identity] = entry

    def iter_entries(self) -> Iterator[MemoryEntry]:
        for identity in sorted(self._entries):
            yield validate_memory_entry(self._entries[identity])

    def stats(self) -> MemoryStats:
        entries = reusable = reviewed = machine = seeded = 0
        locales: set[str] = set()
        for entry in self.iter_entries():
            locales.add(entry.target_locale)
            entries += 1
            if entry.reusable:
                reusable += 1
            if entry.status in {"reviewed", "locked"}:
                reviewed += 1
            elif entry.status == "seeded-existing":
                seeded += 1
            elif entry.status:
                machine += 1
        return MemoryStats(
            path=self.path,
            source_locale=self.source_locale,
            target_locales=len(locales),
            entries=entries,
            reusable=reusable,
            reviewed=reviewed,
            machine=machine,
            seeded=seeded,
        )

    def audit(self) -> MemoryAudit:
        errors: list[str] = []
        for identity, entry in sorted(self._entries.items()):
            try:
                validate_memory_entry(entry)
            except ValueError as exc:
                errors.append(f"{'/'.join(identity)}: {exc}")

        if self._database_path.is_file():
            try:
                with self._new_database() as db:
                    state = self._schema_state(db)
                    if state == "initialized":
                        with Session(db) as session:
                            self._validate_metadata(self._metadata_row(session))
                        integrity = db.integrity_check()
                        if not integrity.ok:
                            errors.append(
                                "SQLite integrity check failed: " + "; ".join(integrity.messages)
                            )
                        foreign_keys = db.foreign_key_check()
                        if not foreign_keys.ok:
                            errors.append(
                                f"SQLite foreign-key check reported {len(foreign_keys.violations)} violation(s)"
                            )
            except Exception as exc:
                errors.append(str(exc))
        return MemoryAudit(tuple(errors))

    def _ensure_schema(self, db: Database) -> None:
        state = self._schema_state(db)
        manager = MigrationManager(db)
        if state in {"empty", "ledger_only"}:
            manager.upgrade_to(MIGRATION_REGISTRY, MIGRATION_REVISION)
        else:
            manager.validate_history(MIGRATION_REGISTRY)
            manager.require_schema(MIGRATION_REVISION, registry=MIGRATION_REGISTRY)

    def save(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._new_database() as db:
            self._ensure_schema(db)
            with Session(db) as session:
                with session.transaction():
                    meta = self._metadata_row(session)
                    if meta is None:
                        session.add(
                            _MemoryMetaRow(
                                id=1,
                                kind=MEMORY_KIND,
                                schema_version=MEMORY_SCHEMA,
                                source_locale=self.source_locale,
                            )
                        )
                    else:
                        self._validate_metadata(meta)

                    for identity in sorted(self._dirty):
                        entry = self._dirty[identity]
                        row = (
                            session.query(_MemoryEntryRow)
                            .where(
                                _MemoryEntryRow.target_locale == entry.target_locale,
                                _MemoryEntryRow.catalog == entry.catalog,
                                _MemoryEntryRow.source_hash == entry.source_hash,
                            )
                            .one_or_none()
                        )
                        placeholders_json = json.dumps(
                            list(entry.placeholders),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if row is None:
                            session.add(
                                _MemoryEntryRow(
                                    target_locale=entry.target_locale,
                                    catalog=entry.catalog,
                                    source_hash=entry.source_hash,
                                    source=entry.source,
                                    translation=entry.translation,
                                    status=entry.status,
                                    provider=entry.provider,
                                    model=entry.model,
                                    placeholders_json=placeholders_json,
                                    reusable=entry.reusable,
                                )
                            )
                        else:
                            row.source = entry.source
                            row.translation = entry.translation
                            row.status = entry.status
                            row.provider = entry.provider
                            row.model = entry.model
                            row.placeholders_json = placeholders_json
                            row.reusable = entry.reusable

            integrity = db.integrity_check()
            if not integrity.ok:
                raise RuntimeError(
                    "SalixORM translation-memory save completed but SQLite integrity validation failed: "
                    + "; ".join(integrity.messages)
                )
            foreign_keys = db.foreign_key_check()
            if not foreign_keys.ok:
                raise RuntimeError(
                    "SalixORM translation-memory save completed but SQLite foreign-key validation failed"
                )
        self._dirty.clear()
