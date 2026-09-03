# SalixTorrent Application Persistence Design

**Status:** application-settings storage pilot
**Current application version string:** `0.3.0`
**Storage policy:** preserve purpose-built file formats where they are already the right abstraction; introduce SalixORM only behind bounded application-state contracts that benefit from transactional/schema-managed persistence.

---

## 1. Purpose

SalixTorrent already persists several very different kinds of data. They should not all be moved into one database merely because a database is available.

This document classifies the current persistence surfaces and records the first runtime-facing SalixORM integration boundary after the localization translation-memory integration.

The selection criteria are:

- user-facing durability;
- modest write frequency;
- clear ownership and lifecycle;
- schema/version evolution value;
- benefit from transactional persistence and integrity checks;
- straightforward migration from the existing format;
- no dependency on the peer/block/network hot path;
- no protocol/interoperability requirement to keep a particular external format.

---

## 2. Persistence inventory

| Persistence surface | Current representation | Classification | Decision |
| --- | --- | --- | --- |
| Application preferences | per-user `settings.json` | structured low-frequency application state | **Selected SalixORM candidate** |
| Desktop/window geometry | no separate persisted layout file currently | no independent persistence surface | no action |
| Transfer/session queue | per-user `session.json` | structured application/session metadata with more lifecycle coupling | good later candidate; keep JSON during settings pilot |
| Fast-resume verification | per-torrent `.salix_resume/<info_hash>.json` | payload-coupled, write-sensitive verification state | keep purpose-built sidecar |
| Cached metainfo | per-user `torrents/<info_hash>.torrent` | standard BitTorrent artifact | keep file-based |
| Magnet shell-handler backup | `shell_integration_backup.json` | tiny Windows-specific recovery artifact | keep file-based |
| UI exception history | `ui_errors.log` | append-only diagnostic log | keep log file |
| Download payload | files/directories beneath the transfer storage path | user payload | never ORM state |
| Created `.torrent` files | bencoded external artifacts | interoperability/export artifact | keep file-based |
| Localization catalogs/manifests/cache/review bundles | deterministic JSON development resources | generated/source-review tooling | keep deterministic files |
| Translation memory | deterministic JSON reference + optional SalixORM/SQLite development backend | reusable development data | existing backend-neutral integration; unchanged |

The fast-resume sidecar is deliberately **not** selected for ORM migration. It is tightly coupled to payload fingerprints, persisted-piece bitfields, recheck behavior and crash-sensitive disk lifecycle. Its compact local sidecar model remains appropriate.

---

## 3. Selected first runtime boundary: application settings

Application preferences are the lowest-risk next state boundary because they are:

- small and structured;
- written only when preferences change;
- already normalized through one `TorrentManager` settings contract;
- independent of peer/block/network timing;
- directly user-facing and worth recovering safely;
- easy to bootstrap from the existing `settings.json` representation.

The settings persistence contract lives under:

```text
app/persistence/
```

with:

```text
settings.py
settings_factory.py
settings_salixorm.py
```

`TorrentManager` depends on the generic settings store rather than on JSON or SalixORM directly.

---

## 4. Backward-compatible backend policy

JSON remains the default runtime backend:

```text
SALIX_T_SETTINGS_BACKEND=json
```

No SalixORM import occurs on the default path.

The optional SalixORM pilot is selected explicitly:

```text
SALIX_T_SETTINGS_BACKEND=salixorm
```

The default SQLite path is:

```text
<SalixTorrent state directory>/settings.db
```

A custom path or SQLite URL may be supplied with:

```text
SALIX_T_SETTINGS_URL=...
```

The SalixORM adapter currently accepts only file-backed SQLite. In-memory or non-SQLite database URLs are rejected explicitly.

SalixORM remains an optional dependency for this pilot. Source/development checkouts can install the sibling released ORM with:

```bat
python -m pip install -e ..\SalixORM
```

The optional module is loaded dynamically only after explicit backend selection. Merely having SalixORM installed in a development environment therefore does not make it an accidental frozen-build dependency. Normal packaged/runtime behavior remains JSON-backed until a deliberate packaging decision is made.

---

## 5. Existing-settings bootstrap behavior

When the SalixORM backend is selected and `settings.db` does not yet contain settings:

1. the primary SalixORM store is checked first;
2. the existing `settings.json` is consulted as a read-only bootstrap source;
3. `TorrentManager` applies its existing normalization rules;
4. the next settings save writes the complete normalized snapshot to SalixORM;
5. after that, the SalixORM database is authoritative for that selected backend.

The legacy JSON file is not deleted or dual-written. This avoids making one settings operation depend on two independent durable commits.

Switching back to the JSON backend explicitly returns to the JSON snapshot. Backend selection is therefore a deliberate development/integration choice rather than an automatic one-way migration at this stage.

---

## 6. SalixORM physical schema

The pilot owns a dedicated settings database and migration history.

Semantic metadata:

```text
kind:           salix-application-settings
schema_version: 1
```

Physical migration revision:

```text
application-settings-0001
```

Tables:

```text
salix_application_settings_meta
salix_application_settings
_salixorm_migrations
```

Settings are stored as unique keys with deterministic JSON-encoded scalar values. SalixTorrent's existing normalization remains the application-level type/range authority.

Every complete settings save is performed inside one explicit SalixORM `Session` transaction. Keys removed from the normalized snapshot are removed from the database in the same transaction.

After a successful commit the adapter runs SQLite integrity and foreign-key checks through SalixORM.

---

## 7. Failure policy

The default JSON backend preserves the historical behavior of falling back to application defaults when `settings.json` is missing or malformed.

The explicitly selected SalixORM backend is stricter:

- unsupported migration revisions fail closed;
- incomplete physical schema fails closed;
- invalid semantic metadata fails closed;
- setting rows without metadata fail closed;
- malformed persisted JSON values fail closed;
- a failed SalixORM load marks the active settings store unhealthy;
- an unhealthy store is not overwritten by later settings saves during that process.

The application may continue using normalized defaults so the UI can remain operable, but the corrupt/incompatible database is preserved for diagnosis/recovery rather than silently replaced.

---

## 8. Session state remains separate for now

`session.json` is intentionally unchanged in this tranche.

It carries more domain-specific state:

- queue order;
- selected transfer;
- persistent lifecycle intent;
- per-torrent limits and priorities;
- uploaded totals;
- source/cached metainfo paths;
- file priorities;
- protocol policy.

It is still a strong future SalixORM candidate, but moving it safely requires a separate design pass covering snapshot atomicity, queue ordering, manager-thread synchronization, restore compatibility and interaction with cached `.torrent` artifacts.

The settings pilot should gain Windows/source mileage before session persistence is migrated.

---

## 9. Invariants

1. JSON remains the default application-settings backend during the pilot.
2. Normal runtime startup does not import or require SalixORM.
3. Settings normalization remains owned by `TorrentManager`, not the database adapter.
4. One settings save is one durable transaction in the SalixORM backend.
5. Existing `settings.json` can bootstrap the opt-in SalixORM backend without being deleted.
6. Corrupt/incompatible SalixORM settings state is not silently overwritten.
7. `session.json` and fast-resume sidecars remain unchanged in this tranche.
8. Fast-resume and peer/block/network hot-path state stays purpose-built unless later evidence justifies a different design.
9. External `.torrent` artifacts and payload files remain file-based.
10. Any SalixORM correctness defect discovered here must be fixed at the ORM abstraction with regression coverage rather than hidden in application workarounds.

---

## 10. Validation checkpoint

The application-settings persistence regression set covers:

- historical JSON save/load behavior;
- lazy default runtime with no SalixORM import;
- SalixORM save/reopen parity;
- deterministic replacement/removal of settings keys;
- file-backed SQLite-only policy;
- semantic metadata corruption refusal;
- JSON bootstrap followed by SalixORM persistence;
- default `TorrentManager` JSON compatibility;
- opt-in `TorrentManager` SalixORM persistence/reopen;
- custom SQLite target selection;
- refusal to overwrite an unhealthy SalixORM settings store.

The exported source snapshot still omits `packaging/SalixTorrent.spec`; packaging-only failures from that omission are not application-persistence regressions and must be verified on the real Windows checkout.
