# SalixTorrent Development Roadmap

**Current application version string:** `0.3.0`
**Roadmap status:** active development planning
**Current implementation checkpoint:** session-state persistence complete and validated
**Current real Windows regression baseline:** 299 / 299 tests passing, with one expected non-Windows skip

This roadmap records intended engineering direction rather than promising dates or release numbers. Changes should remain incremental, testable, reviewable, and compatible with SalixTorrent's existing protocol, persistence, packaging, localization, and cross-platform boundaries.

---

# 1. Current baseline

SalixTorrent already provides:

- BitTorrent v1, v2, and hybrid torrent support;
- btih/btmh magnet handling;
- v1/v2/hybrid torrent creation;
- HTTP/HTTPS and UDP trackers;
- DHT, PEX, and Local Peer Discovery;
- private-torrent discovery isolation;
- incoming peers, downloading, uploading, seeding, and external-source seeding;
- rarest-first piece selection;
- bounded adaptive request pipelines;
- bounded Endgame Mode and peer-wire CANCEL;
- asynchronous disk write-behind/backpressure and recent-piece caching;
- fast resume and force recheck;
- selective files and file priorities;
- queue order, queue priority, and active download slots;
- per-torrent and global bandwidth limits;
- MSE/PE peer encryption;
- IPv4/IPv6 networking;
- network-interface/VPN binding and Interface Lock;
- UPnP/NAT-PMP mapping and diagnostics;
- tracker scrape support;
- desktop GUI and shared headless CLI;
- Windows packaging/shell integration;
- cross-platform desktop/tray abstraction;
- responsive semantic Help/Glossary;
- offline-first localization;
- provider-neutral translation tooling;
- optional SalixORM translation-memory storage;
- backend-neutral application-settings persistence with optional SalixORM/SQLite storage;
- backend-neutral transfer/session persistence with optional SalixORM/SQLite storage.

Future work should extend these systems instead of replacing them without a concrete reason.

---

# 2. Session-state persistence milestone — complete

The transfer/session queue now uses:

```text
SessionStateStore
├── JsonSessionStateStore       default/reference
└── SalixORMSessionStateStore   explicit opt-in
```

Current normalized session version:

```text
7
```

Historical JSON versions `1-6` remain accepted as import/restore inputs.

SalixORM migration:

```text
session-state-0001
```

Semantic metadata:

```text
kind = salix-session-state
schema_version = 1
snapshot_version = 7
```

## Completed acceptance checklist

- [x] backend-neutral session storage boundary;
- [x] JSON remains default/reference;
- [x] SalixORM remains explicit/lazy;
- [x] historical JSON versions 1-6 remain readable;
- [x] version 7 removes duplicate `max_active_downloads` authority;
- [x] application settings are sole durable owner of active download slots;
- [x] queue order persistence;
- [x] selected torrent persistence;
- [x] active / paused / stopped lifecycle intent persistence;
- [x] paused-from state persistence;
- [x] source/cached metainfo path persistence;
- [x] download-directory persistence in normalized snapshots;
- [x] max-peer persistence;
- [x] per-torrent rate-limit persistence;
- [x] uploaded-total persistence;
- [x] seed-source persistence;
- [x] protocol-policy persistence;
- [x] file-priority persistence;
- [x] queue-priority persistence;
- [x] explicit contiguous SQL queue positions;
- [x] one coherent snapshot transaction;
- [x] failed-save preservation of the previous snapshot;
- [x] JSON -> SalixORM bootstrap;
- [x] corrupt semantic state fails closed;
- [x] headless/nonpersistent isolation;
- [x] manual Move Up/Down exits temporary column-sort mode immediately;
- [x] restored queues render in scheduler order on the first GUI frame;
- [x] real Windows two-torrent SalixORM exit/restart smoke;
- [x] 22/22 session persistence regression tests;
- [x] 299/299 full real Windows regression tests.

The real smoke restored `beta -> alpha`, `beta` High priority, both transfers Stopped, and `alpha` selected.

Fast-resume sidecars, cached `.torrent` artifacts, payload files, logs and protocol-hot-path telemetry remain outside this database boundary.

---

# 3. Immediate engineering priority — repository-owned unittest suite

The next change should be repository/test hygiene, not another product feature.

The current source contains:

```text
27 root test_*.py modules
+ foundation_test.py
```

The existing `.gitignore` intentionally excludes those regression tests from the public repository. That policy made sense during early rapid development, but the suite is now too important to live only in local snapshots.

The maintained regression suite should become:

- structured;
- version controlled;
- available in a fresh clone;
- reviewable alongside source changes;
- runnable with Python's standard library;
- removed from the repository root.

## Directory convention

Use the conventional plural directory:

```text
tests/
```

Keep Python's built-in:

```text
unittest
```

No pytest dependency is required.

## Proposed structure

```text
tests/
├── __init__.py
├── core/
│   ├── __init__.py
│   └── test_foundation.py
├── protocol/
│   ├── __init__.py
│   ├── test_piece_selection.py
│   ├── test_request_scheduling.py
│   ├── test_torrent_generation.py
│   ├── test_torrent_v2.py
│   ├── test_v2_peer_wire.py
│   └── test_magnet_metadata.py
├── network/
│   ├── __init__.py
│   ├── test_transport_security.py
│   ├── test_ipv6.py
│   └── test_tracker_scrape.py
├── persistence/
│   ├── __init__.py
│   ├── test_disk_io.py
│   ├── test_app_settings_persistence.py
│   └── test_session_state_persistence.py
├── platform/
│   ├── __init__.py
│   ├── test_runtime_paths.py
│   ├── test_shell_integration.py
│   └── test_desktop_integration.py
├── packaging/
│   ├── __init__.py
│   ├── test_release_packaging.py
│   └── test_localization_packaging.py
├── presentation/
│   ├── __init__.py
│   ├── test_responsive_layout.py
│   └── test_documentation.py
├── cli/
│   ├── __init__.py
│   └── test_headless_cli.py
└── localization/
    ├── __init__.py
    ├── test_locale_resolution.py
    ├── test_runtime_catalogs.py
    ├── test_localization_settings.py
    ├── test_localization_tooling.py
    ├── test_localization_ui.py
    ├── test_localization_semantic_documents.py
    ├── test_localization_extraction.py
    ├── test_localization_translation_pipeline.py
    ├── test_localization_locale_generation.py
    ├── test_localization_validation.py
    ├── test_localization_review.py
    ├── test_localization_translation_memory.py
    ├── test_localization_framework_boundaries.py
    ├── test_localization_runtime_services.py
    └── test_localization_salixorm_memory.py
```

## Naming rule

The final tracked suite should use **behavior-oriented names, not milestone numbers**.

Temporary source files such as `test_phase9.py` through `test_phase12.py` may be used while performing the migration, but they should not remain in the finished tree just to preserve history.

Preserve historical provenance inside the test module instead:

```python
"""Desktop integration regressions.

Regression lineage:
- originally introduced during the Phase 11 desktop-integration milestone
- source milestone commit: <resolved commit hash>
"""
```

Use the real commit hash from Git history when available; do not invent one.

Current mixed milestone files should be split by responsibility where useful:

```text
test_phase9.py
    -> test_torrent_generation.py
    -> test_v2_peer_wire.py
    -> test_magnet_metadata.py

test_phase10.py
    -> test_runtime_paths.py
    -> test_shell_integration.py
    -> test_release_packaging.py

test_phase11.py
    -> test_desktop_integration.py
    -> packaging assertions -> test_release_packaging.py

test_phase12.py
    -> test_locale_resolution.py
    -> test_runtime_catalogs.py
    -> test_localization_settings.py
    -> test_localization_tooling.py
    -> packaging assertions -> test_localization_packaging.py
```

Class names should also describe behavior (`TestLocaleResolution`, `TestDesktopIntegration`, `TestReleasePackaging`, etc.) rather than carrying `PhaseN` names.

## Migration checklist

- [ ] commit the completed session-state persistence checkpoint first;
- [ ] create the `tests/` package tree;
- [ ] move all maintained root regression modules;
- [ ] rename `foundation_test.py` -> `tests/core/test_foundation.py`;
- [ ] replace `test_phaseN.py` filenames and `PhaseN...Tests` classes with semantic behavior-oriented names;
- [ ] split mixed milestone files across logical modules where that improves ownership;
- [ ] preserve milestone/commit provenance in module docstrings or comments, not filenames;
- [ ] add `__init__.py` files for deterministic discovery;
- [ ] introduce shared test path/root helpers;
- [ ] replace assumptions that `Path(__file__).parent` is the repository root;
- [ ] add dedicated restore regressions for unavailable source/cache metainfo and saved-info-hash mismatch refusal;
- [ ] preserve subprocess working-directory expectations explicitly;
- [ ] update README test commands and project tree;
- [ ] remove maintained-test exclusions from `.gitignore`;
- [ ] keep only generated fixtures/output ignored;
- [ ] verify focused suites;
- [ ] verify full Windows discovery;
- [ ] account explicitly for every test-count change;
- [ ] commit the test-tree refactor separately from product features.

`foundation_test.py` currently contains four `unittest` tests but is not matched by normal `test*.py` discovery. Once renamed and included, the initial discoverable suite should therefore be **at least 303 tests** before any new migration-guard tests are added.

Canonical full command after migration:

```bat
python -m unittest discover -s tests -t .
```

Focused examples:

```bat
python -m unittest tests.persistence.test_session_state_persistence -v
python -m unittest tests.persistence.test_app_settings_persistence -v
python -m unittest tests.network.test_transport_security -v
python -m unittest discover -s tests\localization -t . -v
```

A plain repository-root:

```bat
python -m unittest discover
```

should remain useful if practical.

---

# 4. Optional CI follow-up

After the tracked `tests/` tree is stable locally:

- add a simple CI workflow as a separate change;
- run pure/headless tests on supported CI platforms;
- keep packaging/native-desktop gates explicit;
- do not treat CI as a replacement for real native Windows/Linux/BSD/macOS smoke testing.

Recommended order:

```text
A. move/structure tests
B. prove local Windows parity
C. commit
D. add CI separately
```

---

# 5. Application-settings pilot — collect more mileage

Current settings boundary:

```text
AppSettingsStore
├── JsonAppSettingsStore
└── SalixORMAppSettingsStore
```

JSON remains the normal runtime default.

Before promoting SalixORM into normal packaged runtime requirements/default behavior:

- exercise repeated source-run restarts;
- test frozen/portable behavior with SalixORM deliberately bundled;
- verify migration from a real existing `settings.json`;
- verify user-visible corrupt-DB refusal behavior;
- decide whether settings/session databases should ever be consolidated.

Do not merge databases merely for cosmetic uniformity.

---

# 6. User-facing transfer lifecycle features

After test-suite normalization, the next product-oriented track should build on durable session metadata.

## 6.1 Seeding goals and automatic stop policy

Candidate policies:

- seed indefinitely;
- stop at upload ratio;
- stop after a seeding duration;
- stop when either ratio or duration is reached;
- per-torrent override of application defaults.

Requirements:

- distinguish lifetime uploaded total from current-process telemetry;
- preserve manual stop/resume intent;
- persist policy across restart;
- expose remaining goal/status in General/Properties;
- keep policy evaluation outside persistence adapters.

This is the recommended first user-facing feature after test normalization.

## 6.2 Move / relocate downloaded data

Requirements:

- quiesce writes before movement;
- support same-volume rename and cross-volume copy;
- preserve multi-file relative layout;
- verify destination before deleting source;
- update persisted download root only after success;
- preserve or deliberately invalidate fast-resume trust;
- reject unsafe traversal/symlink escapes;
- provide explicit progress/error reporting.

Changing the default download directory must continue to affect new torrents only.

## 6.3 Labels / categories

Requirements:

- labels do not change protocol behavior;
- persist through session metadata;
- support filtering without changing queue order;
- remain localization-safe as user-authored text.

## 6.4 Watch folder

Route detected `.torrent` files through the existing shared transfer-add path:

```text
watcher
  -> TransferAddRequest
  -> TorrentManager.add_transfer()
```

Do not create a second torrent-loading implementation.

---

# 7. Network privacy and routing

SalixTorrent already has explicit interface/VPN binding and fail-closed Interface Lock. Future routing work must preserve that philosophy.

## 7.1 SOCKS5 proxy support

Centralize outbound routing policy rather than scattering proxy conditionals across modules.

Coverage must be deliberately defined for:

- peer TCP;
- HTTP/HTTPS trackers;
- UDP trackers;
- magnet metadata peers;
- DHT;
- DNS resolution;
- Local Peer Discovery.

Strict proxy mode must not silently leak unsupported traffic through direct sockets.

Proxy policy must compose with:

- source binding;
- Interface Lock;
- IPv4/IPv6 policy;
- MSE/PE policy.

## 7.2 uTP / BEP 29

Add uTP as another peer transport, not another peer-wire implementation.

Preserve shared peer-wire semantics, encryption policy, binding, Interface Lock, bandwidth accounting, telemetry, and v1/v2/hybrid identity behavior.

## 7.3 HTTP/WebSeed support

Candidate standards:

```text
BEP 19 url-list
BEP 17 httpseeds
```

Web seeds must feed the same verified piece pipeline. HTTP data must still pass normal piece/Merkle verification.

---

# 8. Queue and automation enhancements

Later candidates:

- pause/resume schedules;
- bandwidth schedules;
- queue rules by label/category;
- automatic seeding-stop rules;
- safe post-completion actions;
- configurable completion relocation.

Prefer event/timer-driven behavior over unnecessary polling.

---

# 9. Headless supervision / local control API

A future local control interface could expose:

- list transfers;
- add torrent/magnet;
- pause/resume/stop;
- remove;
- queue reorder/priority;
- rate limits;
- file priorities;
- diagnostics;
- graceful shutdown.

Prefer authenticated local RPC/HTTP/IPC over GUI automation.

Do not duplicate torrent-engine behavior in the control service.

---

# 10. Localization completion

Current canonical catalog:

```text
1271 entries
UI:       653
Help:     246
Glossary: 372
```

Current target packs remain intentionally partial and use offline `en-AU` fallback.

Remaining work:

- complete `en-GB`;
- complete `en-US`;
- complete `pt-BR`;
- complete `fil-PH`;
- human-review high-visibility UI;
- review security/privacy warnings;
- review BitTorrent/network terminology;
- review Help;
- review Glossary;
- run strict locale validation;
- run source/standalone/portable/installer localization smoke.

---

# 11. Cross-platform desktop validation

Native non-Windows smoke remains outstanding:

- Linux X11;
- Linux Wayland limitation behavior;
- OpenBSD/X11;
- macOS status-item/window restore;
- tray disable/fallback;
- native notifications;
- hide/restore/focus;
- clean shutdown;
- headless CLI.

Do not redesign the abstraction merely because native testing is still pending.

---

# 12. Persistence boundaries that should remain purpose-built

Keep these file-based unless a concrete requirement proves otherwise:

- payload files/directories;
- `.torrent` metainfo;
- cached `.torrent` metainfo;
- fast-resume piece-verification sidecars;
- short rolling speed history;
- high-frequency peer/block telemetry;
- UI logs;
- deterministic localization catalogs/manifests/review bundles.

A relational database is not automatically the right format for every durable artifact.

---

# 13. Priority order

## Priority A — immediate

**Commit the completed session-state persistence checkpoint.**

## Priority B — repository engineering

**Move the maintained regression suite into a tracked structured `tests/` unittest package.**

## Priority C — user-facing durability

1. seeding goals;
2. safe data relocation;
3. labels/categories;
4. watch folder.

## Priority D — privacy/network transport

1. SOCKS5 proxy policy;
2. uTP/BEP 29;
3. WebSeed support.

## Priority E — release/content

1. complete target locale population/review;
2. Windows frozen/portable/installer localization smoke;
3. Linux/BSD/macOS native desktop smoke;
4. choose next release scope.

## Priority F — later automation

1. local supervisory API/service mode;
2. scheduling/rules;
3. documentation timed media/layout inspector.

---

# 14. Possible release themes

Version numbers below are planning examples, not commitments.

## Next engineering checkpoint

```text
Tracked structured unittest suite
```

No version bump is required.

## Possible v0.4.0 theme

```text
Durability and transfer lifecycle
```

Possible contents:

- stable application/session persistence;
- seeding goals;
- safe data relocation;
- queue organization/watch-folder automation;
- localization/release hardening.

## Later network release

```text
Network routing and transport expansion
```

Possible contents:

- SOCKS5;
- uTP;
- WebSeeds;
- cross-platform network validation.

---

# 15. Engineering rules

1. Preserve shared GUI/headless engine paths.
2. Avoid alternate implementations of add/start/pause/restore behavior.
3. Keep protocol identity/storage verification explicit.
4. Keep optional dependencies lazy until deliberately promoted.
5. Prefer event/timer-driven work over polling.
6. Keep peer/block/network hot-path state out of ORM storage.
7. Preserve JSON/file compatibility until deliberately retired.
8. Treat corrupt durable state fail-closed where silent replacement destroys recovery evidence.
9. Keep maintained regression tests in version control once the test-tree migration lands.
10. Add regression coverage before declaring milestones complete.
11. Run real Windows smoke tests for persistence/packaging features.
12. Fix genuine SalixORM correctness defects in SalixORM.
13. Do not tag/bump versions without a deliberate release gate.

---

# 16. Current validation checkpoint

```text
Session persistence suite:
22 / 22 OK

Full real Windows suite:
299 / 299 OK
1 expected non-Windows skip

Live SalixORM session smoke:
migration session-state-0001
snapshot version 7
2 persisted torrents
beta before alpha
beta priority High
both Stopped
alpha selected
process restart restored 2 torrents
first GUI frame displayed persisted queue order
```

Future changes must preserve this baseline or account explicitly for every intentional test-count change.
