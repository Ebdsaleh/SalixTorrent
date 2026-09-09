# SalixTorrent Development Roadmap

**Current application version string:** `0.5.0`
**Roadmap status:** v0.5.0 released; post-v0.5.0 ecosystem extraction on `dev`
**Current implementation checkpoint:** Tranche 19 backend-neutral designer property-inspector presentation is published at `dev@35d0d4c0966aa9a3a6aafbe263edfbe8b383d7aa`; Tranche 20 backend-neutral designer workspace coordination is Windows-accepted and is the current `dev` implementation boundary
**Current real Windows regression baseline:** 746 / 746 in both accepted Tranche-20 discovery forms with one expected non-Windows shell-behavior skip; designer workspace 12 / 12, designer/relocation 151 / 151, GUI components 64 / 64 and Tkinter 30 / 30; localization remains 1,337/current, manual visual smoke and pre-commit passed.
**Accepted Tranche 12 baseline:** 643 / 643 in both real-Windows discovery forms with one expected skip; preview 12 / 12, designer/relocation 56 / 56, GUI components 64 / 64, Tkinter 22 / 22, visuals and pre-commit passed; closure/push checkpoint `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`
**Accepted Tranche 13 baseline:** 655 / 655 in both real-Windows discovery forms with one expected skip; preview host 11 / 11, designer/relocation 67 / 67, GUI components 64 / 64, Tkinter 23 / 23, localization current, visuals and pre-commit passed; implementation `ddfb3ef2269acb33484cd6fe2f99af47fa40140f`, closure/push checkpoint `4b0968bfdf91ce040eeefd641b1e315244a325e6`
**Accepted Tranche 14 baseline:** 668 / 668 in both real-Windows discovery forms with one expected skip; clipboard 12 / 12, designer/relocation 79 / 79, GUI components 64 / 64, Tkinter 24 / 24, localization current, visuals and pre-commit passed; implementation `450c12a`, closure/push checkpoint `f59a9a392bf64820f59787b9449d6b7ca9b3e634`
**Accepted Tranche 15 baseline:** 681 / 681 in both real-Windows discovery forms with one expected skip; selection/focus 12 / 12, designer/relocation 91 / 91, GUI components 64 / 64, Tkinter 25 / 25, localization current, visuals and pre-commit passed; published closure checkpoint `a0d621a8266cdf42b5b1355c417ec7d6d03bb297`
**Accepted Tranche 16 baseline:** 694 / 694 in both real-Windows discovery forms with one expected skip; project-file gate 12 / 12, designer/relocation 103 / 103, GUI components 64 / 64, Tkinter 26 / 26, localization current, visuals and pre-commit passed; implementation `a86acae`, closure/push checkpoint `d95f6a1987aaff1bda9fb270c6219b36b8ee2080`
**Accepted Tranche 17 baseline:** 707 / 707 in both real-Windows discovery forms with one expected skip; navigation 12 / 12, designer/relocation 115 / 115, GUI components 64 / 64, Tkinter 27 / 27, localization current, manual visual smoke and pre-commit passed; implementation `34b2084`, closure/push checkpoint `f07bc5cc0bda02b81ffefd35b2da3a47e1168c7d`
**Accepted Tranche 18 baseline:** 720 / 720 in both real-Windows discovery forms with one expected skip; hierarchy projection 12 / 12, designer/relocation 127 / 127, GUI components 64 / 64, Tkinter 28 / 28, localization current, manual visual smoke and pre-commit passed; implementation and acceptance documentation are published together at `9bd56a7e4a758529a54bbf45c3cc98bc061fa58c` under `Add designer hierarchy projection and expansion`
**Accepted Tranche 19 baseline:** 733 / 733 in both real-Windows discovery forms with one expected skip; property inspector 12 / 12, designer/relocation 139 / 139, GUI components 64 / 64, Tkinter 29 / 29, localization current, manual visual smoke and pre-commit passed; implementation and acceptance documentation are published together at `35d0d4c0966aa9a3a6aafbe263edfbe8b383d7aa` under `Add designer property inspector presentation`
**Accepted Tranche 20 baseline:** 746 / 746 in both real-Windows discovery forms with one expected skip; designer workspace 12 / 12, designer/relocation 151 / 151, GUI components 64 / 64, Tkinter 30 / 30, localization current, manual visual smoke and pre-commit passed; final implementation/acceptance commit and publication are pending

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
- backend-neutral transfer/session persistence with optional SalixORM/SQLite storage;
- durable per-torrent seeding goals with ratio/time automatic-stop policy.

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
9
```

Historical JSON versions `1-8` remain accepted as import/restore inputs.

SalixORM migration lineage:

```text
session-state-0001   initial v7 schema
session-state-0002   v8 seeding-goal fields
session-state-0003   v9 instanced timed-goal baseline + additive time components
```

Semantic metadata:

```text
kind = salix-session-state
schema_version = 1
snapshot_version = 9
```

## Completed acceptance checklist

- [x] backend-neutral session storage boundary;
- [x] JSON remains default/reference;
- [x] SalixORM remains explicit/lazy;
- [x] historical JSON versions 1-8 remain readable;
- [x] version 7 removes duplicate `max_active_downloads` authority;
- [x] version 8 adds per-torrent seeding-goal policy and cumulative seeding time;
- [x] version 9 separates cumulative Seed Time from the current timed-goal window and persists additive Days/Hours/Minutes quick components;
- [x] existing SalixORM v7/v8 databases upgrade through immutable `session-state-0001` -> `session-state-0002` -> `session-state-0003`;
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
- [x] 24/24 pre-seeding session persistence regression baseline;
- [x] 305/305 tracked-suite real Windows regression baseline before the seeding-goal tranche;
- [x] 34/34 current session-persistence regression suite;
- [x] 334/334 current full real Windows regression suite, with one expected non-Windows skip.

The real smoke restored `beta -> alpha`, `beta` High priority, both transfers Stopped, and `alpha` selected.

Fast-resume sidecars, cached `.torrent` artifacts, payload files, logs and protocol-hot-path telemetry remain outside this database boundary.

---

# 3. Repository-owned unittest suite — complete and validated

The maintained regression suite has been migrated from repository-root local files into a structured, version-controlled `tests/` package.

The migration preserves Python's built-in:

```text
unittest
```

No pytest dependency is required.

## Final structure

```text
tests/
├── __init__.py
├── helpers.py
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
│   ├── test_documentation.py
│   └── test_gui_components.py
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

## Naming and lineage rule

Maintained test filenames and classes describe the behavior or contract they protect rather than historical milestone numbers.

The former mixed milestone containers were split by responsibility:

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

Historical milestone lineage is preserved in module documentation where useful. Exact source-test commit hashes are not recorded where the original regression files were never version controlled; no hash is inferred or invented.

## Completed migration checklist

- [x] committed the session-state persistence checkpoint separately first;
- [x] created the `tests/` package tree;
- [x] moved all maintained root regression modules;
- [x] renamed `foundation_test.py` -> `tests/core/test_foundation.py`;
- [x] replaced milestone-only filenames/classes with semantic behavior-oriented names;
- [x] split mixed milestone files across logical modules;
- [x] preserved milestone lineage in module documentation where useful;
- [x] added `__init__.py` files for deterministic discovery;
- [x] introduced shared repository-root helpers;
- [x] removed moved-test assumptions that `Path(__file__).parent` is the repository root;
- [x] added dedicated restore regressions for unavailable source/cache metainfo and saved-info-hash mismatch refusal;
- [x] preserved subprocess working-directory expectations explicitly;
- [x] updated README test commands and project tree;
- [x] removed maintained-test exclusions from `.gitignore`;
- [x] kept generated Python cache/output artifacts ignored;
- [x] verified the focused session suite on the real Windows checkout;
- [x] verified both canonical and plain full discovery on the real Windows checkout;
- [x] accounted explicitly for the discoverable test-count change.

Test-count lineage:

```text
previous normal discovery:    299
foundation tests joining:      +4
new restore regressions:        +2
                              ----
current normal discovery:      305
```

Current Windows validation:

```text
python -m unittest tests.persistence.test_session_state_persistence -v
Ran 24 tests
OK

python -m unittest discover -s tests -t .
Ran 305 tests
OK (skipped=1)

python -m unittest discover
Ran 305 tests
OK (skipped=1)
```

The one skip remains the intentional non-Windows shell-behavior test.

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

## 6.1 Seeding goals and automatic stop policy — complete and Windows-validated

Implemented policy modes:

- Seed Indefinitely;
- Stop at Ratio;
- Stop after Time;
- Stop at Ratio or Time.

Current behavior:

- application defaults are normalized and copied into newly added torrents;
- changing the application default does not silently rewrite existing torrents;
- Preferences offers an explicit one-shot bulk action to apply the current default to all existing torrents;
- right-click Seeding Goal provides per-torrent mode changes, a focused ratio/time target editor, and lazy additive Stop-after-Time components for Days (1-31), Hours (1-12), and Minutes (1-60), plus an explicit clear action;
- Torrent Properties retains the same durable per-torrent override controls;
- each torrent's last saved policy persists independently across restart;
- explicit policy changes emit immediate UI updates without requiring stop/start or restart;
- ratio goals use persisted Uploaded Total divided by full torrent payload size, including source-backed seeds;
- a dedicated cumulative Seed Time clock advances only while the torrent is actually Seeding;
- time-based goals snapshot an independent baseline whenever the user applies/changes the timed goal, so historical Seed Time never satisfies a newly requested duration;
- policy, cumulative seed time, timed-goal baseline, and quick-time components persist through session snapshot version 9;
- historical v1-v7 snapshots restore as Seed Indefinitely rather than being reinterpreted through current defaults;
- reached goals route through `TorrentManager`, become durable Stopped intent, rebalance the queue and emit notification events;
- General shows ratio/time progress with timed elapsed/target values formatted as Days/Hours/Minutes; Configure targets, Torrent Properties and Preferences expose matching three-part duration editors;
- policy evaluation remains independent of JSON/SalixORM persistence adapters;
- Help Topics and the Glossary document ratio, time, default/override and restart behavior;
- localization extraction remains offline-first with canonical fallback for untranslated new strings.

The initial real Windows run passed 320/320 tests. Live GUI smoke then exposed that the application default was correctly staying separate from existing torrents but the per-torrent editing path was too easy to miss. The per-torrent/bulk refinement was then validated at 324/324 tests and its GUI smoke confirmed immediate updates, one-shot bulk application, persistence, and time-based automatic stop. The next live quick-menu smoke showed that Days/Hours/Minutes need to be independent additive components rather than mutually exclusive presets, and that a newly configured timed goal must count from the action moment rather than historical Seed Time. The v9 refinement implements those semantics while retaining Configure targets as the comprehensive exact-value editor. The additive/instanced-time refinement then passed 332/332 tests on the real Windows checkout. The Days/Hours/Minutes presentation/editor pass passed 334/334, and the final compact-layout polish stacked the Configure targets and Preferences duration controls vertically and widened the Preferences ratio input without changing the v9 persistence model. The final real Windows validation again passed 334/334 tests with the one expected non-Windows skip, and GUI smoke confirmed the polished controls, persistence, notifications, additive time selection, and instanced timed-goal behavior.

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
1337 entries
UI:       695
Help:     260
Glossary: 382
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

The next phase is a **dual extraction**: continue broadening the reusable RAD/framework surface while also separating a reusable application engine/runtime from SalixTorrent's current concrete desktop shell.

The detailed architectural target is maintained in `SalixTorrent-Ecosystem-Architecture.md`.

## Priority A — immediate: ecosystem extraction on `dev`

### A1. Inventory and ownership map — initial map established, audit ongoing

- [x] classify the first major candidates across product/domain, engine/runtime, RAD/framework, and backend/platform ownership;
- [x] document the Speed, network/runtime, lifecycle/presentation-host, desktop/platform, and rich-live-view seams before moving code;
- [ ] continue the inventory as deeper implementation details expose additional candidates;
- keep current names provisional while the wider boundary is still being discovered;
- preserve the v0.5.0 `main` branch as the stable rollback line.

### A2. Realtime telemetry and visualization — pushed/Windows-validated

The first post-v0.5.0 implementation tranche used the proven Active Transfers Speed view to establish a renderer-neutral realtime-data/plot boundary.

Committed/pushed checkpoint:

```text
ef8b4be998a714a86455940d8642fdd926a6609d
Extract realtime telemetry and plot boundary
```

Established ownership:

- `app/framework/telemetry.py` owns bounded fixed-series history, immutable snapshots, age windows and current/average/peak/minimum statistics;
- `app/framework/visualization.py` owns semantic line-series specs/data, complete plot frames, `PlotHost`, plot bindings and `RealtimeGraph`;
- `app/engine/plot_hosts/dearpygui.py` owns Dear PyGui plot/axis/line-series operations;
- `TorrentSession` uses generic rolling history while preserving the existing `speed_view` snapshot contract;
- `SpeedView` routes plot creation/updates through the generic boundary while retaining SalixTorrent labels, tooltips, rate units and limit semantics;
- the framework relocation probe exercises telemetry/visualization after package rename;
- real-Windows validation passed 432 / 432 on both discovery paths with one expected skip, plus live Speed and broader button/action smoke.

Ecosystem tranche 3 now provides a Tkinter Canvas plot host that consumes the same plot-facing contract rather than duplicating SalixTorrent application logic.

### A3. Application-engine/runtime boundary — completed/pushed

This completed tranche established the first reusable non-presentation engine package under `app/runtime/` rather than attempting to move `GuiEngine` wholesale.

Established generic runtime ownership:

```text
app/runtime/
├── lifecycle.py     explicit application/service lifecycle
├── scenes.py        backend-neutral scene registry/host contract
├── diagnostics.py   reusable exception reporting/throttling
├── paths.py         parameterized installed/portable/resource path policy
└── network.py       generic dual-stack interface/address/binding helpers
```

Runtime/lifecycle semantics:

- `ApplicationRuntime` supervises explicitly registered `RuntimeService` objects;
- services start in registration order and stop in reverse order;
- partial startup is cleaned up best-effort and earlier services roll back if a later start fails;
- update exceptions may be isolated through an injected error handler, while control-flow `BaseException` types such as `KeyboardInterrupt` are not swallowed;
- runtime restart is explicit and deterministic;
- no worker thread, hidden observer graph, renderer, event loop or model mutation is owned by the generic runtime.

Desktop integration proof:

- `GuiEngine` installs `DearPyGuiSceneHost` into the generic scene registry;
- application-menu and active-scene updates are explicit runtime services;
- frame delta is measured from the actual monotonic frame clock instead of using a hard-coded `0.016`;
- the existing Dear PyGui callback queue/render loop, tray/window policy and component/layout/plot adapters remain concrete engine/backend responsibilities;
- UI exception throttling/logging is composed through reusable `ExceptionReporter`.

Headless proof:

- `HeadlessRunner` now uses the same `ApplicationRuntime` lifecycle for torrent-engine startup/shutdown;
- headless execution still imports no Dear PyGui presentation backend.

Runtime-path proof:

- generic `RuntimePathSpec` / `RuntimePaths` owns installed/portable/state/download/resource resolution;
- `app/engine/runtime_paths.py` remains the SalixTorrent composition facade that supplies product-specific application/environment names;
- existing source/frozen/portable behavior and compatibility function surface remain intact.

### A4. Generic network/runtime awareness — completed/pushed

The same tranche moves the already reusable interface/address/source-binding mechanisms to `app/runtime/network.py`.

Extracted mechanism includes:

- canonical IPv4/IPv6 bind-address normalization;
- address-family and wildcard helpers;
- endpoint formatting;
- cross-platform interface discovery;
- usable local-address inventories;
- default-route source-address probing;
- local bind-availability checks;
- presentation-safe IP masking.

SalixTorrent production callers now consume these generic mechanisms directly. `app/logic/network_binding.py` remains a compatibility facade during extraction.

The following remain explicitly application/domain-owned: trackers, DHT, PEX, LPD, peer sessions, torrent listener policy, MSE/PE, Interface Lock policy, connectivity interpretation/diagnostic wording, and torrent lifecycle consequences. `ConnectivityManager` is therefore **not** moved wholesale.

Validation added **50** focused runtime/scene/network/adapter/relocation regressions and passed both complete real-Windows discovery paths at **482 / 482** with the same one expected non-Windows shell-behavior skip. The exact pushed checkpoint is `8e707efeb0cda162ee038a028a39a77663c2fa4e` (`Extract application runtime and network foundation`).

### A5. Second GUI implementation — completed/pushed

Tkinter now provides the compatibility implementation for the common component, responsive-layout, scene, and realtime-plot contracts. Dear PyGui, Tkinter, and headless execution are composed through explicit presentation-backend bundles, while small toolkit-specific application hosts own their event loops and drive the same `ApplicationRuntime`.

The first non-SalixTorrent proof is `examples/ecosystem_blank_app.py`. Its semantic component tree and realtime graph definition are identical for Dear PyGui and Tkinter; only the outer host selected by `--ui-backend dearpygui|tkinter|headless` changes. Headless mode exercises the same runtime with no graphical toolkit.

Validation added **34** focused application/presentation/backend regressions and passed both complete real-Windows discovery paths at **516 / 516** with one expected non-Windows shell-behavior skip. Live Dear PyGui and Tkinter blank-application proof plus the existing SalixTorrent desktop smoke also passed. The exact pushed checkpoint is `522ac8467fc55a5ac0e3d71fe5fd470251e13562` (`Add Tkinter compatibility application backend`).

Do **not** rewrite SalixTorrent wholesale in Tkinter and do not require identical capability/performance parity between backends. Dear PyGui remains the reference SalixTorrent desktop backend.

### A6. Rich live-data presentation — completed/pushed

The first rich-live-data tranche extracts only the semantics already proven by the read-only Peers, Sources and Pieces surfaces:

- keyed `LiveTable` row identity with incremental changed-row updates, removal and reordering;
- renderer-neutral column/cell/row/frame data;
- optional cell foreground/tooltip presentation metadata;
- compact categorical `StateGrid` frames for high-density state/activity maps;
- Dear PyGui and Tkinter table/state-grid hosts;
- new `LIVE_TABLES` and `STATE_GRIDS` presentation capabilities;
- Peers and Sources migrated away from direct Dear PyGui row rebuilds;
- Pieces detail rows and piece-map drawing migrated behind the same generic boundaries;
- the blank ecosystem application expanded to prove live tables and state grids through both GUI backends.

Validation added **13** focused regressions and passed both complete real-Windows discovery paths at **529 / 529** with one expected non-Windows shell-behavior skip. Live Dear PyGui/Tkinter blank-application proof, state-grid resize reflow, Peers/Sources/Pieces smoke and the existing SalixTorrent desktop surface all passed. The exact pushed checkpoint is `a561b50ddc64520d1dc10b362fb4180378da5dc8` (`Extract live table and state grid presentation`).

### A7. Interactive data, selection and command semantics — completed/pushed

This tranche adds the richer semantics deliberately deferred from the read-only live-data tranche:

- standard-library-only keyed `DataView` search/filter/sort projection;
- explicit multi-term ascending/descending sort state;
- explicit single-selection state;
- renderer-neutral command identity plus enabled/checked/submenu state;
- Active Transfers queue sorting/filter visibility routed through the generic data-view model while its torrent-specific actions remain application-owned;
- Files migrated to `LiveTable`, retaining per-file priority mutation but describing priority command availability through generic `CommandSet` state;
- relocation/package-boundary proof for the new interaction modules.

The real Windows gate passed both discovery forms at **547 / 547** with one expected non-Windows shell-behavior skip. The exact pushed checkpoint is `e16e46884acc53adf54a29a35dbfd09bba40ed26` (`Extract interactive data and command models`).

### A8. Command presentation, ordered items and mixed layout — completed/pushed

This extraction turns the semantic command model into reusable physical presentation and establishes the first parent-aware mixed-layout foundation required by a real WYSIWYG editor:

- `CommandMenu` + `CommandMenuHost` with Dear PyGui and Tkinter implementations;
- nested commands plus enabled/checked state rendered by either backend;
- one shared File-priority command menu instead of one Dear PyGui popup per file row;
- generic `OrderedItems` with `move_item_up`, `move_item_down` and explicit index movement, applied to Active Transfers scheduler order instead of toolkit movement primitives;
- `Placement`, `PlacedComponent`, and `PositionedPanel`: local `(x, y)` placement remains parent-relative, while positioned children can reserve offset + margins + child size so automatic grid cells grow around them;
- renderer `place(...)` and `measure(...)` contracts implemented by Dear PyGui and Tkinter;
- blank-application proof that command menus and explicit local placement coexist with structured layout through both GUI backends.

The real Windows gate passed both discovery forms at **563 / 563** with one expected non-Windows shell-behavior skip. The exact pushed checkpoint is `19ee1ba92826501e2061132e2a514a38862082a1` (`Add command menus and mixed layout foundation`).

### A9. Structural tabs, split regions and non-measuring overlays — completed/pushed

This structural pass proves that mixed layout is recursive rather than a special-case positioned panel:

- renderer-neutral `TabContainer` / `TabPage` with stable semantic page keys and normalized change events;
- renderer-neutral `SplitPanel` / `SplitPane` with horizontal or vertical weighted allocation, per-pane minimums and responsive reflow through the existing `LayoutCoordinator`;
- non-measuring overlay placement, so an explicitly positioned HUD/decoration can share local coordinates without enlarging its parent;
- Download detail tabs migrated from direct Dear PyGui tabs to `TabContainer`;
- Download General's three application panels migrated to a responsive `SplitPanel` while retaining SalixTorrent-owned content/wrapping semantics;
- Help Contents/Glossary navigation migrated to `TabContainer`, and the index/document region migrated to `SplitPanel`;
- the application menu now selects Download detail pages by semantic key instead of backend item ID;
- the blank ecosystem application expanded to prove tabs, weighted splits, measured explicit placement and non-measuring overlays through both GUI backends.

The real-Windows gate passed both complete discovery forms at **581 / 581** with one expected non-Windows shell-behavior skip. Visual acceptance additionally caught and repaired two silent Dear PyGui integration differences: split-pane geometry could collapse into one visually dominant pane, and tab callbacks could omit the selected-page handle from callback data. The exact pushed checkpoint is `731303d847a46c1e7e250d34d8b78a9e51f485ef` (`Add structural tabs, split regions and overlays`). Canonical localization remains 1,337 strings.

### A10. WYSIWYG designer prerequisites — geometry tranche completed/pushed

The first designer-preparation tranche extends the proven mixed-layout runtime without introducing a complete designer model:

- `AxisAnchor` provides start / centre / end / stretch semantics on each parent-local axis;
- `AnchoredPlacement` and `AnchoredChild` resolve against the current `PositionedPanel` content rectangle and reflow through `LayoutCoordinator`;
- `SizeConstraints` provides reusable minimum/maximum width and height bounds;
- fixed and anchored placement metadata round-trips through JSON-safe descriptors without importing a GUI toolkit;
- `SplitPane.maximum` plus `split_sizes(..., maximums=...)` adds richer structural constraints while preserving historical behavior when maximums are omitted;
- Help proves a real application use by capping the index/navigation pane at 480 px on ultrawide layouts;
- the blank ecosystem application proves anchored start/end/stretch geometry and constrained responsive sizing through the shared GUI contracts.

Real-Windows acceptance passed both complete discovery forms at **591 / 591** with one expected skip after repairing the Diagnostics public error-log seam and the blank demo's narrow-layout composition floor. Dear PyGui and Tkinter visual rechecks passed, and the exact pushed checkpoint is `5cef12f534dfc44a8536f504d1aa7773644f5428` (`Add responsive anchors and designer geometry constraints`). Canonical localization remains 1,337 strings and `APP_VERSION` remains `0.5.0`.

### A11. WYSIWYG designer prerequisites — component metadata and hierarchy snapshots accepted

The next Stage-F slice describes the component tree that the geometry tranche can already lay out:

- `DesignerValueKind`, `DesignerPropertySpec` and `DesignerComponentSpec` describe provisional editor-facing type/property metadata without importing a GUI toolkit;
- `DesignerCatalog` and `FRAMEWORK_DESIGNER_CATALOG` cover the framework `Component` classes currently imported by SalixTorrent views while keeping type keys explicitly provisional;
- `DesignerIdentityMap` gives live component objects stable designer IDs and supports explicit persisted-key binding;
- `DesignerNode`, `DesignerChild` and `DesignerSnapshot` capture validated JSON-safe hierarchies with unique IDs and the type metadata needed to interpret every captured node;
- relationship metadata preserves grid row/column positions, tab page keys, split pane weights/minimums/maximums/borders, and fixed/anchored placement descriptors;
- `capture_component_tree(...)` rejects cycles/reused component instances instead of silently producing ambiguous ownership;
- the product-neutral blank application snapshots its actual nested component tree with stable IDs, and the relocation gate exercises the same snapshot after the framework is copied/renamed.

Preparation advanced complete discovery from 591 to **602 tests**; display-less canonical Linux discovery passed 602 / 602 with 58 expected GUI/platform skips. Real-Windows acceptance then passed both complete discovery forms at **602 / 602** with one expected skip, Dear PyGui and Tkinter resize/structure smoke checks passed, and the accepted implementation commit is `5b54084f2d21dc331deb4614c15119ad94cab374`. The acceptance-documentation closure was pushed at `d939f6443a95490881925ca8bdb93e5e94f7ec2c`. Canonical localization remains 1,337 strings and `APP_VERSION` remains `0.5.0`.

This tranche intentionally stopped before executable reconstruction/factories, live property mutation, copy/paste, drag/drop/reparenting, a final project document/schema, preview/runtime restoration, percentages or draggable split handles. Snapshot-level property commands and undo/redo are prepared in the following tranche; the type keys and snapshot shape remain internal working contracts and do not freeze a public designer API.

The future designer should itself use the same engine/framework wherever practical.

### A12. WYSIWYG designer prerequisites — snapshot property commands and undo/redo complete

The next Stage-F slice adds editing semantics without pretending that a serialized snapshot is already an executable application project:

- `app/framework/designer_editing.py` is standard-library-only and edits `DesignerSnapshot` values rather than live renderer/component objects;
- `SetDesignerProperty`, `ClearDesignerProperty` and `CompositeDesignerEdit` are explicit commands with one deterministic `apply(snapshot)` boundary;
- metadata-driven validation covers text, booleans, bounded integer/number values, choices, string/number lists, semantic dimensions and insets;
- `DesignerPropertySpec.nullable` distinguishes explicit `None` from absence, while `unsettable` marks sparse overrides that may legally be reset to inherited/default state;
- `DesignerPropertyState` exposes inspector-facing metadata plus whether a property is explicitly set;
- `DesignerEditSession` owns current snapshot state, whole-snapshot undo/redo history, redo invalidation after divergent edits, grouped one-step edits, and clean/dirty tracking;
- undo/redo command availability reuses the generic `CommandSet` model rather than creating a designer-only menu/action abstraction;
- the relocation proof edits and undoes a snapshot after the framework package is copied/renamed, while the blank-application regression proves the real demo hierarchy can be edited as document data without changing its live components;
- tracked `validate_tranche.bat` now automates non-visual tranche validation into `%USERPROFILE%\Desktop\console_output.txt` while leaving Dear PyGui/Tkinter visual inspection manual.

Preparation advanced canonical discovery from 602 to **616 tests** on display-less Linux with 58 expected GUI/platform skips. After validator-launch and Tk/Tcl lifecycle repairs, real-Windows acceptance passes both complete discovery forms at **616 / 616** with one expected skip. The focused designer-editing, relocation, GUI-component and Tkinter gates pass, canonical localization remains 1,337 strings, manual Dear PyGui/Tkinter/SalixTorrent visual smoke passes, the accepted implementation commit is `3968bd2`, and the Windows-acceptance documentation closure is `df675e89bf025b570a339c7b3fb3c3518262d72a`. `APP_VERSION` remains `0.5.0`.

This tranche deliberately stops before reconstructing executable components from edited snapshots, mutating a live preview tree, structural insert/remove/reparent commands, copy/paste, drag/drop/resize handles, persisted command history, a final project schema or API/package naming freeze. Whole immutable snapshots are retained in history for correctness while the design contract is still provisional; later storage optimization must preserve the same explicit command semantics.

### A13. WYSIWYG designer prerequisites — structural hierarchy mutation/reparenting complete

This Stage-F slice makes the serialized hierarchy editable without creating live preview objects:

- `DesignerChildSlotSpec` makes allowed relationship slots, cardinality, required metadata and sibling-identity fields inspectable through the existing component type descriptors;
- linear containers, grid cells, positioned/placed children, tab pages, split panes, labeled-field parts and duration-editor parts now describe their structural slots explicitly;
- `DesignerNodeLocation` exposes a node's parent, sibling index, slot, relationship metadata and depth without depending on toolkit handles;
- `InsertDesignerChild`, `RemoveDesignerNode`, `MoveDesignerNode` and `ReparentDesignerNode` transform immutable `DesignerSnapshot` values and preserve stable subtree IDs;
- relationship validation rejects duplicate IDs, unknown types, invalid parent slots, root removal/reparenting, cycles, duplicate grid coordinates/tab keys/split keys and malformed fixed/anchored placement metadata;
- `DesignerEditSession` exposes convenience helpers for all four operations while reusing the Tranche-10 undo/redo and dirty-state history exactly;
- the relocated-framework proof performs a structural insertion/undo after package rename, and the blank application reparents its captured `Actions` node as document data while the live component tree remains unchanged;
- tracked validation records `origin/dev` as well as local `HEAD` and adds the dedicated structural gate.

Preparation advanced complete discovery from 616 to **630 tests**. Structural tests passed 14 / 14, the combined designer/relocation gate passed 44 / 44, the real Tkinter backend passed 21 / 21 under Xvfb, and real-Windows acceptance then passed both complete discovery forms at 630 / 630 with one expected skip. Manual Dear PyGui/Tkinter/SalixTorrent visual smoke and pre-commit checks passed, and the tranche was published at `79edec6cb4531759992b4f7fdb2d63ac8f122907`.

This tranche deliberately does not instantiate live components from snapshots, synchronize a preview tree, add copy/paste or duplication, implement pointer-driven drag/drop/resize handles, persist history, or freeze a project schema/public API.

### A14. WYSIWYG designer prerequisites — snapshot-to-preview reconstruction complete

Tranche 12 added the first reconstruction path from supported immutable `DesignerSnapshot` documents back into fresh framework `Component` trees. `DesignerPreviewCatalog` remains backend-neutral, preserves stable designer IDs, restores semantic grid/tab/split/fixed/anchored relationships, and intentionally leaves callbacks/application services inert. The blank ecosystem application round-trips through this bridge and a reconstructed copy builds through the real Tkinter renderer.

Real-Windows acceptance passed the 12-test preview gate, 56-test designer/relocation gate, 64 GUI-component tests, 22 Tkinter tests and both complete **643 / 643** discovery forms with one expected skip. Manual visual smoke and pre-commit passed. The implementation commit `688bcff` plus its Windows-acceptance documentation closure were published together at `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`.

### A15. WYSIWYG designer prerequisites — transactional preview ownership/rebuild accepted and published

Tranche 13 adds an optional `DesignerPreviewHost` above the code-first component framework. It owns one reconstructed preview for a `DesignerEditSession`, prepares candidate trees transactionally, and replaces the accepted preview only after reconstruction/build succeeds. Generic checked execute/undo/redo gates keep preview validation outside the editing core, so ordinary component applications remain independent of designer tooling. Real-Windows acceptance passed 11 / 11 preview-host tests, 67 / 67 designer/relocation tests, 64 GUI-component tests, 23 Tkinter tests and both complete **655 / 655** discovery forms with one expected skip after repairing a pre-existing temporary-directory lifetime race in a persistence regression. Manual visual smoke and pre-commit passed; implementation `ddfb3ef2269acb33484cd6fe2f99af47fa40140f` and its documentation closure were published together at `4b0968bfdf91ce040eeefd641b1e315244a325e6`.

The architecture explicitly preserves two equal authoring paths: direct Python composition and future designer-authored documents both converge on the same semantic `Component` tree, application runtime and backend adapters. SalixTorrent remains the primary code-first reference application; the future RAD editor is an additional authoring surface rather than a required runtime dependency.

The accepted Tranche-13 publication checkpoint is `4b0968bfdf91ce040eeefd641b1e315244a325e6`.

### A16. WYSIWYG designer prerequisites — document copy/paste/duplicate accepted

Tranche 14 keeps clipboard behavior in document/tooling space. `DesignerClipboardPayload` captures a detached immutable subtree plus its source child-slot/relationship metadata; `remap_designer_subtree_ids(...)` deterministically creates fresh IDs in preorder; and `PasteDesignerSubtree` / `DuplicateDesignerNode` route the cloned tree back through the existing structural validation boundary. Repeated paste uses predictable `-copy`, `-copy-2`, ... identities without reusing source IDs.

`DesignerEditSession` owns only ephemeral clipboard state: copy does not dirty the document or touch undo/redo history, while paste and duplicate are ordinary immutable edit commands. Payloads can be passed explicitly between compatible sessions without defining an on-disk project or operating-system clipboard format. `DesignerPreviewHost` adds matching helpers, with paste/duplicate using its checked whole-preview replacement transaction and copy causing no preview rebuild.

The blank application's code-first hierarchy remains untouched while its captured `Actions` node is duplicated in document/preview space. A real Tkinter regression proves the duplicate receives a fresh stable designer ID in the replacement preview and disappears again after undo. The copied/renamed framework probe also exercises subtree capture/paste with no SalixTorrent or GUI dependency.

Real-Windows acceptance advances the baseline to **668 tests** in both complete discovery forms with one expected skip. Clipboard tests pass 12 / 12, combined designer/relocation focus 79 / 79, GUI components 64 / 64 and Tkinter 24 / 24; localization remains current, headless/compileall/Git checks pass, manual Dear PyGui/Tkinter/SalixTorrent smoke passes, and `pre_commit_check.bat` passes. The accepted implementation commit is `450c12a` (`Add designer copy paste and duplicate commands`); implementation and documentation closure were published together at `f59a9a392bf64820f59787b9449d6b7ca9b3e634`.

This tranche does not introduce an operating-system clipboard, cut/multi-selection semantics, drag/drop or resize gestures, incremental live toolkit mutation, project persistence/schema, callback/service serialization or a final public API freeze.

### A17. WYSIWYG designer prerequisites — stable-ID selection/focus accepted

Tranche 15 introduces explicit designer interaction state without turning editor state into project data. `DesignerSelectionModel` keeps one selected node ID and one focused node ID, validates them against the current immutable snapshot, and resolves current nodes/locations without retaining preview components or toolkit handles. Selection and focus can move independently or be coupled explicitly.

`DesignerEditSession` owns the ephemeral selection model alongside its existing clipboard state. Selection/focus changes do not dirty the document, add undo/redo entries or alter redo branches. Accepted document edits reconcile stable IDs: property edits, moves and reparenting retain identity; removal falls back to the nearest surviving ancestor; undo/redo restores document state without reviving historical selection as though it were serialized project data.

`DesignerPreviewHost` exposes the same selection/focus operations without rebuilding. `selected_component` and `focused_component` resolve the stable IDs against the current preview generation, so transactional whole-tree replacement can dispose old component objects while editor selection remains anchored to the same designer identity. A real Tkinter regression proves this against the blank application's `Actions` control.

Real-Windows acceptance passed the dedicated selection gate 12 / 12, combined designer/relocation 91 / 91, GUI components 64 / 64 and Tkinter 25 / 25. Both complete discovery forms passed **681 / 681** with one expected skip; localization remained 1,337/current, headless/compileall/Git checks passed, manual Dear PyGui/Tkinter/SalixTorrent smoke passed and `pre_commit_check.bat` passed. The accepted implementation is `98f64e2` (`Add stable designer selection and focus state`); implementation and documentation closure are published together at `a0d621a8266cdf42b5b1355c417ec7d6d03bb297`.

This tranche intentionally stops before multi-selection/range selection, keyboard traversal policy, visual selection overlays, pointer hit-testing, drag/drop/resize handles, persistent project documents, callback/service serialization, incremental in-place toolkit mutation or final public API/package naming.

### A18. WYSIWYG designer prerequisites — provisional project-file ownership/save-load Windows-accepted

Tranche 16 adds the first on-disk ownership boundary around the existing immutable designer document without claiming a final RAD project format. `DesignerProjectDocument` is a strict versioned JSON envelope containing only one `DesignerSnapshot`; `DesignerProjectFile` owns one `DesignerEditSession`, an optional absolute path and the persisted/dirty relationship. New in-memory projects are unsaved/dirty, opened files begin clean, and Save/Save As mark the session clean and transfer path ownership only after an atomic same-directory replacement succeeds.

Load validation is intentionally strict: duplicate JSON keys, non-finite numeric tokens, missing or unexpected envelope fields, unsupported project versions and invalid embedded snapshots are rejected. Serialization is deterministic sorted UTF-8 JSON with one terminal newline. No file extension is mandated while naming remains provisional. Selection/focus, clipboard and undo/redo history are fresh editor state after reopen rather than serialized project content.

The blank code-first application's captured hierarchy round-trips descriptor-identically through this project layer without mutating the live source tree. Reopened project sessions feed the existing `DesignerPreviewHost`, and a real Tkinter proof renders a reopened blank-application project through the same preview/backend path. Framework relocation exercises the same save/open contract after package rename. Real-Windows acceptance passes 12 / 12 project-file tests, 103 / 103 combined designer/relocation tests, 64 / 64 GUI-component tests and 26 / 26 Tkinter tests; both complete discovery forms pass **694 / 694** with one expected skip. Localization remains current, headless/compileall/Git checks and manual visual smoke pass, and `pre_commit_check.bat` passes. The accepted implementation commit is `a86acae`; implementation and documentation closure were published together at `d95f6a1987aaff1bda9fb270c6219b36b8ee2080`.

This remains a narrow designer-tooling prerequisite. The project envelope stores no callbacks, services, bindings, assets, application runtime state, selection/focus, clipboard or undo history. Multi-document editors, migrations, autosave/recovery, resource manifests, recent-project UI, final extension/schema naming and pointer-driven canvas gestures remain later work. Code-first applications remain equal and independent.

### A19. WYSIWYG designer prerequisites — stable-ID hierarchy navigation Windows-accepted

Tranche 17 adds a read-only hierarchy navigation model above the immutable snapshot and stable selection contracts. `DesignerHierarchyNavigator` computes parent, first/last child, previous/next sibling and previous/next preorder targets directly from snapshot child order. `DesignerHierarchyReveal` reports the root-to-parent ancestor IDs a future hierarchy widget must expand to reveal a target without making expansion state part of the project document.

`DesignerEditSession` exposes relative selection/focus navigation and reveal helpers as ephemeral interaction operations. They do not edit the snapshot, dirty the project, create undo entries, clear redo history or trigger preview replacement. `DesignerPreviewHost` delegates the same operations, allowing a rendered preview to resolve the newly selected component by stable ID while its generation remains unchanged.

The copied/renamed framework probe exercises navigation after package relocation, and a real Tkinter regression navigates from the blank application's rendered `Actions` control to its parent/child hierarchy without rebuilding the preview. Real-Windows acceptance passes 12 / 12 navigation tests, 115 / 115 combined designer/relocation tests, 64 / 64 GUI-component tests and 27 / 27 Tkinter tests; both complete discovery forms pass **707 / 707** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes. The accepted implementation commit is `34b2084`; implementation and documentation closure are published together at `f07bc5cc0bda02b81ffefd35b2da3a47e1168c7d`.

This tranche does not introduce a concrete hierarchy tree widget, persistent expansion state, toolkit keyboard bindings, multi-selection, pointer hit-testing, visual overlays, drag/drop/reparent gestures or resize handles. Those remain later Stage-F surfaces built on these stable semantic targets.

### A20. WYSIWYG designer prerequisites — hierarchy projection/expansion Windows-accepted

Tranche 18 adds `app/framework/designer_hierarchy.py` above the accepted stable-ID navigation model. `DesignerHierarchyProjection` owns only ephemeral expanded IDs and produces visible `DesignerHierarchyRow` records carrying stable ID, type key, depth, parent ID, child count, expanded state and selected/focused markers. The root is expanded by default when useful; reveal expands ancestor IDs from the existing navigation contract rather than inventing toolkit-specific tree behavior.

`DesignerEditSession` owns one projection alongside its existing selection/focus and clipboard state. Expansion operations do not dirty the immutable document, alter project persistence or enter undo/redo history. Accepted edits reconcile surviving expandable IDs; removed or now-leaf nodes are dropped, and undo/redo deliberately does not resurrect historical expansion as though it were project data. `DesignerPreviewHost` delegates the same model without rebuilding previews. A real Tkinter proof selects and reveals the rendered `Actions` control, collapses its hierarchy parent, verifies the row becomes hidden while the rendered component remains valid, and keeps preview generation unchanged.

Real-Windows acceptance passes 12 / 12 hierarchy-projection tests, 127 / 127 combined designer/relocation tests, 64 / 64 GUI-component tests and 28 / 28 Tkinter tests. Both complete discovery forms pass **720 / 720** with one expected skip; localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes. Concrete hierarchy widgets, persisted expansion, keyboard binding policy, range/multi-selection, pointer hit-testing, drag/drop/resize gestures and final public API/package naming remain deferred.

### A21. WYSIWYG designer prerequisites — property-inspector presentation Windows-accepted

Tranche 19 adds `app/framework/designer_inspector.py` over the accepted property metadata and stable-ID selection model. `DesignerPropertyInspector` derives a selection-driven `DesignerInspectorState` containing the selected node's type label/category and ordered `DesignerInspectorRow` records. Rows preserve the existing `DesignerPropertyState` contract and add toolkit-neutral editor hints plus derived edit/clear affordances; no concrete control type, renderer item or toolkit handle becomes part of framework semantics.

Inspector projection is editor interaction/presentation state only. Selecting a node or asking for inspector rows does not dirty the project, enter undo history, alter hierarchy expansion or rebuild the preview. `DesignerEditSession` selected-property helpers reuse the existing validated set/clear commands; `DesignerPreviewHost` routes the same edits through the established checked preview transaction. Project files still serialize only the snapshot envelope, so inspector target state is not persisted.

Real-Windows acceptance passes 12 / 12 inspector tests, 139 / 139 combined designer/relocation tests, 64 / 64 GUI-component tests and 29 / 29 Tkinter tests. Both complete discovery forms pass **733 / 733** with one expected skip; localization remains 1,337/current, headless 3 updates, compileall and Git whitespace checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes.

Still defer concrete Dear PyGui/Tkinter property-editor widgets, inline validation-message UI, multi-selection/mixed-value editing, property grouping/search/favorites, preview pointer hit-testing, visual selection overlays, drag/drop/reparent gestures, resize handles, callback/service/binding serialization and final project/API naming.

### A22. WYSIWYG designer prerequisites — workspace coordination Windows-accepted

Tranche 20 adds `app/framework/designer_workspace.py` as a composition seam over the already-accepted designer project, edit-session, preview-host, hierarchy and inspector models. `DesignerWorkspaceState` gives a future editor shell one immutable snapshot of project path/persisted/dirty/save requirements, undo/redo availability and labels, clipboard presence, stable selection/focus, hierarchy expansion/visible rows, inspector projection and preview generation/rendered availability. The coordinator intentionally does not own a second copy of any of those states.

`DesignerWorkspace` can create/open a `DesignerProjectFile` or adopt an existing `DesignerPreviewHost` only when both share exactly one `DesignerEditSession`. Save/Save-As stays owned by the project file and does not rebuild the preview. Selection/hierarchy/inspector operations stay ephemeral. Property edits, paste/duplicate and undo/redo delegate through the preview host so the existing checked candidate-build transaction remains authoritative. Explicit `sync_preview()` covers the already-supported case where an external session edit temporarily moves the document ahead of the preview.

The copied/renamed framework probe exercises the coordinator without SalixTorrent or Dear PyGui, and a real Tkinter regression proves the same workspace flow through the compatibility backend. Real-Windows acceptance passes 12 / 12 workspace tests, 151 / 151 combined designer/relocation tests, 64 / 64 GUI-component tests and 30 / 30 Tkinter tests; both complete discovery forms pass **746 / 746** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes. This tranche does not add a concrete editor shell, multi-document ownership, autosave/recovery, pointer hit-testing, drag/drop/resize gestures, mixed-value multi-selection or final project/package/API naming. Code-first composition remains a permanent first-class path over the same runtime/components.

### A23. Naming, public API and package/repository split

This remains **after** the wider extraction.

Do not freeze component terminology or external package names until:

- engine lifecycle is reusable;
- Dear PyGui is clearly an adapter;
- a meaningful Tkinter slice implements the same contracts;
- headless remains first-class;
- realtime visualization is renderer-neutral;
- rich live-data view auditing is substantially complete;
- designer metadata requirements are understood;
- a small non-SalixTorrent application can be created without copying SalixTorrent-specific code.

## Priority B — user-facing SalixTorrent durability

1. safe data relocation;
2. labels/categories;
3. watch folder;
4. additional transfer-lifecycle polish discovered through normal use.

These should not interrupt Priority A merely because they are easier to ship.

## Priority C — privacy/network transport

1. SOCKS5 proxy policy;
2. uTP/BEP 29;
3. WebSeed support;
4. additional cross-platform networking validation.

## Priority D — localization/release/content

1. complete target-locale population/review;
2. Windows frozen/portable/installer localization smoke as locale content matures;
3. Linux/BSD/macOS native desktop smoke;
4. preserve deterministic offline locale/review tooling.

## Priority E — later automation

1. local supervisory API/service mode;
2. scheduling/rules;
3. documentation timed media/layout inspector.

---

# 14. Release and branch themes

Version numbers below remain planning guides rather than promises.

## v0.5.0 — released

```text
Reusable GUI component foundation
```

Release commit/tag target:

```text
d403c47f98f7e30d8adf879cd04e098dabc8767e
v0.5.0
```

Release pillars:

- backend-neutral component and composition foundation;
- explicit binding/event/disposal semantics;
- semantic documentation and pure geometry;
- framework package-relocation proof;
- backend-neutral responsive coordination;
- Dear PyGui isolated as the current concrete desktop adapter;
- 416 / 416 real-Windows release tests with one expected non-Windows skip;
- standalone GUI/CLI, portable ZIP and installer release artifacts.

## Post-v0.5.0 development theme

```text
Modular application ecosystem extraction
```

The active `dev` line now broadens the work in two directions at once:

```text
reusable application engine/runtime
            +
optional RAD/application framework
            +
presentation/platform adapters
```

Dear PyGui remains the reference GUI backend. Tkinter is now the validated compatibility implementation for the common GUI surface, while headless/CLI remains a first-class execution profile. Future GLFW/OpenGL or other backends are allowed by the architecture when a real project justifies them; they are not current dependencies.

A future v0.6.0 may consolidate a coherent portion of this ecosystem work, but the release number should follow proven scope rather than drive it.

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

1. Keep `main` stable and released; perform active extraction/integration work on `dev`.
2. Preserve shared GUI/headless engine behavior and keep headless operation first-class.
3. Treat the ecosystem as cohesive but modular: applications should import only the capabilities they need.
4. Keep Dear PyGui as the current reference presentation backend without allowing Dear PyGui concepts to define generic contracts.
5. Use Tkinter as the compatibility implementation to challenge backend assumptions; do not force identical feature parity.
6. Keep UI-backend selection conceptually separate from hardware/3D acceleration.
7. Application/view code should depend on semantic contracts rather than branch on Dear PyGui versus Tkinter for ordinary framework behavior.
8. Prefer small backend contracts plus explicit capabilities over one premature monolithic presentation interface.
9. Extract generic mechanism; keep BitTorrent/product policy in SalixTorrent and OS/toolkit details in adapters.
10. Do not freeze framework/engine names or a public third-party API until the wider extraction and second-backend proof are mature.
11. Do not wrap complex tables/graphs cosmetically; generalize only when reusable semantics are demonstrated.
12. Prefer event/timer-driven work over polling.
13. Keep peer/block/network hot-path state out of ORM storage.
14. Preserve JSON/file compatibility until deliberately retired.
15. Treat corrupt durable state fail-closed where silent replacement destroys recovery evidence.
16. Keep maintained regression tests in version control and add regressions for new boundaries.
17. Run real Windows smoke/release gates before merging a release candidate back to `main`.
18. Fix genuine SalixORM correctness defects in SalixORM rather than compensating for them in application code.
19. Do not tag/bump versions without a deliberate release gate.
20. Treat layout strategy as container-local: structured and explicit-placement regions must be nestable rather than forcing one geometry model across an entire window. Parent-local placement coordinates are resolved inside the parent content origin, and placed children should reserve their occupied offset + margins + size so structured rows/columns can grow around them instead of clipping them.
21. Keep final WYSIWYG designer metadata driven by proven runtime/component contracts rather than designing the editor model in isolation.

---

# 16. Current validation checkpoint

```text
Released SalixTorrent:
version:                         0.5.0
release commit:                  d403c47f98f7e30d8adf879cd04e098dabc8767e
annotated tag:                   v0.5.0

Real Windows release gate:
canonical discovery:             416 / 416 OK, skipped=1
plain discovery:                 416 / 416 OK, skipped=1
component focus:                  63 / 63 OK
responsive-layout focus:          14 / 14 OK
framework packaging focus:         5 / 5 OK
documentation/localization:       40 / 40 OK

Release artifacts:
standalone GUI:                  built/smoked
standalone CLI:                  built/smoked
portable ZIP:                    built/smoked
Inno Setup installer:            built/smoked
frozen CLI version:              SalixTorrent 0.5.0

Development workflow:
main:                            stable v0.5.0 release line
dev documentation checkpoint:   eb906e45f7b9f62403dc7887b36aae81a1818b6f
dev realtime/plot checkpoint:   ef8b4be998a714a86455940d8642fdd926a6609d
dev runtime/network checkpoint: 8e707efeb0cda162ee038a028a39a77663c2fa4e
previous pushed Windows dev gate: 591 / 591 OK, skipped=1
previous pushed dev checkpoint:   5cef12f534dfc44a8536f504d1aa7773644f5428
accepted Tranche-9 Windows gate:  602 / 602 OK, skipped=1
accepted Tranche-9 implementation: 5b54084f2d21dc331deb4614c15119ad94cab374
pushed Tranche-9 closure:        d939f6443a95490881925ca8bdb93e5e94f7ec2c
accepted Tranche-10 implementation: 3968bd2
accepted Tranche-10 closure:       df675e89bf025b570a339c7b3fb3c3518262d72a
accepted Tranche-10 Windows gate: 616 / 616 OK, skipped=1
accepted Tranche-11 baseline:     630 / 630 Windows, skipped=1; pushed as 79edec6
accepted Tranche-12 baseline:     643 / 643 Windows, skipped=1; local commit 688bcff, push pending
committed Tkinter/blank-app baseline: 516 / 516, Windows skipped=1
committed live-data/state-grid baseline: 529 / 529, Windows skipped=1
committed interactive-data baseline: 547 / 547, Windows skipped=1
committed command/mixed-layout baseline: 563 / 563, Windows skipped=1
committed structural-region baseline: 581 / 581, Windows skipped=1
committed designer-geometry baseline: 591 / 591, Windows skipped=1
accepted designer-metadata baseline: 602 / 602 Windows, skipped=1; display-less Linux preparation also passed 602 / 602 with expected GUI/platform skips
accepted designer-editing baseline: 616 / 616 Windows, skipped=1; display-less Linux preparation also passed 616 / 616 with expected GUI/platform skips
accepted designer-structure baseline: 630 / 630 Windows, skipped=1
accepted designer-preview baseline: 643 / 643 Windows, skipped=1; local commit 688bcff, push pending

Localization:
canonical catalog:               1337 entries
UI:                              695
Help:                            260
Glossary:                        382
extraction/manifests:            current
translation-memory parity:       432 / 432

Current session persistence:
snapshot version:                9
historical JSON versions:        1-8 accepted
SalixORM migration head:         session-state-0003
```

The v0.5.0 live/release smoke covered startup/navigation, repeated resizing, ordinary dialogs, Help/Glossary, clean shutdown, live Speed-history updates while seeding, standalone and portable launches, installer behavior, and frozen version identity.

Post-v0.5.0 development should preserve this release boundary while accounting explicitly for every intentional test-count or behavior change introduced on `dev`.
---

## 23. Tenth post-v0.5.0 implementation checkpoint — Windows validated

The tenth `dev` tranche adds the first explicit editing/history layer above the designer metadata snapshots accepted in Tranche 9. `app/framework/designer_editing.py` remains backend-neutral and standard-library-only. Its command objects transform immutable `DesignerSnapshot` values; they do not reach into Dear PyGui, Tkinter, SalixTorrent models or live `Component` instances.

`SetDesignerProperty` and `ClearDesignerProperty` validate edits against the type/property metadata embedded in the snapshot. `CompositeDesignerEdit` groups multiple property operations into one undo step. `DesignerPropertyState` exposes inspector-facing value/metadata state, including whether a value is explicitly present, while `DesignerPropertySpec.nullable` records properties for which explicit `None` is valid and therefore distinct from an absent inherited override.

`DesignerEditSession` owns current document state plus deterministic undo/redo stacks. New edits clear the redo branch, no-op edits create no history, `mark_clean()` defines a save/checkpoint boundary, and generic `CommandSet` entries expose undo/redo availability using stable semantic keys. History stores immutable whole snapshots in this provisional pass to prioritize correctness and easy recovery over delta compression.

The relocation gate now edits and undoes a copied/renamed framework snapshot, and the blank ecosystem application's existing component snapshot is edited in tests without mutating the live `Actions` button. This proves the editing boundary is document-oriented rather than an accidental toolkit mutation path.

The tranche also introduces tracked `validate_tranche.bat`, which runs the focused designer gates, component/Tkinter regressions, localization extraction, both complete discovery forms, headless proof, compileall and Git whitespace/status checks and writes one complete report to `%USERPROFILE%\Desktop\console_output.txt`. Visual GUI checks intentionally remain manual.

Preparation canonical discovery passes **616 / 616** on display-less Linux with 58 expected GUI/platform skips. After the Windows validator-launch repair and Tk/Tcl owner-thread lifecycle repair, both complete real-Windows discovery forms pass **616 / 616** with one expected skip; the one-command validator ends in `TRANCHE VALIDATION PASSED`, and manual Dear PyGui/Tkinter/SalixTorrent visual smoke passes. The accepted implementation commit is `3968bd2`. No version bump, tag, merge to `main`, public API freeze or final project schema is implied. Structural hierarchy editing/reparenting, copy/paste, live preview reconstruction/mutation and draggable designer handles remain later Stage-F work.

---

## 24. Eleventh post-v0.5.0 implementation checkpoint — accepted

The eleventh `dev` tranche adds structural document editing above the accepted property/history layer. Component type descriptors now include provisional child-slot metadata through `DesignerChildSlotSpec`, recording relationship names, cardinality, required metadata and sibling identity fields. This makes hierarchy mutation rules inspectable rather than burying them inside future editor widgets.

`app/framework/designer_structure.py` adds immutable insert/remove/reorder/reparent commands plus `DesignerNodeLocation`. The operations preserve node IDs and complete subtrees, reject root removal/reparenting and cycles, and validate each destination against parent metadata. Grid coordinates, tab-page keys, split-pane keys and fixed/anchored placement descriptors remain semantic relationship data rather than being converted to backend coordinates.

`DesignerEditSession` delegates structural operations through the same `execute(...)` path as property commands, so structural changes participate in deterministic undo/redo, redo invalidation and dirty-state tracking with no parallel history implementation. Snapshot JSON round-trips retain the structurally edited hierarchy.

The blank ecosystem application proves the boundary by reparenting its captured `Actions` node between positioned panels while the original live component hierarchy remains untouched. The copied/renamed framework proof also performs and undoes a structural insertion without importing SalixTorrent or a GUI toolkit.

Preparation advanced the complete suite from 616 to **630 tests**. The structural gate passed 14 / 14, combined designer/relocation focus passed 44 / 44, display-less canonical and plain discovery passed 630 / 630 with 58 expected skips, Xvfb canonical discovery passed 630 / 630 with 38 expected skips, and the Tkinter live backend remained 21 / 21. Real-Windows `validate_tranche.bat` then passed both complete discovery forms at **630 / 630** with one expected skip; manual Dear PyGui/Tkinter/SalixTorrent visual smoke and `pre_commit_check.bat` also passed. The tranche was committed and pushed as `79edec6` (`Add designer structural hierarchy editing`).

The accepted Tranche-10 base for this work is closure commit `df675e89bf025b570a339c7b3fb3c3518262d72a`; `APP_VERSION` remains `0.5.0`. No release tag, merge to `main`, live preview synchronization, drag/drop UI, copy/paste, persistent project schema or public API freeze is introduced.

---

## 25. Twelfth post-v0.5.0 implementation checkpoint — accepted and published

The twelfth `dev` tranche introduces the first deliberate reconstruction boundary from immutable designer documents back into executable framework components. `app/framework/designer_preview.py` remains standard-library-only and backend-neutral: it does not import Dear PyGui, Tkinter adapters, SalixTorrent views or application models.

`DesignerPreviewCatalog` maps provisional designer type keys to reconstruction builders. `DesignerPreviewContext` supplies only reusable layout coordination, while `DesignerPreviewBuild` owns the new root plus a stable mapping from every designer node ID to its reconstructed `Component`. `reconstruct_designer_snapshot(...)` first reports unsupported types before constructing any partial tree, then rebuilds children and parents through the registry. `DesignerPreviewBuild.recapture()` rebinds the original node IDs and produces a canonical snapshot of the reconstructed tree.

The initial framework preview registry covers the primitive controls and container/structure types used by the product-neutral blank application: labels/buttons/value controls, rows/columns/grids, sections/dialogs, placed/positioned containers, tab pages/tabs, split panels and generic labeled fields. Fixed/anchored placement metadata is restored through `placement_from_descriptor(...)`; grids remain semantic row/column relationships and require a dense rectangular shape for current runtime `ControlGrid`; tabs and split panes retain keys and sizing metadata.

Callbacks are intentionally not reconstructed. A preview button or value control is inert unless a later runtime/application layer explicitly binds behavior. The four specialized semantic-field composites (`field.labeled_combo`, `field.labeled_numeric`, `field.numeric_unit`, `field.duration`) are also intentionally reported as unsupported in this pass because their constructors synthesize internal children; supporting them should be based on an explicit semantic reconstruction contract rather than hidden object surgery. Custom preview catalogs can extend support without mutating the framework default.

`DemoView.reconstruct_designer_preview()` proves the real blank-application snapshot is fully supported and descriptor-round-trips with the same 31 designer IDs. Tests also edit a property and reparent a node through `DesignerEditSession`, reconstruct the edited document, and verify the original live component tree remains untouched. The framework relocation proof reconstructs/recaptures after package rename, and a real Tkinter/Xvfb regression builds the reconstructed blank hierarchy using an injected `LayoutCoordinator`.

Preparation advanced complete discovery from 630 to **643 tests**. Real-Windows acceptance then passed the 12 / 12 preview gate, 56 / 56 combined designer/relocation focus, 64 / 64 GUI-component regression and 22 / 22 Tkinter regression. Both complete discovery forms passed **643 / 643** with one expected skip, canonical localization remained 1,337/current, the one-command validator ended in `TRANCHE VALIDATION PASSED`, manual Dear PyGui/Tkinter/SalixTorrent visual regression smoke passed, and `pre_commit_check.bat` passed. The exact 12-file implementation boundary was committed locally as `688bcff` (`Add designer snapshot preview reconstruction`).

The Windows validator captured the published Tranche-11 base as `79edec6cb4531759992b4f7fdb2d63ac8f122907` for both `HEAD` and `origin/dev` before the Tranche-12 commit. Implementation `688bcff` and its documentation closure were subsequently published together at `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`. `APP_VERSION` remains `0.5.0`. This tranche does not add live preview synchronization, callback/service resolution, specialized semantic-field factories, copy/paste/duplicate, pointer-driven drag/drop/resize handles, project persistence/versioning or a public API freeze. The next narrow Stage-F candidate is preview rebuild/ownership semantics driven by the current `DesignerEditSession.snapshot`.
