# SalixTorrent Application Persistence Design

**Status:** settings boundary stable; session-state backend pilot implemented
**Current application version string:** `0.3.0`
**Storage policy:** preserve purpose-built file formats where they are the right abstraction; introduce SalixORM only behind bounded application-state contracts that benefit from transactional/schema-managed persistence.

---

## 1. Purpose

SalixTorrent persists several kinds of state with very different lifecycle and performance needs. They should not all be moved into one database merely because a database backend exists.

The persistence architecture therefore uses small application-owned storage contracts. JSON remains the default/reference behavior while optional SalixORM/SQLite adapters can be exercised without coupling torrent-engine hot paths to the ORM.

Selection criteria include:

- user-facing durability;
- modest write frequency;
- clear ownership and lifecycle;
- schema/version evolution value;
- benefit from transaction/integrity guarantees;
- straightforward compatibility from the existing representation;
- no peer/block/network hot-path requirement;
- no protocol/interoperability requirement to preserve an external file format.

---

## 2. Persistence inventory

| Persistence surface | Representation | Classification | Decision |
| --- | --- | --- | --- |
| Application preferences | `settings.json` / optional `settings.db` | low-frequency normalized application state | backend-neutral boundary implemented |
| Transfer/session queue | `session.json` / optional `session.db` | ordered application/session metadata | backend-neutral boundary implemented |
| Fast-resume verification | `.salix_resume/<info_hash>.json` | payload-coupled crash-sensitive verification state | keep purpose-built sidecar |
| Cached metainfo | `torrents/<info_hash>.torrent` | standard BitTorrent artifact | keep file-based |
| Magnet shell-handler backup | `shell_integration_backup.json` | tiny Windows recovery artifact | keep file-based |
| UI exception history | `ui_errors.log` | append-only diagnostic log | keep log file |
| Download payload | files/directories beneath transfer storage | user payload | never ORM state |
| Created `.torrent` files | bencoded external artifacts | interoperability/export artifact | keep file-based |
| Localization resources/cache/review | deterministic JSON development resources | generated/source-review tooling | keep deterministic files |
| Translation memory | deterministic JSON + optional SalixORM | reusable development data | existing backend-neutral integration |

The fast-resume sidecar remains deliberately outside SalixORM. It is tightly coupled to payload fingerprints, verified-piece bitfields, recheck behavior and write-sensitive disk lifecycle.

---

## 3. Application settings boundary

Files:

```text
app/persistence/settings.py
app/persistence/settings_factory.py
app/persistence/settings_salixorm.py
```

Boundary:

```text
TorrentManager
    -> AppSettingsStore
         -> JsonAppSettingsStore        default/reference
         -> SalixORMAppSettingsStore    explicit opt-in
```

Environment selection:

```text
SALIX_T_SETTINGS_BACKEND=json|salixorm
SALIX_T_SETTINGS_URL=...
```

Default SalixORM path:

```text
<state directory>/settings.db
```

Physical migration:

```text
application-settings-0001
```

Semantic metadata:

```text
kind: salix-application-settings
schema: 1
```

Settings normalization remains owned by `TorrentManager`. One SalixORM save persists the complete normalized snapshot in one transaction. Existing JSON can bootstrap an empty selected database, but the legacy file is not dual-written or deleted.

---

## 4. Session-state boundary

Files:

```text
app/persistence/session_state.py
app/persistence/session_factory.py
app/persistence/session_salixorm.py
```

Boundary:

```text
TorrentManager
    -> SessionStateStore
         -> JsonSessionStateStore        default/reference
         -> SalixORMSessionStateStore    explicit opt-in
```

Environment selection:

```text
SALIX_T_SESSION_BACKEND=json|salixorm
SALIX_T_SESSION_URL=...
```

Default SalixORM path:

```text
<state directory>/session.db
```

When session persistence is explicitly disabled (for example the headless CLI), the manager forces the JSON boundary and performs no load/save. This prevents an inherited desktop session-backend environment variable from importing an optional runtime dependency into a nonpersistent process.

---

## 5. Session snapshot ownership

Current normalized session state version:

```text
7
```

Historical JSON versions 1-6 remain accepted as import/restore inputs.

The current snapshot owns:

```text
selected_info_hash
ordered torrents[]
```

Each torrent entry owns:

```text
info_hash
torrent_path
cached_torrent_path
max_peers
download_dir
intent
paused_from_state
download_limit_value
download_limit_unit
upload_limit_value
upload_limit_unit
uploaded_bytes
seed_source_path
protocol_policy
file_priorities
queue_priority
```

List order is queue order in the JSON reference backend. The SalixORM adapter stores the same order explicitly through `queue_position`.

---

## 6. Single durable authority for active download slots

Historical session snapshots also contained:

```text
max_active_downloads
```

The same preference is already part of application settings. Maintaining two durable authorities allowed session restore to overwrite the settings value.

Session snapshot version 7 removes the duplicate field. Application settings are now the sole durable authority for `max_active_downloads`.

Historical JSON versions remain readable, but their legacy queue-limit field is ignored during restore. This is an intentional ownership correction rather than a data-loss fallback.

---

## 7. SalixORM session physical schema

Semantic metadata:

```text
kind:           salix-session-state
schema_version: 1
snapshot:       7
```

Physical migration revision:

```text
session-state-0001
```

Tables:

```text
salix_session_meta
salix_session_torrents
_salixorm_migrations
```

The metadata singleton stores selected transfer and snapshot identity. Torrent rows store queue order and all normalized per-transfer session metadata.

Unique constraints protect:

```text
info_hash
queue_position
```

On load, queue positions must be exactly contiguous `0..N-1`; duplicate/gapped order is treated as corrupt/incompatible durable state rather than guessed into a new order.

The desktop queue starts in unsorted queue-order presentation mode. A user may temporarily sort by a table column, but a restored session is first rendered in persisted scheduler order, and manual Move Up / Move Down returns the view to queue order immediately.

---

## 8. Whole-snapshot transaction semantics

Session persistence represents one coherent transfer queue at a point in time.

The SalixORM adapter therefore uses one explicit `Session` transaction to:

1. validate the complete new snapshot before modifying durable data;
2. validate/create semantic metadata;
3. remove the previous torrent rows;
4. flush those deletes while still inside the transaction;
5. insert the complete replacement queue with explicit positions;
6. update selected-transfer metadata;
7. commit the transaction;
8. run SQLite integrity and foreign-key checks.

The explicit flush between old-row deletion and replacement insertion avoids a transient uniqueness conflict on queue positions while preserving all-or-nothing transaction semantics.

A failed validation/save must leave the previous committed snapshot intact.

---

## 9. JSON -> SalixORM bootstrap

When the SalixORM session backend is selected and `session.db` has no session snapshot:

1. the primary database is checked first;
2. historical `session.json` is consulted as a read-only fallback;
3. `TorrentManager` restores the queue with existing compatibility behavior;
4. the next normal save writes a current version-7 snapshot to SalixORM;
5. the database becomes authoritative for that selected backend.

The legacy JSON file is not deleted or dual-written.

---

## 10. Failure policy

The default JSON session backend preserves historical tolerant behavior: missing/malformed/unsupported JSON is treated as no restorable session and a later valid save may replace it.

The explicitly selected SalixORM backend is stricter:

- unsupported migration revision fails closed;
- partial physical schema fails closed;
- invalid semantic metadata fails closed;
- torrent rows without metadata fail closed;
- unsupported snapshot version fails closed;
- invalid persisted file-priority JSON fails closed;
- invalid/duplicate torrent identity fails closed;
- duplicate or noncontiguous queue position fails closed;
- selected torrent referring to no persisted row fails closed.

A SalixORM load failure marks the active session store unhealthy. The manager remains operable, but subsequent normal queue/shutdown saves are refused so the damaged database is not silently replaced by an empty or partial queue.

---

## 11. Restore boundary remains application-owned

The storage adapter does not instantiate `TorrentSession` objects or validate external metainfo files.

`TorrentManager` still owns restore semantics:

- source-path then cached-metainfo path resolution;
- deterministic cache fallback by info hash;
- metainfo reparse;
- saved info-hash verification;
- queue/lifecycle reconstruction;
- paused-from state;
- transfer limits;
- uploaded totals;
- file priorities;
- queue priority;
- protocol policy;
- auto-resume policy;
- skipping unavailable torrents;
- post-restore state rewrite to remove dead entries.

Cached `.torrent` files stay external artifacts and are not stored as SQL blobs.

---

## 12. Invariants

1. JSON remains the default settings and session backend during the pilot.
2. Normal default runtime startup does not import or require SalixORM.
3. Headless/nonpersistent session use does not import or write an optional session backend.
4. Settings normalization remains owned by `TorrentManager`.
5. Application settings are the sole durable authority for `max_active_downloads`.
6. One SalixORM settings save is one complete settings transaction.
7. One SalixORM session save is one coherent queue snapshot transaction.
8. Existing `settings.json` and `session.json` can bootstrap empty opt-in databases without being deleted.
9. Corrupt/incompatible SalixORM state is not silently overwritten.
10. Fast-resume and peer/block/network hot-path state remains purpose-built.
11. External `.torrent` artifacts and payload files remain file-based.
12. Any genuine SalixORM correctness defect must be fixed in SalixORM with regression coverage rather than hidden in application workarounds.

---

## 13. Validation checkpoint

Session persistence regression coverage includes:

- current JSON round-trip/atomic replacement;
- JSON historical versions 1-6 import;
- malformed/unsupported JSON tolerance;
- current-version-only JSON saves;
- default runtime lazy dependency behavior;
- headless/nonpersistent isolation even with a SalixORM session environment selection;
- removal of duplicate `max_active_downloads` session authority;
- legacy session queue-limit refusal to override settings;
- SalixORM save/reopen/order parity;
- semantic metadata and migration revision;
- empty queue snapshots;
- file-backed SQLite-only policy;
- corrupt metadata refusal;
- noncontiguous queue refusal;
- failed-save preservation of the previous committed snapshot;
- JSON -> SalixORM bootstrap;
- manager backend/path selection;
- corrupt-store write refusal;
- custom database target;
- restore of real stopped-torrent metainfo/session metadata.

The source-export snapshot can still omit `packaging/SalixTorrent.spec`; packaging-only failures caused solely by that omission are not persistence regressions and must be validated on the real checkout.
