# SalixTorrent Development Roadmap

**Current application version string:** `0.4.0`
**Roadmap status:** active development planning
**Current implementation checkpoint:** post-v0.4.0 reusable GUI/RAD extraction — renderer-neutral event/disposal tranche pushed/validated; first physical framework-boundary tranche implemented
**Current real Windows regression baseline:** 392 / 392 through the pushed renderer-neutral event/disposal tranche, with one expected non-Windows skip; first physical framework-boundary tranche targets 397

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

## Priority A — immediate

**Continue the reusable GUI/RAD extraction through proven application forms and renderer-adjacent behavior.**

First tranche — complete/pushed (`66b46fa7070128f13bc87fbe4f9556a86049e895`):

- [x] create a framework-owned `app/engine/components/` package;
- [x] add backend-neutral primitive Label, Button, ComboBox, NumericStepper, CheckBox and Spacer controls;
- [x] add semantic `AUTO` / `FILL` sizing rather than exposing Dear PyGui sizing sentinel values;
- [x] resolve width, height and row spacing through the existing default -> theme -> instance property cascade;
- [x] add generic `ControlRow`, `ControlColumn` and aligned `ControlGrid` composition;
- [x] add `LabeledComboField`, `LabeledNumericField` and three-part `DurationEditor` composites;
- [x] migrate Torrent Properties, `Configure targets...`, and Preferences seeding-goal controls without changing seeding-policy semantics;
- [x] add nine headless component/layout regressions;
- [x] regenerate deterministic localization extraction metadata without adding or changing canonical strings;
- [x] real Windows focused component/localization validation;
- [x] both full Windows discovery commands at 343/343 with one expected skip;
- [x] visual parity smoke for Torrent Properties, `Configure targets...`, and Preferences.

Second tranche — Preferences composition expansion — complete/pushed (`139931246280818694de1920b4b49c4e5cf734ca`):

- [x] add backend-neutral `TextInput`;
- [x] add generic `LabeledField` with one primary control plus zero-or-more trailing/accessory components;
- [x] make `LabeledComboField` and `LabeledNumericField` reuse the generic field contract;
- [x] add `NumericUnitField` for numeric-value + unit-selector rows;
- [x] migrate Preferences value controls and action rows while retaining existing item-id compatibility aliases;
- [x] add five additional headless component regressions (14 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] focused Windows component/localization validation;
- [x] both full Windows discovery commands at 348/348 with one expected skip;
- [x] visual/behavior smoke across Preferences before commit.

Third tranche — component layout profiles — complete/pushed (`f5e30e30012958429240bcf2646ac9a09d348de5`):

- [x] add backend-neutral `ComponentLayoutProfile` with named layout and aligned-grid column slots;
- [x] keep a framework profile with safe `AUTO` fallbacks and established composite defaults;
- [x] let the active renderer carry one application-selected profile;
- [x] select SalixTorrent's desktop profile once in `GuiEngine` rather than inside individual views;
- [x] preserve profile/default -> component theme -> explicit instance precedence;
- [x] move Preferences and seeding-goal component dimensions out of view construction into `ui_component_profile.py`;
- [x] retain explicit width overrides in the generic APIs for exceptional one-off layouts;
- [x] add six profile/layout regressions (20 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] run focused Windows component/localization validation;
- [x] run both full Windows discovery commands at 354/354 with one expected skip;
- [x] visually confirm Preferences, Torrent Properties and `Configure targets...` retain their established dimensions.

Fourth tranche — structural composition and attachment boundary — complete/pushed (`61d9d8424eecfbf3201d529d824fc68a85f079d5`):

- [x] add a backend-neutral `Separator` primitive;
- [x] add reusable `SectionPanel` and `Dialog` structural containers;
- [x] let `ControlRow` and `ControlColumn` expose context-managed incremental composition as well as declarative child builds;
- [x] add generic post-build component attachment hooks without importing SalixTorrent Help semantics into the reusable layer;
- [x] extend the Dear PyGui bridge with separator, panel/child-window and dialog/window rendering;
- [x] move the eight Preferences panel dimensions into the application component profile;
- [x] migrate Preferences root/pair/panel structure away from direct Dear PyGui group/child-window construction while retaining responsive item-id layout behavior;
- [x] migrate `Configure targets...` onto the reusable dialog boundary and profile-owned dialog dimensions;
- [x] add eight structural/attachment regressions (28 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] run focused Windows component/localization validation;
- [x] run both full Windows discovery commands at 362/362 with one expected skip;
- [x] visually confirm Preferences and `Configure targets...` retain their established structure and behavior;
- [x] commit/push as `61d9d8424eecfbf3201d529d824fc68a85f079d5` (`Add reusable structural GUI composition`).

Fifth tranche — Create Torrent form composition and tooltip renderer boundary — complete/pushed (`e11e05eb50238d540e798cbb689476afc302d939`):

- [x] add a backend-neutral `Tooltip` attachment that delegates backend tooltip creation through `ComponentRenderer`;
- [x] centralize Dear PyGui tooltip creation/failure isolation in the renderer while preserving existing Help helper compatibility;
- [x] add an application attachment adapter that turns SalixTorrent Help/Glossary terms into generic tooltip attachments;
- [x] add reusable `ProgressBar` and backend-neutral `TextInput` label support;
- [x] move Create Torrent panel/control dimensions into the application component profile;
- [x] migrate the complete Create Torrent form onto `ControlColumn`, `ControlRow`, `SectionPanel`, primitive/value components and generic attachments;
- [x] retain the existing raw item IDs consumed by background creation, state updates and `ResponsiveLayout`;
- [x] preserve exact user-facing strings, torrent-generation choices, callbacks and torrent-creation semantics;
- [x] add eight form/tooltip regressions (36 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] source-side component and focused localization/documentation validation;
- [x] run both real-Windows full discovery commands at 370/370 with one expected skip;
- [x] complete the real-Windows Create Torrent behavior/tooltips smoke before commit;
- [x] commit/push as `e11e05eb50238d540e798cbb689476afc302d939` (`Migrate Create Torrent to reusable GUI components`).

Sixth tranche — backend-neutral runtime state lifecycle — complete/pushed (`30fee9f65ba08f1563f8a0a0f1b43d34eb046297`):

- [x] add generic component `configure`, `exists`, `set_enabled` and `set_visible` helpers;
- [x] add `ComponentGroup` for coordinated runtime state transitions across already-built controls;
- [x] keep the contract renderer-neutral and avoid introducing an automatic observer/data-binding framework prematurely;
- [x] migrate Create Torrent runtime reads and updates from direct Dear PyGui calls to component objects;
- [x] preserve raw backend item IDs for `ResponsiveLayout` geometry compatibility only;
- [x] remove the direct Dear PyGui import from `create_torrent_view.py`;
- [x] add four runtime-state regressions (40 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] source-side component and focused localization/documentation validation;
- [x] run both real-Windows full discovery commands at 374/374 with one expected skip;
- [x] smoke Create Torrent source/output selection, busy/cancel transitions, progress/status updates and Start Seeding show/enable transitions;
- [x] commit/push as `30fee9f65ba08f1563f8a0a0f1b43d34eb046297` (`Add backend-neutral component runtime state`).

Seventh tranche — transfer utility dialogs and second runtime-state proof — complete/pushed (`3ee3982687810f709ab0a34312e8e8b73d47324e`):

- [x] add backend-neutral `Dialog` minimum-size and renderer-driven centering support;
- [x] add `ProgressBar.set_overlay(...)` through the component runtime configuration boundary;
- [x] migrate Open Magnet construction onto reusable dialog/row/input/button/progress/label components and application tooltip attachments;
- [x] migrate Open Magnet input, progress, status, Add/Cancel and dialog visibility transitions onto component runtime APIs;
- [x] preserve clipboard acquisition and responsive geometry services as separate application/backend concerns rather than forcing them into value binding;
- [x] migrate Remove Torrent, Removal Notice, Force Recheck and Download Complete onto reusable dialog/control/profile structures;
- [x] centralize magnet/remove/recheck/completion dialog dimensions in the SalixTorrent component profile;
- [x] preserve removal safety, force-recheck behavior, completion/seeding-goal notifications, BEP-9 cancellation and auto-close semantics;
- [x] add six additional component/dialog regressions (46 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] source-side component and focused localization/documentation validation;
- [x] run both real-Windows full discovery commands at 380/380 with one expected skip;
- [x] smoke Open Magnet add/cancel/auto-close plus remove/recheck/completion utility-dialog behavior;
- [x] commit/push as `3ee3982687810f709ab0a34312e8e8b73d47324e` (`Migrate transfer dialogs to reusable GUI components`).

Eighth tranche — explicit synchronous value binding and Preferences runtime migration — complete/pushed (`665faab`):

- [x] add backend-neutral `ValueBinding` and `BindingSet` contracts for named value synchronization;
- [x] support explicit read/write transforms and per-binding defaults without implicit observers or background mutation;
- [x] migrate Preferences ordinary settings collection/synchronization onto the binding contract;
- [x] keep multi-control seeding-duration composition explicit rather than hiding it behind a fake one-control binding;
- [x] move network-interface refresh and Preferences status/connectivity updates onto component APIs;
- [x] replace remaining Preferences raw text/spacer construction with reusable components;
- [x] remove the direct Dear PyGui import/calls from `settings_view.py`;
- [x] keep Tk/native folder selection, networking services and `ResponsiveLayout` geometry as separate application concerns;
- [x] preserve settings persistence, localization/canonical-choice conversion, seeding-goal bulk apply and user-facing strings;
- [x] add five binding/runtime regressions (51 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] source-side component and focused localization/documentation validation;
- [x] run both real-Windows full discovery commands at 385/385 with one expected skip;
- [x] smoke Preferences load/save/restore, interface refresh, connectivity status, folder chooser, limits, desktop toggles and seeding defaults;
- [x] commit/push as `665faab` (`Add explicit component value bindings`).

Ninth tranche — renderer-neutral events and explicit disposal ownership — complete/pushed (`447c6296c37c288384345bebef220ac1e2901c22`):

- [x] add immutable `ComponentEvent` metadata with semantic `ACTIVATE` and `CHANGE` event types;
- [x] keep backend callback arguments inside the renderer bridge instead of exposing Dear PyGui sender/app-data/user-data conventions to reusable controls;
- [x] replace reusable-control `user_data` with explicit backend-neutral `event_data`;
- [x] add `action_callback(...)` for deliberate adaptation of existing no-argument application actions;
- [x] propagate event metadata through labeled/composite value fields without adding observer/reactive behavior;
- [x] add renderer-owned `destroy(...)` and explicit idempotent `Component.dispose()` lifecycle ownership;
- [x] reject stale rendered handles through `require_item()` while allowing an explicitly rebuilt component to bind a fresh item;
- [x] migrate callbacks for Create Torrent, Preferences and the already-componentized transfer utility dialogs through the event adapter;
- [x] leave queue tables, context menus, high-frequency telemetry, native dialogs, networking services and responsive geometry at their existing application/backend boundaries;
- [x] add seven event/lifecycle regressions (58 component tests total);
- [x] regenerate deterministic localization extraction metadata with no canonical string changes;
- [x] source-side component and focused localization/documentation validation;
- [x] run both real-Windows full discovery commands at 392/392 with one expected skip;
- [x] smoke Create Torrent, Preferences, Open Magnet, remove/recheck/completion dialog button actions and ordinary close/cancel paths;
- [x] commit/push as `447c6296c37c288384345bebef220ac1e2901c22` (`Add renderer-neutral component events and disposal`).

Tenth tranche — first physical framework boundary — complete/pushed (`bfc0e7a4fd5a49234425980c4dd5ce04f6f5a10f`):

- [x] create a provisional internal `app/framework/` namespace without choosing the eventual external framework name;
- [x] move the reusable property cascade and component implementations into that physical boundary;
- [x] retain `app/engine/components/` and `app/engine/property_cascade.py` as temporary compatibility facades rather than breaking established imports during extraction;
- [x] migrate SalixTorrent views, component profile/attachment adapters, documentation layout and component tests onto the new framework-facing imports;
- [x] split concrete `DearPyGuiRenderer` implementation into `app/engine/component_renderers/` so the framework candidate does not import the desktop backend;
- [x] replace hidden renderer selection with explicit `set_default_renderer(...)`, `get_default_renderer()` and `clear_default_renderer(...)` ownership;
- [x] make `GuiEngine` construct, install, profile and clear the Dear PyGui renderer at the application composition root;
- [x] add a source-level extraction audit rejecting engine/view/logic/localization/Dear PyGui imports from framework-candidate modules;
- [x] preserve explicit bindings/events/disposal and avoid observers, automatic lifecycle management, or cosmetic table/graph wrapping;
- [x] add five net component regressions (63 component tests total);
- [x] preserve canonical UI/Help/Glossary wording and application/session persistence schemas;
- [x] run focused real-Windows component/documentation/localization validation;
- [x] run both real-Windows full discovery commands at 397/397 with one expected skip;
- [x] smoke startup plus Create Torrent, Preferences, Open Magnet, utility-dialog actions, Help/Glossary tooltips and ordinary shutdown;
- [x] commit/push as `bfc0e7a4fd5a49234425980c4dd5ce04f6f5a10f` (`Extract reusable GUI framework boundary`).

Eleventh tranche — framework documentation and pure geometry boundary — implementation complete:

- [x] extract pure geometry contracts from the Dear PyGui `ResponsiveLayout` dispatcher into `app/framework/geometry.py`;
- [x] keep `app.engine.responsive_layout` as the concrete resize/event adapter and compatibility re-export boundary;
- [x] move semantic documentation model, layout policy/cascade and typography/theme contracts into `app/framework/documentation/`;
- [x] retain the concrete Dear PyGui `DocumentationRenderer` under `app/engine/documentation/renderer.py`;
- [x] keep runtime-resource lookup, media cache, SalixTorrent `UiTypography`, resize watching and Dear PyGui ownership outside the reusable documentation contracts;
- [x] retain engine documentation model/layout/typography paths as compatibility facades during extraction;
- [x] migrate Help/Preferences and presentation tests onto framework-facing documentation/geometry imports where they consume reusable contracts;
- [x] extend extraction audits to reject product/backend dependencies from framework documentation/geometry modules;
- [x] add six documentation/framework-boundary regressions (23 documentation tests; 40 focused documentation/localization tests);
- [x] regenerate deterministic localization extraction metadata with canonical wording unchanged at 1,337 entries;
- [x] source-side component, responsive-layout and focused documentation/localization validation;
- [ ] run both real-Windows full discovery commands and account for the expected 397 -> 403 test-count increase;
- [ ] smoke Help Topics/Glossary at normal/maximized/resized layouts, documentation scale changes, Preferences documentation-scale persistence, and ordinary GUI shutdown.

## Priority B — user-facing durability

1. safe data relocation;
2. labels/categories;
3. watch folder;
4. additional transfer-lifecycle polish discovered during seeding-goal mileage.

## Priority C — privacy/network transport

1. SOCKS5 proxy policy;
2. uTP/BEP 29;
3. WebSeed support.

## Priority D — release/content

1. complete target locale population/review;
2. Windows frozen/portable/installer localization smoke;
3. Linux/BSD/macOS native desktop smoke;
4. choose next release scope.

## Priority E — later automation

1. local supervisory API/service mode;
2. scheduling/rules;
3. documentation timed media/layout inspector.

---

# 14. Possible release themes

Version numbers below are planning examples, not commitments.

## Current engineering checkpoint

```text
v0.4.0 — durability and transfer lifecycle
```

The v0.4.0 release consolidates the completed persistence, tracked-test, localization-foundation, and seeding-goal milestones behind the current `0.4.0` application version.

## v0.4.0 release theme

```text
Durability and transfer lifecycle
```

Included release pillars:

- stable backend-neutral application/session persistence;
- tracked regression-suite ownership;
- offline-first localization/framework foundations;
- durable per-torrent seeding goals and automatic-stop policy.

## Post-v0.4.0 GUI-framework direction

The first component tranche is now implemented in source. It introduces a backend-neutral component model with a Dear PyGui renderer bridge, primitive controls, semantic sizing, and reusable composition objects.

Current component hierarchy:

```text
Primitive controls
    Label
    Button
    ComboBox
    TextInput
    NumericStepper
    CheckBox
    ProgressBar
    Separator
    Spacer
        |
        v
Layout / structural composition
    ControlRow
    ControlColumn
    ControlGrid
    SectionPanel
    Dialog
        |
        v
Field composition
    LabeledField
        primary control + 0..n accessories
    LabeledComboField
    LabeledNumericField
    NumericUnitField
    DurationEditor

Cross-cutting component hooks
    post-build attachments
        -> Tooltip
        -> application-owned Help/Glossary/accessibility/diagnostic semantics
```

`ControlRow` is the generic single-row-capacity composition primitive: it accepts an arbitrary number of child components and resolves width, height and horizontal spacing independently through the existing framework property cascade. `AUTO` and `FILL` are semantic framework sizes; Dear PyGui-specific values are translated only inside the renderer bridge.

The first live migration deliberately targeted the already-polished seeding-goal controls and is now Windows-validated:

- Torrent Properties uses one dense `ControlRow` containing the existing goal-mode, ratio and D/H/M primitives;
- `Configure targets...` uses labeled combo/numeric composites plus `DurationEditor`;
- Preferences new-torrent defaults use the same semantic composites and duration editor.

The second tranche broadens the same contract across Preferences. `LabeledField` provides the generic row shape for a label, one primary control and arbitrary trailing accessories; `NumericUnitField` is a convenience built on that contract rather than a parallel layout system. Preferences no longer constructs input/combo/checkbox value controls directly through Dear PyGui, while its surrounding panel/child-window structure remains intentionally application-specific. Existing raw item-id aliases are retained temporarily so persistence, refresh, tooltips and save/restore logic continue through their proven boundaries.

The third tranche introduces renderer-selected `ComponentLayoutProfile` policy. Framework components select semantic profile slots for layout defaults; SalixTorrent's application profile centralizes the exact established Preferences and seeding-goal dimensions in one place. Missing slots fall back safely to framework `AUTO` sizing, sparse `ControlLayoutTheme` values remain the theme layer, and `ControlLayout` stays the explicit per-instance override. `DurationEditor` also resolves its aligned grid/input/column metrics from profile slots, so views no longer need to repeat those numbers. The tranche is now committed/pushed and Windows-validated at 354/354 with visual parity confirmed.

The fourth tranche extends the reusable layer upward into structural composition without wrapping complex tables or telemetry views cosmetically. `SectionPanel` owns child-window/panel sizing, heading and separator structure; `Dialog` owns window/dialog construction and semantic profile sizing; `ControlRow` and `ControlColumn` support context-managed incremental migration where existing view logic still needs imperative construction. Preferences now uses those structural boundaries instead of direct Dear PyGui groups/child windows, and `Configure targets...` uses the reusable dialog boundary. The same tranche adds a generic post-build attachment hook so future tooltip/accessibility metadata can attach to components without embedding SalixTorrent-specific Help semantics in the framework.

The fifth tranche proves those contracts on a complete ordinary form. Create Torrent now uses framework-owned rows, panels, value controls and profile dimensions throughout its construction path, including a reusable `ProgressBar`. Generic `Tooltip` attachments call the active renderer rather than Dear PyGui directly, while a SalixTorrent adapter converts glossary/help terms into tooltip text.

The sixth tranche separates runtime component state from Dear PyGui as well. Generic components can now configure their rendered item, query existence, toggle enabled/visible state, and coordinate those transitions through `ComponentGroup`. Create Torrent uses component value/state APIs for its entire runtime workflow, while raw backend IDs remain only where the established `ResponsiveLayout` geometry service still requires them. This is intentionally a small lifecycle contract derived from proven duplication, not an automatic observer/data-binding subsystem.

The seventh tranche proves that lifecycle on a second independent workflow and broadens ordinary dialog reuse. Open Magnet now uses component-owned input/progress/status/button state, including progress overlay updates and dialog visibility, while `Dialog` itself can express minimum size and delegate viewport centering through the renderer. Remove Torrent, Removal Notice, Force Recheck and Download Complete use the same reusable dialog/control/profile boundary, leaving tables, row popups and high-frequency telemetry deliberately untouched. It is committed/pushed and Windows-validated at 380/380.

The eighth tranche adds the minimal explicit synchronization contract justified by the duplicated form/settings code: `ValueBinding` maps one named application value to one `ValueComponent`, with explicit presentation/model transforms and defaults, while `BindingSet` collects or applies those bindings only when application code calls it. Preferences now uses that contract for ordinary persisted values and component APIs for status/connectivity updates, eliminating direct Dear PyGui usage from `settings_view.py`. This remains intentionally synchronous rather than observer/reactive, and is pushed/Windows-validated at 385/385.

The ninth tranche formalizes the two renderer-adjacent boundaries exposed by that extraction. Reusable controls now emit immutable `ComponentEvent` objects with semantic `ACTIVATE`/`CHANGE` types and explicit application `event_data`; backend callback tuple conventions stay inside `ComponentRenderer`. Existing command-style view actions are adapted deliberately through `action_callback(...)` rather than relying on renderer argument quirks. In parallel, rendered lifetime gains explicit renderer-owned `destroy(...)` and idempotent `Component.dispose()` semantics, with stale backend handles rejected before state/value operations. No observer system, automatic teardown manager, or application-service ownership is introduced. It is pushed/Windows-validated at 392/392 under `447c6296c37c288384345bebef220ac1e2901c22`.

The tenth tranche begins the first physical extraction without freezing final framework naming. Reusable property-cascade and component implementations move under the provisional internal `app.framework` boundary, while the old engine paths remain temporary compatibility facades. Dear PyGui becomes a concrete engine/backend adapter rather than part of the framework core, and `GuiEngine` explicitly installs/clears that renderer at the composition root. A source audit enforces that framework-candidate modules do not import SalixTorrent engine/view/logic/localization layers or Dear PyGui. It is pushed/Windows-validated at 397/397 under `bfc0e7a4fd5a49234425980c4dd5ce04f6f5a10f`.

The eleventh tranche proves that physical boundary with a second independent reusable subsystem. Pure alignment/content/split/fill/dialog geometry moves to `app.framework.geometry`, while the Dear PyGui `ResponsiveLayout` dispatcher remains an engine adapter. Semantic documentation model/layout/typography contracts move to `app.framework.documentation`; the concrete `DocumentationRenderer` deliberately remains in the engine because it owns Dear PyGui, resource paths, application typography, media and resize callbacks. Compatibility facades preserve the former engine documentation import paths during extraction. It is pushed/Windows-validated at 403/403 under `1f70669678b3621718467b60e2fcb94aa8e77642`.

The twelfth tranche proves package relocation ergonomics before any external repository split. All dependencies inside `app/framework/` now use package-relative imports, so the framework tree does not hard-code SalixTorrent's `app.framework` namespace internally. A packaging regression copies that directory to a temporary package named `portable_framework`, imports every module under Python isolated mode, and confirms that neither SalixTorrent's `app` package nor Dear PyGui is loaded. A second probe exercises representative component, documentation, geometry and property-cascade contracts from the renamed package, while a source audit restricts absolute framework dependencies to the Python standard library. The provisional framework root intentionally does not publish a version or wildcard public surface yet. Dear PyGui resize callback/handler ownership remains in the engine adapter because no second backend has proven that state reusable.

Names such as `components`, `SectionPanel`, `Dialog`, and profile identifiers remain working extraction names. Final RAD-framework naming and public API terminology are deliberately deferred until the full reusable boundary has been extracted and proven.

### Possible v0.5.0 theme

```text
Reusable GUI component foundation
```

Candidate follow-up work after the package-relocation boundary validates:

- inspect whether a small backend-neutral resize/callback coordination contract is genuinely shared before moving any remaining `ResponsiveLayout` state out of the Dear PyGui adapter;
- prove the explicit binding or event contract on another ordinary persisted/editable surface only when it removes real duplication;
- migrate only additional ordinary dialogs/forms where the current contracts remove real application code rather than creating cosmetic wrappers;
- define the eventual host/backend adapter packaging boundary before an external repository split, while keeping the current package name and public API provisional;
- keep application services such as clipboard, native file dialogs, networking and backend-specific resize handlers outside component ownership unless a broader reusable contract is proven;
- continue using application-owned adapters for Help/Glossary/accessibility semantics while keeping generic attachments product-neutral;
- avoid converting complex tables/graphs merely for cosmetic uniformity;
- postpone the final framework naming/API pass until the full RAD extraction boundary is visible.

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
Current real Windows feature validation:
seeding policy: 14 / 14 OK
application settings persistence: 12 / 12 OK
session persistence: 34 / 34 OK
semantic-documentation + localization-UI focus: 17 / 17 OK

Full canonical discovery:
392 / 392 OK
1 expected non-Windows skip

Plain repository-root discovery:
392 / 392 OK
1 expected non-Windows skip

Localization:
canonical catalog: 1337 entries
UI: 695
Help: 260
Glossary: 382
extraction/manifests: current
pseudo locale: OK
offline validation: OK with expected incomplete-target warnings
translation-memory parity: 432 / 432

Current session persistence:
snapshot version 9
historical JSON versions 1-8 accepted
SalixORM migration head session-state-0003
historical SalixORM v7/v8 upgrades covered by regression

Previous live SalixORM session smoke (pre-v8):
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

The v0.4.0 release baseline remains 334/334 tests with one expected non-Windows skip. The first GUI-component tranche is committed/pushed at `66b46fa7070128f13bc87fbe4f9556a86049e895` and passed 343/343 on the real Windows checkout. The second Preferences-composition tranche is committed/pushed at `139931246280818694de1920b4b49c4e5cf734ca` and passed 348/348. The third component-profile tranche is committed/pushed at `f5e30e30012958429240bcf2646ac9a09d348de5` and passed 354/354. The fourth structural tranche is committed/pushed at `61d9d8424eecfbf3201d529d824fc68a85f079d5` and passed 362/362. The Create Torrent form/tooltip tranche is committed/pushed at `e11e05eb50238d540e798cbb689476afc302d939` and passed 370/370 on the real Windows checkout. The runtime-state tranche is committed/pushed at `30fee9f65ba08f1563f8a0a0f1b43d34eb046297` and passed 374/374. The transfer-dialog tranche is committed/pushed at `3ee3982687810f709ab0a34312e8e8b73d47324e` and passed 380/380. The explicit Preferences-binding tranche is committed/pushed at `665faab` and passed 385/385. The renderer-neutral event/disposal tranche is committed/pushed at `447c6296c37c288384345bebef220ac1e2901c22` and passed 392/392. The first physical framework-boundary tranche is committed/pushed at `bfc0e7a4fd5a49234425980c4dd5ce04f6f5a10f` and passed 397/397 on Windows. The documentation/geometry extraction tranche adds six regressions for an expected 403-test Windows gate; focused documentation/localization is 40/40 source-side and deterministic localization extraction remains current.

The v0.4.0 live GUI smoke covers per-torrent editing, additive Days/Hours/Minutes quick controls, explicit bulk Preferences application, persistence, in-app/native notifications, instanced time-based automatic stop, Days/Hours/Minutes exact editors, stacked compact duration controls, and the widened Preferences ratio field. Ratio-threshold behavior remains covered by deterministic regressions without requiring a second live peer. Future changes must preserve the applicable baseline or account explicitly for every intentional test-count change.
