"""Optional SalixORM/SQLite application-settings storage backend.

This adapter is imported lazily only when ``SALIX_T_SETTINGS_BACKEND=salixorm``
is selected.  The default SalixTorrent runtime therefore keeps its historical
JSON settings dependency and does not require SalixORM merely to start.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from .settings import AppSettingsStoreError

try:
    import salixorm
    from salixorm import (
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
except ImportError as exc:
    raise ImportError(
        "SalixORM is required for the SalixORM application-settings backend"
    ) from exc


MINIMUM_SALIXORM_VERSION = (0, 2, 0)
SETTINGS_KIND = "salix-application-settings"
SETTINGS_SCHEMA = 1
MIGRATION_REVISION = "application-settings-0001"
META_TABLE = "salix_application_settings_meta"
SETTINGS_TABLE = "salix_application_settings"
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
        "The SalixORM application-settings backend requires SalixORM v0.2.0 or newer; "
        f"found {getattr(salixorm, '__version__', 'unknown')!r}."
    )


class _SettingsMetaRow(Model):
    __table__ = META_TABLE

    id = Integer(primary_key=True)
    kind = Text(nullable=False)
    schema_version = Integer(nullable=False)


class _SettingRow(Model):
    __table__ = SETTINGS_TABLE

    id = Integer(primary_key=True, auto=True)
    setting_key = Text(nullable=False)
    value_json = Text(nullable=False)

    class Meta:
        unique_constraints = [
            Unique("setting_key", name="uq_salix_application_settings_key")
        ]


class _CreateApplicationSettingsSchema(Migration):
    revision = MIGRATION_REVISION
    parent = None

    def upgrade(self, op):
        builder = SchemaBuilder(SQLiteDialect())
        op.create_table(builder.model_to_table_schema(_SettingsMetaRow.__meta__))
        op.create_table(builder.model_to_table_schema(_SettingRow.__meta__))

    def downgrade(self, op):
        op.drop_table(SETTINGS_TABLE)
        op.drop_table(META_TABLE)


MIGRATION_REGISTRY = MigrationRegistry([_CreateApplicationSettingsSchema])


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
        raise ValueError("SalixORM application-settings target cannot be empty")
    if "://" not in raw:
        path = Path(raw).expanduser().resolve()
        return _sqlite_url_for_path(path), str(path), path

    config = DatabaseConfig.from_url(raw)
    if config.scheme != "sqlite":
        raise ValueError(
            "The current SalixORM application-settings adapter is intentionally SQLite-only."
        )
    if config.is_memory:
        raise ValueError(
            "Application settings require a file-backed SQLite database; in-memory "
            "databases cannot preserve settings between launches."
        )
    path = Path(config.database).expanduser().resolve()
    return raw, str(path), path


def _encode_value(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AppSettingsStoreError(
            f"Application setting value is not deterministically JSON-serializable: {exc}"
        ) from exc


def _decode_value(value: object, key: str) -> object:
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AppSettingsStoreError(
            f"Persisted application setting {key!r} contains invalid JSON"
        ) from exc


class SalixORMAppSettingsStore:
    """File-backed application-settings store implemented through SalixORM."""

    def __init__(self, target: str | os.PathLike[str]) -> None:
        try:
            self.database_url, self.path, self._database_path = _normalize_target(target)
        except (TypeError, ValueError) as exc:
            raise AppSettingsStoreError(str(exc)) from exc

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
        application_tables = {META_TABLE, SETTINGS_TABLE}
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
            raise AppSettingsStoreError(
                "application-settings migration ledger records an applied revision "
                "but the settings tables are missing"
            )

        if present_application != application_tables or not has_ledger:
            missing = set(application_tables - present_application)
            if not has_ledger:
                missing.add(MIGRATION_TABLE)
            raise AppSettingsStoreError(
                "application-settings database schema is incomplete; missing: "
                + ", ".join(sorted(missing))
            )

        row = db.execute(
            f"SELECT revision FROM {MIGRATION_TABLE} ORDER BY applied_at DESC LIMIT 1;"
        ).fetchone()
        revision = str(row[0]) if row else ""
        if revision != MIGRATION_REVISION:
            raise AppSettingsStoreError(
                f"application-settings database revision {revision!r} does not match "
                f"required {MIGRATION_REVISION!r}"
            )
        return "initialized"

    @staticmethod
    def _metadata_row(session: Session) -> _SettingsMetaRow | None:
        rows = session.query(_SettingsMetaRow).all()
        if len(rows) > 1:
            raise AppSettingsStoreError(
                "application-settings metadata contains multiple rows"
            )
        return rows[0] if rows else None

    @staticmethod
    def _validate_metadata(row: _SettingsMetaRow | None) -> None:
        if row is None:
            raise AppSettingsStoreError("application-settings metadata row is missing")
        if row.id != 1:
            raise AppSettingsStoreError(
                "application-settings metadata singleton id is invalid"
            )
        if row.kind != SETTINGS_KIND:
            raise AppSettingsStoreError("application-settings metadata kind is invalid")
        if row.schema_version != SETTINGS_SCHEMA:
            raise AppSettingsStoreError(
                "application-settings semantic schema is unsupported"
            )

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
                    rows = session.query(_SettingRow).all()
                    if meta is None:
                        if not rows:
                            return None
                        raise AppSettingsStoreError(
                            "application-settings metadata is missing while setting rows exist"
                        )
                    self._validate_metadata(meta)

                    settings: dict[str, object] = {}
                    for row in rows:
                        key = str(row.setting_key or "").strip()
                        if not key:
                            raise AppSettingsStoreError(
                                "application-settings database contains an empty key"
                            )
                        if key in settings:
                            raise AppSettingsStoreError(
                                f"application-settings database contains duplicate key {key!r}"
                            )
                        settings[key] = _decode_value(row.value_json, key)
                    return settings
        except AppSettingsStoreError:
            raise
        except Exception as exc:
            raise AppSettingsStoreError(
                f"Could not load SalixORM application settings from {self.path}: {exc}"
            ) from exc

    def save(self, settings: Mapping[str, object]) -> None:
        values = {str(key): value for key, value in dict(settings).items()}
        if any(not key for key in values):
            raise AppSettingsStoreError("Application settings cannot contain an empty key")

        encoded = {key: _encode_value(value) for key, value in values.items()}
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self._new_database() as db:
                self._ensure_schema(db)
                with Session(db) as session:
                    with session.transaction():
                        meta = self._metadata_row(session)
                        if meta is None:
                            session.add(
                                _SettingsMetaRow(
                                    id=1,
                                    kind=SETTINGS_KIND,
                                    schema_version=SETTINGS_SCHEMA,
                                )
                            )
                        else:
                            self._validate_metadata(meta)

                        existing = {
                            str(row.setting_key): row
                            for row in session.query(_SettingRow).all()
                        }
                        for key in sorted(existing.keys() - encoded.keys()):
                            session.delete(existing[key])

                        for key in sorted(encoded):
                            row = existing.get(key)
                            if row is None:
                                session.add(
                                    _SettingRow(
                                        setting_key=key,
                                        value_json=encoded[key],
                                    )
                                )
                            else:
                                row.value_json = encoded[key]

                integrity = db.integrity_check()
                if not integrity.ok:
                    raise AppSettingsStoreError(
                        "SalixORM application-settings save completed but SQLite integrity "
                        "validation failed: " + "; ".join(integrity.messages)
                    )
                foreign_keys = db.foreign_key_check()
                if not foreign_keys.ok:
                    raise AppSettingsStoreError(
                        "SalixORM application-settings save completed but SQLite foreign-key "
                        "validation failed"
                    )
        except AppSettingsStoreError:
            raise
        except Exception as exc:
            raise AppSettingsStoreError(
                f"Could not save SalixORM application settings to {self.path}: {exc}"
            ) from exc
