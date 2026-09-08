# SalixTorrent Development Roadmap

**Current application version string:** `0.5.0`
**Roadmap status:** v0.5.0 released; post-v0.5.0 ecosystem extraction on `dev`
**Current implementation checkpoint:** structural tabs, split regions and overlays are Windows-validated and pushed on `dev` at `731303d847a46c1e7e250d34d8b78a9e51f485ef`; prepared Tranche 8 begins designer geometry with parent-local anchors, size constraints, serializable placement descriptors and split-pane maximums
**Current real Windows regression baseline:** 581 / 581 at the pushed structural-region checkpoint with one expected non-Windows shell-behavior skip; Tranche 8 initially passed 589 / 589 on Windows, then received two acceptance repairs and now has a 591-test prepared gate awaiting final Windows visual recheck

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

### A10. WYSIWYG designer prerequisites — first geometry tranche prepared

The first designer-preparation tranche extends the proven mixed-layout runtime without introducing a complete designer model:

- `AxisAnchor` provides start / centre / end / stretch semantics on each parent-local axis;
- `AnchoredPlacement` and `AnchoredChild` resolve against the current `PositionedPanel` content rectangle and reflow through `LayoutCoordinator`;
- `SizeConstraints` provides reusable minimum/maximum width and height bounds;
- fixed and anchored placement metadata round-trips through JSON-safe descriptors without importing a GUI toolkit;
- `SplitPane.maximum` plus `split_sizes(..., maximums=...)` adds richer structural constraints while preserving historical behavior when maximums are omitted;
- Help proves a real application use by capping the index/navigation pane at 480 px on ultrawide layouts;
- the blank ecosystem application proves anchored start/end/stretch geometry and constrained responsive sizing through the shared GUI contracts.

Initial prepared canonical discovery advanced from **581 to 589 tests**. Real-Windows validation passed both 589-test discovery forms with the expected single skip, but live acceptance exposed two pre-commit issues: the Diagnostics menu still referenced a removed private UI-error-log helper, and the product-neutral blank application's fixed-position proof could clip inside its left split pane at narrower supported widths. Both are repaired in the tranche: the diagnostics path now uses a public engine contract and the blank demo's minimum/composition geometry is internally consistent. Regression coverage is now **591 tests**; display-less Linux canonical discovery passes 591 / 591 with expected GUI skips. Canonical localization remains 1,337 strings. Final Dear PyGui/Tkinter visual recheck remains required before commit/push.

This tranche intentionally stops before a full designer document model. Still deferred:

- component/type registry and property metadata;
- serializable component hierarchy and stable designer object identity;
- command-based mutations and undo/redo;
- copy/paste and drag/drop/reparent operations;
- percentages and richer relationship constraints;
- interactive split/resize handles;
- project document/schema and preview/runtime bridge.

The future designer should itself use the same engine/framework wherever practical.

### A11. Naming, public API and package/repository split

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
current pushed Windows dev gate: 581 / 581 OK, skipped=1
current pushed dev checkpoint:   731303d847a46c1e7e250d34d8b78a9e51f485ef
dev:                             tracks origin/dev before applying prepared Tranche 8
committed Tkinter/blank-app baseline: 516 / 516, Windows skipped=1
committed live-data/state-grid baseline: 529 / 529, Windows skipped=1
committed interactive-data baseline: 547 / 547, Windows skipped=1
committed command/mixed-layout baseline: 563 / 563, Windows skipped=1
committed structural-region baseline: 581 / 581, Windows skipped=1
prepared designer-geometry baseline: 591 / 591 canonical Linux after Windows acceptance repairs; final Windows visual recheck pending

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
