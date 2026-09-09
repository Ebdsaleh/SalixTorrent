# Changelog

Notable SalixTorrent changes are recorded here.

## Unreleased

### Ecosystem Extraction — Designer Copy / Paste / Duplicate Documents

- Added standard-library-only `app/framework/designer_clipboard.py` in the optional designer/tooling layer. `DesignerClipboardPayload` captures one immutable subtree plus its source relationship context; no operating-system clipboard, GUI toolkit, application service or project persistence dependency is introduced.
- Added deterministic preorder subtree cloning through `remap_designer_subtree_ids(...)`. Fresh IDs use `<source>-copy`, then `-2`, `-3` and so on as required by the target document, and `DesignerSubtreeClone` exposes the complete source-ID -> cloned-ID map for future selection/editor tooling.
- Added `PasteDesignerSubtree` and `DuplicateDesignerNode`. Both reuse Tranche-11 structural validation, so pasted/duplicated content still obeys parent slots, cardinality, grid coordinates, tab/split identities and fixed/anchored placement descriptors rather than bypassing those contracts. Source relationship metadata is preserved by default and can be replaced explicitly when a unique destination relationship is required.
- Extended `DesignerEditSession` with ephemeral clipboard state plus `copy_node()`, `paste()`, `duplicate_node()` and `clear_clipboard()`. Copying alone does not dirty the document or touch history; paste/duplicate use the same immutable undo/redo stack as property and structural edits. Explicit payload transfer between compatible sessions is supported without defining a persistent clipboard/project schema.
- Extended `DesignerPreviewHost` with the same optional copy/paste/duplicate surface. Copy does not rebuild a preview; paste/duplicate execute through the existing checked transaction gate, so a replacement preview must reconstruct/build successfully before document history advances.
- Added a real Tkinter proof where duplicating the blank application's captured `Actions` button through the preview host disposes the previous rendered preview only after the replacement succeeds, exposes the fresh designer ID, and undo reconstructs a tree without the duplicate. The original code-first application hierarchy remains unchanged.
- Expanded copied/renamed framework packaging proof to import and execute clipboard capture/paste through the relocatable package. Tranche validation now expects 12 clipboard tests, 79 combined designer/relocation tests, 24 Tkinter tests and **668** complete-discovery tests.
- Tranche 13 and its documentation closure are now published together at `4b0968bfdf91ce040eeefd641b1e315244a325e6`; `HEAD` and `origin/dev` matched at that checkpoint with a clean tree before this tranche.
- Real-Windows Tranche-14 acceptance passed 12 / 12 clipboard tests, 79 / 79 designer/relocation tests, 64 / 64 GUI-component tests, 24 / 24 Tkinter tests and both complete **668 / 668** discovery forms with one expected skip. Localization, headless/compileall/Git checks, manual Dear PyGui/Tkinter/SalixTorrent smoke and `pre_commit_check.bat` also passed; the accepted implementation commit is `450c12a` (`Add designer copy paste and duplicate commands`), with only the documentation closure and push still pending.
- This tranche deliberately stops before operating-system clipboard integration, cut semantics, multi-selection/group copy, pointer-driven drag/drop/resize handles, incremental in-place toolkit mutation, callback/service serialization, project persistence/schema or final ecosystem/package API freeze.

### Ecosystem Extraction — Transactional Designer Preview Ownership

- Added standard-library-only `app/framework/designer_preview_host.py` as an optional tooling layer above code-first framework composition. `DesignerPreviewHost` owns one reconstructed preview for a `DesignerEditSession`; ordinary applications can continue to create and compose `Component` objects directly without importing designer modules.
- Preview replacement is whole-tree and transactional. A candidate snapshot is reconstructed first and, when a renderer is supplied, built before the currently accepted preview is disposed. Candidate failures are cleaned up and do not advance document/history state.
- Extended `DesignerEditSession` with generic checked execute/undo/redo gates. Validation callbacks run against prospective immutable snapshots before session/history mutation, allowing preview preparation (and later project/schema validation) without introducing a dependency from the editing core to renderer/toolkit code.
- Host-mediated property edits, structural edits, undo and redo keep the current immutable designer document and preview generation aligned. External session changes remain supported through explicit `sync()`, and stable designer node IDs continue to resolve reconstructed components after each replacement.
- Added a real Tkinter replacement proof: an accepted reconstructed blank-app preview is rendered, a document property edit builds a replacement tree, the old rendered root becomes stale/disposed only after the replacement succeeds, and undo builds another accepted preview.
- Expanded copied/renamed framework packaging proof to use the preview host without SalixTorrent or Dear PyGui. Tranche validation now expects 11 preview-host tests, 67 combined designer/relocation tests, 23 Tkinter tests and **655** complete-discovery tests.
- Clarified the ecosystem's dual-entry construction policy: visual RAD tooling is an additional authoring path over the same semantic components/runtime/backends, not a requirement for applications. SalixTorrent remains the primary code-first reference application.
- Real-Windows validation exposed a pre-existing persistence-test lifetime race rather than a preview-host regression: `test_running_manager_bulk_apply_uses_command_boundary_and_emits_updates` allowed its async `TorrentManager` to outlive the `TemporaryDirectory` that backed its state. The test now shuts the manager down in a `finally` block before the temporary directory is removed and clears the singleton so unittest teardown cannot restart persistence against a deleted path. This keeps the full-suite gate strict instead of retrying or ignoring Windows `WinError 145` cleanup failures.
- Real-Windows acceptance then completed on the repaired boundary: preview ownership passed 11 / 11, designer/relocation focus 67 / 67, GUI components 64 / 64 and Tkinter 23 / 23; both complete discovery forms passed **655 / 655** with one expected skip, canonical localization remained 1,337/current, headless/compileall/Git checks passed, manual Dear PyGui/Tkinter/SalixTorrent smoke passed, and `pre_commit_check.bat` passed. The accepted implementation is `ddfb3ef2269acb33484cd6fe2f99af47fa40140f` (`Add transactional designer preview ownership`); its Windows-acceptance documentation closure was then published with it at `4b0968bfdf91ce040eeefd641b1e315244a325e6`.
- This tranche deliberately stopped before incremental in-place toolkit synchronization, callback/service serialization, specialized semantic-field factories, project persistence/schema, pointer-driven drag/drop/resize handles or final ecosystem/package API freeze. Document-level copy/paste/duplicate follows in Tranche 14.

### Ecosystem Extraction — Designer Snapshot Preview Reconstruction

- Added standard-library-only `app/framework/designer_preview.py` as the first explicit document-to-runtime preview bridge. `DesignerPreviewCatalog` maps provisional type keys to backend-neutral builders, `DesignerPreviewContext` injects only reusable layout coordination, and `DesignerPreviewBuild` exposes the reconstructed root plus a stable designer-node-ID to `Component` mapping. No GUI toolkit or SalixTorrent product module is imported by the bridge.
- Reconstructs the primitive/layout types used by the product-neutral blank application: labels/buttons/value controls, rows/columns/grids, sections/dialogs, placed/positioned containers, tab pages/tabs, split panels and generic labeled fields. Fixed and anchored placement descriptors are restored through the existing geometry parser; grid cells, tab keys and split-pane metadata remain semantic relationships rather than backend coordinates.
- Preserves source designer IDs across reconstruction and can recapture the rebuilt tree through `DesignerPreviewBuild.recapture()`. Runtime-captured blank-application snapshots round-trip descriptor-for-descriptor, while sparse hand-authored nodes are allowed to materialize ordinary constructor defaults on canonical recapture.
- Preview callbacks are intentionally inert: buttons, value controls and tabs are reconstructed without application callbacks or bindings. Unsupported specialized semantic-field types are reported before partial reconstruction through `DesignerPreviewUnsupportedTypeError`, and custom preview catalogs can extend support without mutating the framework registry.
- The blank ecosystem application now exposes `reconstruct_designer_preview()` over its existing captured hierarchy. Focused tests prove property edits plus structural reparenting feed the preview bridge while the original live component tree remains unchanged. A real Tkinter/Xvfb regression builds the reconstructed blank snapshot through the existing renderer with an injected `LayoutCoordinator`.
- Expanded the relocation proof so a copied/renamed framework reconstructs and recaptures a preview without importing SalixTorrent or Dear PyGui. Tranche validation now expects 12 preview tests, 56 combined designer/relocation tests, 22 Tkinter tests and **643** complete-discovery tests.
- Real-Windows acceptance completed for this tranche: the preview gate passed 12 / 12, designer/relocation focus 56 / 56, GUI components 64 / 64 and Tkinter 22 / 22; both complete discovery forms passed **643 / 643** with one expected skip, canonical localization remained 1,337/current, manual Dear PyGui/Tkinter/SalixTorrent smoke passed, and `pre_commit_check.bat` passed. The accepted implementation `688bcff` and its Windows-acceptance documentation closure were published together on `dev`, whose resulting checkpoint is `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`.
- Tranche 11 Windows acceptance completed before this work: both complete discovery forms passed **630 / 630** with one expected skip, manual visual smoke passed, pre-commit passed, and `79edec6` was pushed to `dev`.
- This tranche deliberately stops before live preview synchronization/replacement, application callback resolution, specialized semantic-field factories, copy/paste/duplicate commands, pointer-driven drag/drop/resize handles, persisted undo history, a final project schema or final ecosystem/package API freeze.

### Ecosystem Extraction — Designer Structural Hierarchy Commands

- Added provisional `DesignerChildSlotSpec` metadata to the component catalog so a future hierarchy editor can inspect which child relationships a container supports, whether a slot is single or repeated, which relationship metadata is required, and which metadata fields identify a unique sibling location. Existing captures now describe linear children, grid cells, placed/positioned children, tab pages, split panes and composite-field slots explicitly.
- Added standard-library-only `app/framework/designer_structure.py` with immutable `InsertDesignerChild`, `RemoveDesignerNode`, `MoveDesignerNode` and `ReparentDesignerNode` commands plus `DesignerNodeLocation` / `locate_designer_node(...)`. Commands preserve stable subtree IDs, reject root removal/reparenting, cycles, reused IDs, unknown types, illegal slots, missing placement/cell/page/pane metadata and duplicate relationship identities.
- Structural validation keeps container-local semantics intact: grid row/column locations must be non-negative and unique, tab page keys remain semantic and consistent with tab-page nodes, split-pane keys remain unique, and placed/positioned children reuse the validated fixed/anchored placement descriptors rather than flattening geometry.
- Extended `DesignerEditSession` with location/insert/remove/move/reparent helpers. Structural commands use the same immutable whole-snapshot history, dirty tracking, undo/redo stacks and generic command availability as property edits; no parallel designer-only history system is introduced.
- Expanded the relocation proof so a copied/renamed framework can insert and undo a structural child without SalixTorrent or a GUI toolkit. The blank-application regression reparents the real captured `Actions` node between positioned containers and proves the original live component hierarchy is untouched.
- Updated tracked tranche validation to report both local `HEAD` and `origin/dev`, run the new structural hierarchy gate, and expect **630 tests** for complete discovery. Preparation passed 14 / 14 structural tests, 44 / 44 designer/relocation tests, 21 / 21 real Tkinter tests under Xvfb, and both complete Linux discovery forms at 630 / 630; canonical localization remained 1,337 strings. Real-Windows acceptance then passed both complete discovery forms at 630 / 630 with one expected skip, the validator ended in `TRANCHE VALIDATION PASSED`, manual Dear PyGui/Tkinter/SalixTorrent smoke passed, and the tranche was pushed as `79edec6` (`Add designer structural hierarchy editing`).
- Added an explicit `.gitignore` exception for repository-root `validate_tranche.bat`. The launcher existed in the accepted Tranche-10 working tree but the repository's broad `*.bat` ignore rule prevented it from being staged; Tranche 11 makes the one-command validator genuinely version-controlled alongside `tools/validate_tranche.py`.
- This tranche intentionally stops before snapshot-to-live component reconstruction, live preview synchronization, copy/paste/duplicate commands, pointer-driven drag/drop, selection overlays/resize handles, persisted undo history, a final project schema or final ecosystem/package API freeze.

### Ecosystem Extraction — Designer Property Commands and Undo/Redo

- Added standard-library-only `app/framework/designer_editing.py` as a document/snapshot editing layer above the Tranche-9 metadata model. `SetDesignerProperty`, `ClearDesignerProperty` and `CompositeDesignerEdit` are explicit command objects; they transform immutable `DesignerSnapshot` values rather than mutating live GUI components.
- Added `DesignerEditSession` with deterministic whole-snapshot undo/redo history, redo invalidation after divergent edits, one-step composite edits, clean/dirty tracking and `mark_clean()` support. Undo/redo availability is exposed through the already-proven generic `CommandSet` model using stable semantic command keys.
- Added inspector-facing `DesignerPropertyState` plus metadata-driven value normalization for text, booleans, bounded integers/numbers, choices, string/number lists, semantic `auto`/`fill` dimensions and compact/mapped insets. Read-only or non-serializable properties are rejected explicitly.
- Extended `DesignerPropertySpec` with explicit nullable and unsettable metadata. A future property inspector can now distinguish an explicit `None` value from a property that is absent because a sparse layout override should inherit/default; only metadata marked `unsettable` may be cleared. Current nullable framework properties include optional wrapping/text/numeric fields and layout spacing where the runtime already supports `None`.
- Expanded the relocation proof so a copied/renamed framework can edit a captured component snapshot and undo the edit without importing SalixTorrent or a GUI toolkit. The product-neutral blank application's real component snapshot is also exercised by the editing regressions while its live component objects remain unchanged.
- Added tracked `validate_tranche.bat` backed by the standard-library `tools/validate_tranche.py` process runner. The batch file selects the repository Python interpreter while the runner executes each command as an argument list, avoiding fragile CMD command-string quoting. It runs the tranche-focused gates, GUI/Tkinter regressions, localization check, both complete `unittest` discovery forms, headless proof, compileall and Git whitespace/status checks, then writes one complete report to `%USERPROFILE%\Desktop\console_output.txt`. Visual Dear PyGui/Tkinter/SalixTorrent checks remain manual.
- Real-Windows full-discovery validation then exposed a separate Tk/Tcl teardown hazard: after the Tkinter live tests had passed, later suite activity could trigger garbage collection of retained `tkinter.Variable` objects on a worker thread and abort the process with `Tcl_AsyncDelete: async handler deleted by the wrong thread`. `TkinterRenderer` now has explicit owner-thread cleanup for value variables/tooltips, `TkinterApplicationHost` invokes it before root destruction, Tkinter command-menu variables are released on rebuild/disposal, and the live-test teardown forces remaining Tk cycles to be collected on the Tk owner thread.
- Preparation validation advances complete discovery from 602 to **616 tests**. After repairing the Windows validator launch path and a Tk/Tcl owner-thread teardown hazard, real-Windows acceptance passes both complete discovery forms at **616 / 616** with one expected skip. The focused designer-editing, relocation, GUI-component and Tkinter gates pass, canonical localization remains 1,337 strings, the Dear PyGui/Tkinter/SalixTorrent visual smoke passes, and the accepted implementation commit is `3968bd2` (`Add designer property editing and undo history`). `APP_VERSION` remains `0.5.0`.
- This tranche intentionally stops before executable component reconstruction, mutation of live preview objects, structural insert/remove/reparent commands, copy/paste, drag/drop/resize handles, persistent command history, a final project document/schema or final ecosystem naming/API freeze.

### Ecosystem Extraction — Designer Component Metadata and Hierarchy Snapshots

- Added standard-library-only `app/framework/designer.py` with provisional `DesignerValueKind`, `DesignerPropertySpec`, `DesignerComponentSpec`, `DesignerCatalog` and `FRAMEWORK_DESIGNER_CATALOG` contracts. Stable internal type keys classify the component classes already used by SalixTorrent views without claiming final package/type names.
- Added explicit property metadata for common layout settings plus control/container/field properties. A source-audit regression verifies every framework `Component` class imported by current `app/views` is covered by the provisional designer catalog.
- Added `DesignerIdentityMap` for stable live-object IDs, including explicit persisted-key binding, and `DesignerNode` / `DesignerChild` / `DesignerSnapshot` for validated hierarchy captures. Snapshots reject duplicate IDs, component cycles/reuse and missing type metadata.
- Added `capture_component_tree(...)` with JSON round trips for real component hierarchies. Relationship metadata preserves grid row/column slots, tab page keys, split-pane weight/minimum/maximum/border settings, and the fixed/anchored placement descriptors introduced by the previous tranche.
- The product-neutral blank ecosystem application now exposes `capture_designer_snapshot()` on its existing component tree; repeated captures retain stable IDs without consulting the GUI backend. Framework relocation proof now exercises the designer snapshot boundary after copying/renaming the framework package.
- Preparation validation advanced complete discovery from 591 to **602 tests**. Display-less canonical Linux discovery passed 602 / 602 with 58 expected GUI/platform skips; real-Windows acceptance then passed both complete discovery forms at **602 / 602** with one expected skip. Dear PyGui and Tkinter visual resize/structure checks passed, including the reinforced minimum window geometry. Canonical localization remains 1,337 strings, and the accepted implementation commit is `5b54084f2d21dc331deb4614c15119ad94cab374`.
- This tranche intentionally stopped before component reconstruction/factories, a final project/document schema, live property mutation, drag/drop/reparenting or copy/paste. Snapshot-level property commands and undo/redo are prepared in the following tranche; no version bump, release tag, merge to `main`, final ecosystem naming or public API freeze was introduced. The Windows-acceptance documentation closure was pushed at `d939f6443a95490881925ca8bdb93e5e94f7ec2c`.

### Ecosystem Extraction — Anchors, Constraints and Serializable Geometry

- Added backend-neutral `AxisAnchor`, `AnchoredPlacement`, `AnchoredChild` and convenience helpers for start/centre/end/stretch placement inside a `PositionedPanel`. Anchored geometry remains parent-local and reflows through the existing `LayoutCoordinator`; fixed `(x, y)` placement remains fully supported.
- Added reusable `SizeConstraints` with minimum/maximum width and height bounds. Anchored stretch sizing applies those constraints after calculating the available parent-local extent, allowing a child to stretch responsively without exceeding designer/application limits.
- Added JSON-safe placement descriptors and `placement_from_descriptor(...)` round-trip restoration for both fixed and anchored geometry. This is intentionally geometry metadata only: it does not yet claim a full component registry, project document, inspector schema or public designer API.
- Extended `split_sizes(...)`, `split_widths(...)` and `SplitPane` with optional per-pane maximums. SalixTorrent now proves the constraint in Help by capping the Contents/Glossary navigation pane at 480 px while the document pane absorbs additional ultrawide space.
- Expanded the product-neutral blank ecosystem application with responsive anchored content and a constrained stretch control. The same semantic view continues to run through Tkinter and Dear PyGui without toolkit-name branching inside `DemoView`.
- Added focused anchor/constraint/descriptor, split-maximum, Tkinter live-reflow and relocation regressions. Initial prepared canonical discovery advanced from 581 to 589 tests; canonical localization remains 1,337 strings.
- Real-Windows acceptance exposed two final integration issues before commit: Diagnostics still called a removed private UI-error-log helper, and the blank application's deliberately fixed-positioned Actions proof could outgrow the left split pane at narrower supported widths. `GuiEngine` now exposes the diagnostics log through a public `ui_error_log_path()` contract, and the blank demo declares composition metrics that keep its fixed-position proof inside the pane down to the application's minimum width. Regression coverage advances canonical discovery to **591 tests**. The repaired Windows gate passed both complete discovery forms at **591 / 591** with one expected skip, the Dear PyGui/Tkinter visual recheck passed, and the tranche was pushed on `dev` at `5cef12f534dfc44a8536f504d1aa7773644f5428` (`Add responsive anchors and designer geometry constraints`).
- No application version, persistence schema, final ecosystem naming/API freeze, release tag or merge to `main` is introduced.

### Ecosystem Extraction — Structural Tabs, Split Regions and Overlays

- Added renderer-neutral `TabContainer` / `TabPage` structural components with stable semantic page keys, normalized change events, declarative and incremental page composition, explicit selection, and no dependency on toolkit tab IDs.
- Added renderer-neutral `SplitPanel` / `SplitPane` structural components for horizontal or vertical weighted regions with gaps, per-pane minimums and responsive reflow through the existing `LayoutCoordinator`. The framework geometry layer now exposes axis-neutral `split_sizes(...)`, while the historical width helper remains compatible.
- Added non-measuring overlay placement. Overlay children keep parent-local explicit coordinates but contribute no occupied extent, allowing HUD/decorative/designer surfaces to coexist with measured positioned content without enlarging the surrounding layout.
- Added Dear PyGui and Tkinter renderer support for tab bars/pages and split panes while preserving toolkit ownership in the engine adapters. Tkinter programmatic tab selection suppresses duplicate native change dispatch so semantic selection remains deterministic.
- Migrated Download detail tabs to `TabContainer`, migrated the General page's Transfer / Swarm Status / Torrent Info regions to a responsive three-pane `SplitPanel`, and changed application-menu detail navigation to select pages by semantic key rather than backend item ID.
- Migrated Help's Contents / Glossary navigation to `TabContainer` and its index/document region to `SplitPanel`, preserving localization, documentation rendering, scrolling and responsive wrap ownership at the application layer.
- Expanded the product-neutral blank ecosystem application to prove tabs, weighted split regions, measured explicit placement and a non-measuring overlay alongside command menus, live tables, state grids and realtime graphs through Dear PyGui or Tkinter without toolkit-name branching inside the view.
- Added focused structural-region, migration, mixed-layout, Tkinter and relocation regressions. Real-Windows acceptance passed both complete discovery forms at 581 / 581 with one expected non-Windows shell-behavior skip, and the tranche was pushed on `dev` at `731303d847a46c1e7e250d34d8b78a9e51f485ef` (`Add structural tabs, split regions and overlays`). Canonical localization remained 1,337 strings; no application version, persistence schema, release tag or merge to `main` was introduced.
- Hardened the Dear PyGui structural-tab adapter for the reference desktop backend: semantic TabContainer/TabPage width and height hints are now consumed by surrounding layout regions instead of being forwarded to Dear PyGui `tab_bar`/`tab` primitives, which do not accept those keywords. A backend-contract regression now locks this behavior.
- Hardened the structural region runtime after real-Windows visual acceptance exposed silent backend differences that unit tests did not surface: split panes are now sized and positioned deterministically inside a parent-local positioned root instead of relying on toolkit flow/group behavior, and tab-change normalization falls back to the backend current value when callback payload data is empty. This restores the Help navigator/document split, glossary document rendering, Download Speed live rendering and split-hosted blank-app live surfaces while preserving the same renderer-neutral contracts.

### Ecosystem Extraction — Command Menus, Ordered Items and Mixed Layout

- Added standard-library-only `OrderedItems` semantics for stable keyed ordering with generic `move_item_up`, `move_item_down`, explicit-index movement, boundary queries, replacement, append and removal. Active Transfers now uses that model for scheduler-order changes instead of Dear PyGui item-movement primitives while `TorrentManager` remains the durable queue-policy owner.
- Added renderer-neutral `CommandMenu` / `CommandMenuHost` coordination over the existing `CommandSet` tree, with Dear PyGui and Tkinter hosts for nested commands and enabled/checked state. Command semantics remain separate from physical menu widgets and application policy.
- Replaced the Files view's per-row Dear PyGui priority popups with one shared command-menu surface. The generic command tree describes current/available priority choices; SalixTorrent still owns actual file-priority mutation and right-click attachment.
- Added the first mixed-layout explicit-placement primitive: `PositionedPanel`, `Placement`, `PlacedComponent`, and `PositionedChild`. A positioned panel gives its direct children local `(x, y)` coordinates through the renderer `place(...)` contract, while `PlacedComponent` lets any ordinary component carry a parent-local offset and margins while still participating in a structured parent layout. The wrapper reserves the child's occupied offset + size, and `ControlGrid` consumes that semantic extent so the affected column/row can grow rather than clip the child. Dear PyGui maps this to item positioning and Tkinter maps it to `place()`.
- Expanded the Dear PyGui/Tkinter presentation bundles with explicit `COMMAND_MENUS` capability and extended the product-neutral blank ecosystem application to prove structured flow layout, local explicit placement and command menus alongside live tables, state grids and realtime graphs without toolkit-name branching inside the view.
- Documented the long-term mixed-layout rule for WYSIWYG work: layout policy is container-local, so structured layout and explicit placement can coexist in one hierarchy. Explicit coordinates are resolved inside the parent-assigned content space, naturally translating through parent padding/margins, and positioned children can contribute their occupied bounds to parent measurement instead of becoming invisible to layout.
- Added focused ordering, command-menu, mixed-layout, backend and relocation regressions. No application version, persistence schema, canonical localization strings, final ecosystem naming/API freeze, release tag or merge to `main` is introduced.

### Ecosystem Extraction — Interactive Data, Selection and Commands

- Added standard-library-only `DataView`, `DataRecord`, `SortTerm`, and `SortDirection` contracts for deterministic keyed search/filter/sort projection outside any GUI toolkit.
- Added explicit `SelectionModel`, `CommandSpec`, and `CommandSet` interaction contracts. Commands expose stable identities plus enabled/checked/submenu state without embedding backend callbacks or introducing observer/reactive machinery.
- Routed Active Transfers queue ordering and visibility projection through the generic data-view layer while preserving Dear PyGui's existing sortable headers, filters, persisted queue order, row actions, and SalixTorrent-specific policy.
- Migrated the Files detail table onto the renderer-neutral `LiveTable` boundary. Stable file identity, changed-row updates, colours and contextual cell help now use the same live-data contract already proven by Peers, Sources and Pieces.
- Reframed file-priority context-menu state through backend-neutral command specifications while leaving actual torrent mutation and the current Dear PyGui popup host application-owned. This intentionally separates semantic command state from physical menu rendering before a later multi-backend command host is extracted.
- Extended framework relocation proof to import and execute the interaction/data-view contracts after package copy/rename with no application or GUI dependency.
- Added 18 focused regressions. Complete source discovery advances from 529 to 547 tests; canonical localization remains 1,337 strings.

### Ecosystem Extraction — Live Tables and State-Grid Presentation

- Added renderer-neutral keyed live-table contracts under `app/framework/live_data.py`, including column/cell/row/frame models, explicit backend bindings, stable row identity, incremental changed-row updates, removal/reordering, optional cell foreground metadata, and per-cell explanatory text without requiring a GUI toolkit in the framework.
- Added renderer-neutral categorical state-grid contracts for compact high-density activity/state maps. State-grid cells carry stable identity and backend-neutral RGBA presentation data while concrete sizing/drawing remains adapter-owned.
- Added Dear PyGui and Tkinter table hosts plus Dear PyGui drawlist and Tkinter Canvas state-grid hosts. The presentation backend capability bundle now advertises live-table and state-grid support independently of components, scenes, layout, and realtime plots.
- Migrated the live Peers and Sources tables away from direct Dear PyGui row creation/deletion. Stable peer connection/source identities now preserve backend rows across updates, while SalixTorrent-specific formatting, localization, discovery semantics, and contextual help remain application-owned.
- Migrated the Pieces detail table and compact piece map through the same generic live-table/state-grid boundaries. Piece bucketing, scheduler/disk telemetry, piece-state meaning, colors, and application wording remain SalixTorrent-specific; direct `dpg.table_row`, `dpg.add_drawlist`, and `dpg.draw_rectangle` calls are removed from the Pieces view.
- Expanded the product-neutral blank ecosystem application so the same `DemoView` now proves semantic components, a keyed live table, a state grid, and a realtime graph through Dear PyGui or Tkinter without toolkit-name branching inside the view. Headless mode continues to exercise only the shared runtime.
- Added 13 focused live-data/Tkinter/backend regressions, including a Dear PyGui resize-reflow/resource-ownership regression, advancing complete discovery from the committed 516-test checkpoint to 529 tests. Source validation passes 529 / 529 in both display-less and Xvfb-backed Linux runs; canonical localization remains 1,337 strings with only extraction source metadata refreshed.
- This tranche deliberately leaves the transfer queue and interactive Files table application-owned for now because sorting/filtering, context menus, per-row commands, and file-priority mutation need a richer interaction contract than the read-only live-table boundary should pretend to provide.
- No application version bump, persistence-schema change, localization-string change, final ecosystem naming/API freeze, release tag, or merge to `main` is introduced.

### Ecosystem Extraction — Tkinter Compatibility Backend and Blank Application Proof

- Added backend-neutral `ApplicationSpec` / `ApplicationHost` metadata and explicit `PresentationBackend` capability bundles so desktop and headless hosts share one application vocabulary without making a GUI toolkit a runtime dependency.
- Added a Tkinter compatibility implementation of the existing component renderer, responsive layout host, scene host, and realtime plot host contracts. The same framework `Button`, inputs, grids, dialogs, runtime state, scene switching, and `RealtimeGraph` contracts now have a second concrete GUI implementation.
- Added a Tkinter Canvas realtime line-plot adapter that consumes the renderer-neutral `PlotHost` / `PlotFrame` contract introduced by the first ecosystem tranche; SalixTorrent-specific Speed labels and transfer semantics remain outside the compatibility backend.
- Added reusable Dear PyGui, Tkinter, and headless presentation-bundle composition factories plus minimal Dear PyGui/Tkinter/headless application hosts. The hosts own toolkit event loops and drive the same `ApplicationRuntime` lifecycle while generic application content depends only on framework contracts.
- Added `examples/ecosystem_blank_app.py`, a product-neutral blank-application proof whose component tree and realtime graph definition are unchanged between Dear PyGui and Tkinter. `--ui-backend dearpygui|tkinter|headless` selects only the outer host; headless mode runs the same application runtime without importing a graphical toolkit.
- Added focused application-spec/capability, packaging, headless-host, Tkinter component/layout/scene/plot, application-host, and blank-demo regressions. Real-Windows validation passed both complete discovery paths at 516 / 516 with one expected non-Windows shell-behavior skip, plus live Dear PyGui/Tkinter blank-application proof and an unchanged SalixTorrent desktop smoke.
- Committed/pushed on `dev` as `522ac8467fc55a5ac0e3d71fe5fd470251e13562` (`Add Tkinter compatibility application backend`).
- This is a compatibility/reference backend, not a Tkinter rewrite of SalixTorrent and not a promise of pixel-identical or feature-identical parity. Dear PyGui remains the reference SalixTorrent desktop backend.
- No application version bump, persistence-schema change, localization-string change, final ecosystem naming/API freeze, release tag, or merge to `main` is introduced.

### Ecosystem Extraction — Application Runtime and Generic Network Foundation

- Added a provisional, standard-library-only `app/runtime/` package for backend-neutral application mechanics that can be used by graphical, CLI/headless, test, and future designer hosts without importing Dear PyGui or BitTorrent protocol code.
- Added explicit `ApplicationRuntime`, `ServiceRegistry`, `RuntimeService`, and `CallbackService` lifecycle coordination with ordered startup, reverse-order teardown, restart support, per-service update failure isolation, startup rollback/cleanup, and no swallowing of control-flow `BaseException` types.
- Added backend-neutral `SceneRegistry` / `SceneHost` contracts and the concrete `DearPyGuiSceneHost`; `SceneManager` is now the SalixTorrent compatibility/composition facade and no longer imports Dear PyGui directly.
- Added reusable `ExceptionReporter` throttling/logging and moved `GuiEngine` UI-update diagnostics onto that generic failure-reporting mechanism while preserving SalixTorrent's `ui_errors.log` destination and repeated-error suppression.
- Extracted the installed/portable/state/download/resource path rules into parameterized `RuntimePathSpec` / `RuntimePaths`; `app/engine/runtime_paths.py` now supplies SalixTorrent's application/env names through that generic policy while preserving its established public function surface.
- Kept runtime root normalization lexical rather than filesystem-canonicalizing caller-supplied roots, preserving Windows short/long path aliases returned by temporary, portable and bundled locations while still producing absolute roots.
- Extracted generic dual-stack network-interface/address/source-binding helpers into `app/runtime/network.py`; SalixTorrent production callers now use that runtime boundary directly while `app/logic/network_binding.py` remains a compatibility facade. BitTorrent routing policy, trackers, DHT/PEX/LPD, peer sessions, listener policy, MSE/PE, and torrent-specific connectivity diagnosis remain application-owned.
- Integrated the same `ApplicationRuntime` lifecycle into both the Dear PyGui desktop engine and the headless CLI. Desktop application-menu and active-scene updates are explicit runtime services driven by measured frame delta; headless manager startup/shutdown is supervised by the same runtime without importing a GUI backend.
- Added 50 focused runtime/scene/network/adapter/relocation regressions. Real-Windows validation passed both complete discovery paths at 482 / 482 with one expected non-Windows shell-behavior skip; the repaired Windows path-alias regression is included in that gate.
- Committed/pushed on `dev` as `8e707efeb0cda162ee038a028a39a77663c2fa4e` (`Extract application runtime and network foundation`).
- No application version bump, persistence-schema change, localization-string change, public API freeze, release tag, or merge to `main` was introduced.

### Ecosystem Extraction — Realtime Telemetry and Plot Boundary

- Added backend-neutral rolling telemetry contracts under `app/framework/telemetry.py`, including fixed-series samples, bounded rolling history, immutable snapshots, age-based windows, and current/average/peak/minimum statistics suitable for GUI or headless consumers.
- Added renderer-neutral realtime line-plot contracts under `app/framework/visualization.py`, including semantic series specifications/data, complete plot frames, a small `PlotHost` protocol, explicit plot bindings, and `RealtimeGraph` coordination without Dear PyGui imports.
- Added `DearPyGuiPlotHost` under `app/engine/plot_hosts/` so plot creation, line-series updates, axis labels/limits, existence checks, and disposal are concrete backend responsibilities.
- Migrated the Active Transfers Speed graph to the new graph/plot-host boundary while preserving its existing localized labels, tooltips, rate-unit semantics, visible-window behavior, limit lines, and SalixTorrent-specific summary text.
- Replaced the torrent session's private deque/statistics implementation with the generic rolling telemetry model while preserving the existing `speed_view` snapshot shape consumed by the desktop application.
- Extended the framework relocation probe to import and exercise telemetry and realtime visualization after package rename, with no SalixTorrent or Dear PyGui dependency in the relocated framework.
- Added 16 focused telemetry/visualization regressions. Real-Windows validation passed both complete discovery paths at 432 / 432 with one expected non-Windows skip, and live application/Speed behavior plus the broader button/action surface was smoke-tested before commit/push. Canonical localization remains 1,337 strings; only extraction source metadata changed.
- Committed/pushed on `dev` as `ef8b4be998a714a86455940d8642fdd926a6609d` (`Extract realtime telemetry and plot boundary`). Current names remain provisional and no Tkinter plot implementation, backend-selection CLI, public API freeze, application-version bump, protocol change, or persistence-schema change was introduced.

### Development Architecture and Documentation

- Documented the post-v0.5.0 reverse-pyramid extraction strategy: SalixTorrent remains the reference application while reusable behavior moves into a general application engine/runtime, optional RAD/application framework, and concrete backend/platform adapters.
- Defined Dear PyGui as the current reference desktop backend, Tkinter as the planned compatibility implementation for the common GUI surface, and headless/CLI execution as a first-class profile.
- Recorded realtime telemetry/graph extraction, generic network/runtime awareness, application lifecycle/presentation-host separation, rich live-data views, and later designer metadata as explicit audit targets before final public naming/API freeze.
- Added `SalixTorrent-Ecosystem-Architecture.md` to describe the long-term WYSIWYG RAD-editor destination, backend-capability policy, reverse-pyramid classification rules, extraction sequence, and conditions required before external package/API stabilization.
- Established `main` as the stable/release line and `dev` as the active post-v0.5.0 integration branch.
- No runtime, protocol, persistence, localization, packaging or user-facing application behavior changes are introduced by this documentation update.

## v0.5.0 - 2026-09-07

v0.5.0 completes the reusable GUI component/framework foundation developed after v0.4.0 while preserving the established torrent engine, persistence, localization, and packaging behavior. The release keeps the framework namespace provisional: final external package/repository naming and a frozen third-party API remain later work.

### Release

- Released and tagged v0.5.0 at `d403c47f98f7e30d8adf879cd04e098dabc8767e` (`Prepare SalixTorrent v0.5.0 release`).
- Passed both complete real-Windows discovery paths at 416 / 416 tests with one expected non-Windows shell-behavior skip.
- Built and smoke-tested the standalone desktop executable, standalone CLI executable, portable ZIP and Inno Setup installer.
- Verified the frozen CLI reports exactly `SalixTorrent 0.5.0` before publishing the annotated `v0.5.0` tag.

### GUI/RAD Extraction — Backend-Neutral Responsive Coordination

- Added a reusable `LayoutHost` protocol and `LayoutCoordinator` under `app/framework/responsive.py`, separating keyed callback coordination, explicit refresh/trigger behavior, item-watch replacement, and memoized geometry application from any concrete GUI toolkit.
- Added the concrete `DearPyGuiLayoutHost` under `app/engine/layout_hosts/`; it exclusively owns Dear PyGui viewport callback adaptation, item-handler registries, item-size reads, existence checks, and `configure_item(...)` writes.
- Reduced `app/engine/responsive_layout.py` to the SalixTorrent singleton/composition surface over the framework coordinator plus Dear PyGui host, while preserving existing view/documentation call sites and framework-geometry compatibility exports.
- Kept native clipboard/file-dialog/network services, transfer tables/graphs, scene ownership, and Dear PyGui handler objects outside the reusable framework.
- Extended responsive-layout regression coverage from 7 to 14 tests and extended the isolated framework relocation probe to construct/use the responsive coordinator after package rename. The expected full real-Windows suite advances from 408 to 415 tests.
- The completed component/documentation/geometry/relocation/responsive boundaries satisfy the planned v0.5.0 reusable-GUI-foundation feature scope. The tranche passed its 415-test Windows gate and live GUI smoke before the separate v0.5.0 release-preparation change.
- No user-facing strings, transfer/network behavior, persistence schema, or SalixORM integration changed in the feature tranche; the v0.5.0 release-preparation commit then advances the application version and release-facing metadata.

### GUI/RAD Extraction — Framework Package Relocation Readiness

- Converted every intra-framework dependency under `app/framework/` to package-relative imports so the reusable tree no longer hard-codes the SalixTorrent `app.framework` namespace internally.
- Added an isolated packaging probe that copies the framework directory to a temporary package named `portable_framework`, imports every module under Python isolated mode, and verifies that neither SalixTorrent's `app` package nor Dear PyGui is loaded.
- Added a second relocation probe that exercises representative component, documentation, geometry, and property-cascade contracts from the renamed package.
- Added a standard-library-only dependency audit for the framework boundary and a guard that keeps the provisional root package from freezing a final package version or wildcard public API during extraction.
- Kept Dear PyGui resize-dispatch ownership in `app/engine/responsive_layout.py`; no callback registry, backend state, or application service was moved merely for cosmetic symmetry.
- Added five framework-packaging regressions. The focused component/documentation/responsive suites remain unchanged, while the expected full real-Windows suite advances from 403 to 408 tests.
- No user-facing strings, transfer/network behavior, persistence schema, SalixORM integration, or application version changed.

### GUI/RAD Extraction — Framework Documentation and Geometry Boundary

- Extracted backend-neutral geometry primitives (`ContentBounds`, alignment enums, content metrics, clamps/splits/fill helpers, and dialog metrics) into `app/framework/geometry.py`; the Dear PyGui resize dispatcher remains in `app/engine/responsive_layout.py` and re-exports the pure contracts for compatibility.
- Moved the semantic documentation model, sparse layout policy/cascade, and typography/theme contracts into `app/framework/documentation/` as a second independent reusable subsystem.
- Kept the concrete `DocumentationRenderer` in `app/engine/documentation/renderer.py` because it legitimately owns Dear PyGui, SalixTorrent runtime-resource lookup, application typography, media caching, and responsive callback integration.
- Converted the former engine documentation model/layout/typography modules into compatibility facades and migrated application surfaces/tests onto the framework-facing contracts without a breaking public rename.
- Extended source-level extraction coverage so framework documentation/geometry modules reject imports from SalixTorrent engine/view/logic/localization layers and Dear PyGui.
- Added six documentation/framework-boundary regressions; the focused documentation/localization gate increases from 34 to 40 while the component suite remains 63. The expected real-Windows full-suite total advances from 397 to 403.
- Regenerated deterministic localization extraction metadata after source relocation with canonical UI/Help/Glossary wording unchanged at 1,337 entries.
- No transfer/network behavior, settings/session schema, SalixORM integration, user-facing documentation prose, or final framework naming/API decision changed.

### GUI Component/RAD Extraction — First Physical Framework Boundary

- Moved the reusable property-cascade and GUI component implementations into the provisional internal `app/framework/` boundary, while retaining `app/engine/components/` and `app/engine/property_cascade.py` as compatibility facades during extraction.
- Migrated SalixTorrent views, component profile/attachment adapters, documentation layout code, and component tests to import the reusable contracts from `app.framework` rather than the application engine namespace.
- Split the concrete `DearPyGuiRenderer` into an application/backend adapter under `app/engine/component_renderers/`; the reusable renderer module now contains only the backend-neutral protocol and renderer-selection contract.
- Replaced the hidden Dear PyGui default with explicit `set_default_renderer(...)` / `get_default_renderer()` / `clear_default_renderer(...)` composition-root ownership. `GuiEngine` now creates, installs, profiles, and clears SalixTorrent's Dear PyGui renderer explicitly.
- Added an extraction-boundary regression that rejects product-layer, localization-layer, engine-layer, or Dear PyGui imports from the framework candidate modules, plus renderer-installation, backend-isolation, composition-root, and compatibility-facade coverage.
- Kept all current component/RAD names provisional; this tranche creates an internal physical boundary without choosing the eventual external framework package/repository name.
- No user-facing strings, settings/session schemas, transfer behavior, SalixORM integration, or complex queue/table/telemetry ownership changed.
- Added five net component regressions, increasing the focused component suite from 58 to 63 and the expected full real-Windows suite from 392 to 397.

### GUI Component/RAD Extraction — Renderer-Neutral Events and Explicit Disposal

- Added immutable backend-neutral `ComponentEvent` metadata with semantic `ACTIVATE` and `CHANGE` event types so reusable controls no longer expose renderer callback tuple conventions.
- Replaced reusable-control `user_data` with explicit `event_data`, keeping application metadata distinct from Dear PyGui sender/app-data/user-data arguments.
- Added `action_callback(...)` for deliberate adaptation of existing no-argument application commands to the component-event contract.
- Extended labeled/composite value fields to carry the same event metadata without introducing observers, subscriptions, background mutation, or automatic two-way state.
- Added renderer-owned `destroy(...)` plus explicit idempotent `Component.dispose()` lifecycle semantics; stale rendered handles are rejected by `require_item()` and an explicitly rebuilt component can bind a fresh backend item.
- Migrated Create Torrent, Preferences, Open Magnet, Remove Torrent, Removal Notice, Force Recheck and Download Complete component-button actions through the renderer-neutral event adapter while leaving complex queue/context-menu callbacks on their existing application boundary.
- Regenerated deterministic localization extraction metadata with canonical UI/Help/Glossary wording unchanged.
- Added seven event/lifecycle regressions, increasing the component suite from 51 to 58 and the expected real-Windows full-suite total from 385 to 392.

### GUI Component/RAD Extraction — Explicit Preference Bindings

- Added backend-neutral `ValueBinding` and `BindingSet` contracts for explicit, synchronous component-to-model synchronization without observers, background mutation, or implicit two-way reactivity.
- Added per-binding read/write transforms and explicit defaults so application code can convert localized presentation values, numeric input, booleans, and storage-facing canonical values at a single named boundary.
- Migrated Preferences collection/synchronization onto the binding contract while retaining the existing application-owned normalization and persistence APIs.
- Removed direct Dear PyGui usage from `settings_view.py`: Preferences status/connectivity text, network-interface refresh, file-path value access, save/restore synchronization, seeding-default reset, and ordinary control reads/writes now use component APIs.
- Kept `ResponsiveLayout`, Tk/native folder selection, networking services, localization conversion, and seeding-duration composition as explicit application concerns rather than folding unrelated services into binding.
- Preserved the established Preferences layout, Help/Glossary strings, settings schema, save/apply semantics, networking refresh behavior, and seeding-goal bulk-apply behavior.
- Added five binding/runtime regressions, increasing the component suite from 46 to 51; real-Windows validation passed both full discovery paths at 385/385 with one expected non-Windows skip before the tranche was committed and pushed.

### GUI Component/RAD Extraction — Transfer Utility Dialogs

- Added backend-neutral dialog minimum-size and viewport-centering behavior to the reusable `Dialog`/renderer contract instead of positioning ordinary dialogs with Dear PyGui viewport calls in view logic.
- Added runtime `ProgressBar.set_overlay(...)` support so progress text updates remain behind the same component renderer boundary as progress values.
- Migrated the complete Open Magnet dialog onto reusable `Dialog`, `ControlRow`, `TextInput`, `Button`, `ProgressBar`, `Label`, `Spacer` and application tooltip attachments while preserving BEP-9 lookup/cancel/auto-close semantics and responsive sizing.
- Migrated the Remove Torrent, Removal Notice, Force Recheck and Download Complete utility dialogs onto the same reusable structural/control/profile boundaries while preserving their existing callbacks, destructive-action safeguards and notification behavior.
- Centralized the established magnet/remove/recheck/completion dialog dimensions in the SalixTorrent component profile, including the magnet field/progress dimensions.
- Proved the renderer-neutral runtime-state contract on a second independent workflow: magnet input, progress overlay/value, status, Add/Cancel enabled state and dialog visibility no longer use Dear PyGui state calls directly.
- Added six component/dialog regressions, increasing the component suite from 40 to 46; real-Windows validation passed both full discovery paths at 380/380 with one expected non-Windows skip before the tranche was committed and pushed.

### GUI Component/RAD Extraction — Backend-Neutral Runtime State

- Added renderer-neutral runtime configuration helpers on every component for existence checks, enabled state and visibility without exposing Dear PyGui calls to view logic.
- Added `ComponentGroup` for coordinated state transitions across related controls without creating product-specific form classes.
- Migrated Create Torrent's complete runtime value/state path onto component objects: source/output/status/detail labels, progress, editable-control busy state, combo/text/checkbox reads, Cancel, and Start Seeding visibility/enabled transitions no longer call Dear PyGui directly.
- Kept raw item IDs available only where existing `ResponsiveLayout` geometry operations still require them, preserving established resize behavior and compatibility boundaries.
- Deliberately stopped short of an automatic observer/data-binding system: this tranche extracts only lifecycle behavior already proven by duplicated runtime state updates.
- Added four runtime-state regressions, increasing the component suite from 36 to 40; real-Windows validation passed both full discovery paths at 374/374 with one expected non-Windows skip before the tranche was committed and pushed.

### GUI Component/RAD Extraction — Create Torrent Form and Tooltip Boundary

- Added a backend-neutral `Tooltip` component attachment and moved Dear PyGui tooltip creation/failure isolation behind the reusable component renderer contract.
- Kept SalixTorrent Help/Glossary semantics application-owned through a small attachment adapter rather than embedding torrent terminology in generic controls.
- Added a reusable `ProgressBar` value component and extended `TextInput` with backend-neutral label support needed by ordinary form migration.
- Migrated the complete Create Torrent form onto `ControlColumn`, `ControlRow`, `SectionPanel`, primitive/value components and attachment adapters while preserving existing raw item IDs, callbacks, background creation behavior and responsive tracker-panel resizing.
- Centralized Create Torrent panel/control dimensions in the application component profile instead of keeping Dear PyGui width/height literals in view construction.
- Kept canonical UI/Help/Glossary wording unchanged; only deterministic localization extraction locations/manifests move with the refactor.
- Added eight component/form/tooltip regressions, increasing the component suite from 28 to 36 and the expected real-Windows full-suite total from 362 to 370 after the structural tranche is accepted.

### Reusable GUI Component Foundation

- Added a framework-owned component package under `app/engine/components/` with backend-neutral primitive controls, semantic layout sizing, a Dear PyGui renderer bridge, and value/configuration helpers.
- Added semantic `AUTO` / `FILL` sizing so framework-facing code no longer needs to depend on Dear PyGui's raw sizing sentinel values.
- Added `ControlRow`, a generic single-row container for an arbitrary number of child components, with width, height and spacing resolved through the existing `framework default -> active theme -> explicit instance override` property cascade.
- Added `ControlGrid` and `ControlColumn` composition primitives for aligned form rows and vertical component groups.
- Added reusable `LabeledComboField`, `LabeledNumericField`, and `DurationEditor` composites built from the primitive component layer.
- Migrated the seeding-goal controls in Torrent Properties, `Configure targets...`, and Preferences new-torrent defaults onto the new component layer while preserving the existing GUI behavior, localized strings, durable policy semantics, and legacy item-id aliases used by the surrounding views.
- Added headless component regressions covering layout provenance/fallback, semantic sizing, arbitrary `ControlRow` composition, integer/float numeric dispatch, value/configuration access, grid validation, and the three-part duration editor.
- Regenerated deterministic localization extraction metadata after the view-level component migration; no canonical UI/Help/Glossary strings changed.
- Validated the first component tranche on the real Windows checkout at 343/343 tests in both canonical and plain discovery, with one expected non-Windows skip; live GUI smoke confirmed parity in Torrent Properties, `Configure targets...`, and Preferences.

### Preferences Component Composition Expansion

- Added generic `LabeledField` composition so one label, one primary control, and zero or more trailing/accessory components can share a single reusable row without proliferating narrowly named widget combinations.
- Added backend-neutral `TextInput` and reusable `NumericUnitField` components; the latter composes a validated numeric stepper with a unit selector through the same generic field/accessory boundary.
- Refactored `LabeledComboField` and `LabeledNumericField` to share the generic `LabeledField` contract instead of maintaining parallel row implementations.
- Migrated Preferences value controls onto the component layer, including the default download-directory chooser, listen-port fallback row, torrent protocol/max peers, DHT/PEX/LPD and port-mapping toggles, peer encryption, network-interface selection/refresh, Interface Lock/IP masking, queue controls, global/default bandwidth rows, desktop choices/toggles, and Save/Restore actions.
- Preserved the existing Dear PyGui item identifiers as compatibility aliases so persistence, refresh, tooltips, validation, and save/restore behavior continue through the established view logic while construction becomes framework-owned.
- Added five component regressions covering generic trailing accessories, numeric+unit composition, text-input rendering/value access, specialized-field inheritance, and the rule that Preferences no longer constructs input/combo/checkbox value controls directly through Dear PyGui.
- Regenerated deterministic localization extraction metadata after the Preferences migration; canonical UI/Help/Glossary strings remain unchanged.
- Validated the Preferences composition tranche on the real Windows checkout at 348/348 tests in both canonical and plain discovery, with one expected non-Windows skip.

### Component Layout Profiles

- Added backend-neutral `ComponentLayoutProfile` support so reusable controls can select named layout defaults instead of repeating concrete width constants in view code.
- Made the active component profile a renderer-level policy selected once by the application composition root; the framework profile still provides safe `AUTO` fallbacks when a named slot is absent.
- Preserved the existing property precedence for each component: profile/framework default -> component theme -> explicit instance override.
- Added SalixTorrent's desktop component profile in `app/engine/ui_component_profile.py`, centralizing the exact Preferences and seeding-goal control metrics that were previously scattered across `settings_view.py` and `download_view.py`.
- Added profile-owned aligned-grid column metrics so `DurationEditor` can inherit Days/Hours/Minutes input, grid, and column dimensions without embedding view-specific numbers.
- Kept `LabeledComboField`, `LabeledNumericField`, `NumericUnitField`, direct primitive controls, and `DurationEditor` compatible with explicit width overrides for exceptional one-off layouts.
- Removed direct component-width constants from the migrated Preferences and seeding-goal view construction paths while preserving the existing live layout.
- Added six headless regressions for named profile defaults, safe fallback, theme/instance precedence, numeric-unit profile slots, duration grid metrics, and the rule that migrated view dimensions are profile-owned.
- Regenerated deterministic localization extraction metadata after line movement; canonical UI/Help/Glossary strings remain unchanged.
- Validated the component-profile tranche on the real Windows checkout at 354/354 tests in both canonical and plain discovery, with one expected non-Windows skip; visual smoke confirmed Preferences, Torrent Properties, and `Configure targets...` retained their established layout.

### Structural Component Composition

- Added backend-neutral `Separator`, `SectionPanel`, and `Dialog` structural components and extended `ControlRow` / `ControlColumn` with context-managed construction for incremental migration of proven imperative views.
- Added generic component post-build attachment hooks so product-specific tooltip, accessibility, diagnostics, or metadata behavior can attach without moving those semantics into the reusable component model.
- Extended the Dear PyGui renderer bridge with separator, panel/child-window, and dialog/window rendering while keeping backend-specific construction outside the component model.
- Migrated the Preferences structural tree away from direct Dear PyGui groups/child windows: the root, paired sections, panel headings/separators, and panel sizing now flow through reusable structural components and the application component profile.
- Moved the eight established Preferences panel dimensions into `ui_component_profile.py`, preserving responsive width updates while centralizing initial structural metrics.
- Migrated the focused `Configure targets...` seeding-goal window onto the reusable `Dialog` boundary and moved its 620x365 dimensions into the application profile without changing policy behavior or strings.
- Added eight headless regressions for attachment timing, context-managed row/column composition, panel heading/separator ownership, declarative panel children, profile-owned dialog sizing, Preferences structural ownership, and the Configure-targets dialog boundary.
- Regenerated deterministic localization extraction metadata after source movement; canonical UI/Help/Glossary strings remain unchanged at 1337 entries.



### Release Preparation

- Advanced `APP_VERSION` from `0.4.0` to `0.5.0` after the complete reusable-GUI-foundation feature scope passed the 415-test Windows gate and live GUI smoke.
- Updated release-facing README and roadmap state to make v0.5.0 the current release checkpoint while preserving v0.4.0 as the previous immutable release boundary.
- Updated the Inno Setup fallback `MyAppVersion` to `0.5.0`; normal Windows builds still inject `APP_VERSION` explicitly.
- Added a release-packaging regression that requires the Inno fallback version to match `APP_VERSION`, preventing stale manual-installer metadata in future releases.
- Completed the final release gate at 416 tests on Windows with one expected non-Windows skip, then built/smoked the standalone GUI/CLI, portable ZIP and installer, verified frozen `SalixTorrent 0.5.0` output, pushed the release commit, and published the annotated `v0.5.0` tag.

## v0.4.0 - 2026-09-05

### Release

- Promoted SalixTorrent to version 0.4.0 after the completed durability and transfer-lifecycle milestone.
- Consolidated the Phase 12 offline-first localization foundation, backend-neutral application/session persistence, optional SalixORM/SQLite integrations, tracked regression-suite migration, and durable per-torrent seeding goals into one release checkpoint.
- Preserved deterministic JSON as the default/reference persistence path while keeping SalixORM integrations explicit and optional.
- Established the release source baseline at 334 / 334 real-Windows regression tests passing, with one expected non-Windows shell-behavior skip.

### Seeding Goals & Automatic Stop

- Added durable per-torrent seeding policies with four modes: Seed Indefinitely, Stop at Ratio, Stop after Time, and Stop at Ratio or Time.
- Added application defaults for new torrents without silently rewriting existing per-torrent policies.
- Added an explicit one-shot **Apply this seeding goal to all existing torrents when saving** Preferences action for deliberate bulk updates.
- Added right-click **Seeding Goal** controls with quick mode changes and a focused target editor, while retaining the same durable per-torrent controls in Torrent Properties.
- Expanded **Stop after Time** into lazy right-click Days (1-31), Hours (1-12), and Minutes (1-60) component submenus that combine additively (for example 1 day + 5 hours + 10 minutes), with independent passive branch markers, interactive numeric check marks, per-component toggle-off behavior, and **Clear Time (Days/Hrs/Mins)**; exact targets remain available through **Configure targets...**.
- Polished long-duration presentation and editing: General now shows timed-goal elapsed/target values as Days/Hours/Minutes, while **Configure targets...**, Torrent Properties, and the Preferences default expose separate Days, Hours, and Minutes fields instead of requiring large minute totals.
- Stacked the Days, Hours, and Minutes controls vertically in **Configure targets...** and the compact Preferences default panel so unit labels and Dear PyGui +/- controls stay readable at normal DPI and scaled desktop layouts; widened the Preferences ratio input to match the polished numeric-control presentation.
- Added immediate seeding-goal update events so General, Properties and context-menu state reflect per-torrent changes without requiring stop/start or application restart.
- Kept a dedicated cumulative Seed Time counter for lifetime-style telemetry, while time-based goals now persist an independent instance baseline so every explicit timed-goal apply/change starts counting from that moment instead of immediately consuming historical Seed Time.
- Added automatic stop handling through the shared `TorrentManager` lifecycle boundary so a reached goal becomes durable Stopped intent, rebalances the queue, and emits desktop/in-app notification events.
- Added live seeding-goal progress to General/Properties, including payload-based ratio progress that remains meaningful for external/source-backed seeds.
- Advanced normalized session state to version 9 and added SalixORM migration `session-state-0003` for timed-goal baselines and additive quick-time components; historical JSON versions 1-8 and existing SalixORM v7/v8 databases remain upgrade-compatible while `session-state-0001` and `session-state-0002` stay checksum-frozen.
- Added internal Help/Glossary coverage for seeding goals, ratio targets, cumulative seed time and automatic-stop restart behavior, with corresponding localization extraction updates.
- Added policy, application-settings, JSON-session, SalixORM migration and restore regression coverage for the new lifecycle behavior.
- Validated the completed seeding-goal tranche on the real Windows checkout at 334/334 tests in both canonical and plain discovery, with one expected non-Windows skip; localization extraction/manifests, pseudo locale, offline validation, and 432/432 translation-memory parity also remained clean.

### Maintained Regression Suite

- Moved the maintained `unittest` regression suite from repository-root local files into a version-controlled `tests/` package with logical core, protocol, network, persistence, platform, packaging, presentation, CLI and localization subpackages.
- Replaced milestone-only test filenames/classes with behavior-oriented names while preserving milestone lineage in module documentation.
- Added shared repository-root helpers so moved tests no longer depend on `Path(__file__).parent` being the project root, and preserved subprocess working-directory contracts explicitly.
- Added dedicated session-restore regressions for unavailable source/cache metainfo and saved-info-hash mismatch refusal.
- Removed the historical `.gitignore` exclusions that kept maintained regression tests out of the public repository and documented canonical full/focused `unittest` commands.
- Validated both canonical `tests/` discovery and plain repository-root discovery at 305 tests on the real Windows checkout, with one expected non-Windows skip.

### Session-State Persistence Boundary

- Added a backend-neutral `SessionStateStore` boundary so `TorrentManager` no longer owns `session.json` file I/O directly; deterministic JSON remains the default/reference backend.
- Advanced the normalized session snapshot to version 7 while retaining JSON import compatibility for historical versions 1-6.
- Removed `max_active_downloads` from new session snapshots so application settings are the single durable authority for the active-download slot preference; legacy session values no longer overwrite current settings during restore.
- Added lazy session backend selection with `SALIX_T_SESSION_BACKEND=json|salixorm` and optional `SALIX_T_SESSION_URL`; headless/nonpersistent managers force the JSON boundary without importing an optional SalixORM backend.
- Added an optional file-backed SQLite session adapter using SalixORM `v0.2.0`, explicit `session-state-0001` migration metadata, ordered per-torrent rows, and one-transaction whole-snapshot replacement.
- Preserved queue order explicitly with validated contiguous queue positions and persisted selected transfer, lifecycle intent, transfer limits, uploaded totals, seed-source path, protocol policy, file priorities and queue priority.
- Made manual Move Up / Move Down immediately return a column-sorted queue view to real queue order so the GUI visibly reflects the persisted scheduler change without requiring a second Queue Order click.
- Made the transfer table start in unsorted queue-order mode so a restored persisted queue is presented in scheduler order on the first rendered frame instead of defaulting to Name ASC.
- Added read-only `session.json` bootstrap for an empty opt-in SalixORM store without deleting or dual-writing the legacy artifact.
- Made corrupt/incompatible SalixORM session state fail closed and mark the active store unhealthy so later queue changes or shutdown cannot silently overwrite the damaged database.
- Added diagnostics for active session backend/storage health and regression coverage for JSON v1-v6 compatibility, JSON v7 authority, lazy dependency behavior, SalixORM migration/reopen/order parity, atomic failed save, corrupt metadata/queue refusal, legacy bootstrap, custom database targets and real stopped-torrent restore.

### Application Settings Persistence Boundary

- Audited SalixTorrent's file-backed durable state and selected application preferences as the next low-risk SalixORM integration boundary; session metadata remains JSON while fast-resume, cached metainfo, payloads, shell-handler backup and diagnostic-log formats remain purpose-built files.
- Added a generic `AppSettingsStore` boundary plus deterministic JSON reference/default implementation so `TorrentManager` no longer owns JSON file I/O directly.
- Added lazy application-settings backend selection with `SALIX_T_SETTINGS_BACKEND=json|salixorm` and optional `SALIX_T_SETTINGS_URL`, while normal runtime startup continues to avoid importing or requiring SalixORM.
- Added an optional file-backed SQLite settings adapter using released SalixORM `v0.2.0`, an explicit `application-settings-0001` migration, semantic metadata, unique setting keys, one-transaction full-snapshot saves and post-commit SQLite integrity/foreign-key checks.
- Preserved backward compatibility by allowing an existing `settings.json` snapshot to bootstrap an empty opt-in SalixORM store; the next normalized settings save makes the selected database authoritative without deleting or dual-writing the legacy JSON file.
- Made corrupt/incompatible SalixORM settings state fail closed and mark the active store unhealthy so later settings updates cannot silently overwrite the database with defaults.
- Added application-settings persistence regression coverage for JSON compatibility, lazy dependency loading, SalixORM save/reopen, metadata corruption, key replacement, legacy bootstrap, custom database targets and `TorrentManager` runtime integration.
- Added `SalixTorrent-Application-Persistence-Design.md` documenting the persistence inventory, selection criteria, settings pilot and the reasons session/resume/protocol-hot-path state remain separate.

### SalixORM Translation-Memory Storage

- Expanded the provider-neutral `TranslationMemoryStore` contract to cover iteration, statistics, audit and persistence operations actually consumed by localization tooling, with shared semantic entry validation and backend-neutral fail-closed merge behavior.
- Added one development-time translation-memory backend factory with deterministic JSON remaining the default/reference backend and optional `salixorm` selection through CLI/environment configuration.
- Added a file-backed SQLite translation-memory adapter built on released SalixORM `v0.2.0`, with explicit migration revisioning, source-locale metadata, unique semantic identities, placeholder/source-hash validation and post-save SQLite integrity checks.
- Made interrupted first-initialization states recoverable when only an empty SalixORM migration ledger or schema-without-semantic-data exists, while refusing missing metadata once entry rows exist.
- Preserved locale-generation failure atomicity by staging SalixORM memory mutations until `save()` and committing the complete pending set inside one explicit SalixORM `Session` transaction rather than durably writing each `put()`.
- Kept `SALIX_LOCALIZATION_MEMORY` backward-compatible as the JSON-memory path and added separate `SALIX_LOCALIZATION_MEMORY_BACKEND` / `SALIX_LOCALIZATION_MEMORY_URL` configuration for backend selection and SQLite URLs.
- Generalized memory bootstrap/status/audit/merge/plan/translation commands so the provider pipeline depends on the storage contract instead of constructing `JsonTranslationMemory` directly.
- Added offline JSON-to-SalixORM parity validation proving all 432 checked-in exact-source memory entries round-trip without semantic loss, while conflicting imports remain non-destructive.
- Added `--salixorm-memory-check`, tracked Windows `validate_salixorm_memory.bat`, and SalixORM-memory regression coverage for lazy optional dependency loading, migration history, persistence/reopen, source-locale/hash corruption refusal, no-network reuse and provider-failure no-partial-persistence behavior.
- Renamed temporary numbered localization tests, support modules, validation helpers and one-shot CLI checks to function-descriptive names so development checkpoint numbering does not persist in the maintained codebase.
- Kept SalixORM out of runtime localization and normal SalixTorrent runtime requirements; the new backend is optional development translation-memory storage and physical framework extraction remains deferred.

### Generic Runtime Kernel and Semantic Documentation Services

- Extracted catalog loading/fallback/formatting/pseudo-locale behavior into framework-neutral `LocalizationRuntime`, driven only by an injected `LocalizationProfile`, `CatalogRepository`, locale resolver and optional pseudo transform.
- Reduced `LocalizationManager` to a SalixTorrent singleton compatibility adapter while preserving existing `tr()`, diagnostics, direct catalog-test hooks and runtime behavior.
- Added generic semantic-document contracts and services (`JsonSemanticDocumentRepository`, `SemanticDocumentationSource`, `SemanticDocumentationService`) for stable Help/Glossary parsing and locale overlays without SalixTorrent resource paths or renderer dependencies.
- Reduced `app/localization/documents.py` to a SalixTorrent content-path/runtime adapter while preserving the historical Help/Glossary helper API.
- Extended `LocalizationProfile` with optional pseudo-locale metadata so generic runtime diagnostics no longer need application locale-info helpers.
- Expanded the framework extraction audit from four to six immediately extractable modules and added an explicit runtime/semantic facade-boundary audit.
- Added `--runtime-boundary-audit`, `--runtime-check` and tracked Windows `validate_runtime_boundaries.bat`.
- Added runtime/semantic-service regression coverage for generic runtime injection, fallback/placeholder contracts, semantic-document services, SalixTorrent compatibility and extraction boundaries.

### Framework Extraction Readiness

- Added framework-neutral runtime localization contracts (`LocaleDescriptor`, `LocalizationProfile`, `CatalogRepository`, `JsonCatalogRepository`) without SalixTorrent, Dear PyGui, runtime-path or translation-provider dependencies.
- Added an explicit SalixTorrent localization profile/resource adapter and routed runtime catalog parsing plus semantic-document content paths through that application boundary while preserving the existing `LocalizationManager`/`tr()` API.
- Generalized the JSON translation-memory backend so the canonical source locale is explicit rather than structurally fixed to `en-AU`; source-locale mismatches and cross-source-locale memory merges fail closed.
- Added an offline framework-extraction audit and map that distinguish immediately extractable modules from SalixTorrent application adapters and development/provider adapters.
- Added `--framework-report`, `--framework-audit`, and `--framework-check` plus tracked Windows `validate_framework_extraction.bat`.
- Added `SalixTorrent-Phase12-Framework-Extraction-Map.md` documenting dependency direction, extraction sequence, the optional SalixORM storage boundary and non-negotiable framework boundaries.
- Added framework-boundary regression coverage for profile/repository contracts, existing runtime compatibility, non-`en-AU` translation-memory operation, source-locale merge refusal, extraction auditing and offline CLI validation.

### Provider-Neutral Translation Memory Foundation

- Added a provider-neutral translation-memory service with deterministic JSON storage, exact canonical source hashes, placeholder contracts, provenance, model/status metadata and a storage interface designed for interchangeable backends.
- Added source-based memory identity independent of SalixTorrent localization keys while retaining semantic catalog separation (`ui`, `help`, `glossary`) to avoid unsafe reuse across unrelated text domains.
- Seeded the project memory from the existing source-hash-valid translation cache, deduplicating 452 key records into 432 reusable exact-source candidates (108 per target locale).
- Updated changed-only translation planning/generation to consult manual overrides, the project key cache, then reusable translation memory before invoking a provider; memory hits work in strict no-network mode and are adopted back into the key cache.
- Added a lazy development provider registry and explicit `--provider` selection; Google Cloud remains one registered network provider rather than the localization architecture itself.
- Added `--providers`, `--memory-bootstrap`, `--memory-status`, `--memory-path`, `--memory-merge` and `--memory-check` plus tracked Windows `validate_translation_memory.bat`.
- Added fail-closed memory merge/audit behavior for malformed hashes/placeholders and conflicting candidate translations.
- Added translation-memory regression coverage for source-based reuse, catalog separation, placeholder safety, merge conflicts, portable memory paths, memory-assisted no-network generation, provider registration and offline translation-memory validation.

### Translation Review Infrastructure

- Added provider-neutral review-state analysis that classifies every target-locale entry as missing, awaiting review, reviewed, locked, stale, or invalid without requiring any translation provider.
- Added deterministic offline review-bundle export with canonical source text, source hashes, placeholders, extraction/source locations, current translation, provider provenance, reviewer notes and editable review state.
- Added fail-closed review import: only entries explicitly marked `reviewed` or `locked` are promoted; stale canonical hashes, edited source text, broken placeholders, missing protected terms, unknown keys/catalogs and malformed review states abort the entire import before authoritative review metadata is written.
- Upgraded manual overrides to a backward-compatible rich schema carrying source hash, review/lock state, reviewer, note and review timestamp; reviewed/locked entries remain authoritative over machine/cache translations, including forced regeneration.
- Extended locale validation so reviewed overrides participate in source-hash freshness, placeholder, protected-term and packaging-consistency checks instead of being exempt from provenance validation.
- Added `--review-report`, `--review-export`, `--review-import` and `--review-check` commands plus tracked Windows `tools/localization/review_localization.bat` offline audit helper.
- Added translation-review regression coverage for review summaries, export context/provenance, reviewed and locked promotion, stale-source refusal, placeholder/protected-term refusal, review freshness validation and repository ignore policy.
- Kept manual language/content review explicitly dependent on populated locale packs; machine-translation population remains on hold.

### Validation and Packaging Hardening

- Added deterministic `app/localization/locales/manifest.json` metadata covering canonical/packaged entry counts, catalog hashes, script, text direction, font profile, support status and the development-only pseudo locale.
- Added strict catalog metadata/hash validation, source-hash freshness checks for packaged translations, and protected-technical-term preservation checks in addition to the existing placeholder and semantic-document validators.
- Hardened runtime locale loading so missing/corrupt target catalogs fail closed to canonical `en-AU` per key while structured catalog-health, fallback-reason, script/direction and font-profile diagnostics remain available.
- Added the in-memory `en-XA` pseudo locale for accent/expansion stress testing without network translation or a packaged pseudo catalog; `SALIX_T_PSEUDO_LOCALE=1` can force it for development smoke tests.
- Added offline pseudo-localization auditing, PyInstaller localization-resource contract checks, locale-manifest drift checking, and the one-shot `--offline-validation-check` command.
- Added tracked Windows `tools/localization/validate_localization.bat` preflight for extraction, deterministic drift checking and all offline localization hardening checks.
- Added localization-validation regression coverage for metadata capabilities, pseudo expansion/placeholder safety, corrupt-pack fallback, deterministic manifest generation, packaging contracts, stale translation detection, protected terminology and offline-validation CLI behavior.

### Initial Locale Generation Harness

- Added offline locale-generation status reporting for all four target packs, including packaged, source-hash-valid cache, reviewed override and missing-entry counts.
- Added a Google development setup doctor that checks client/auth availability, Application Default Credentials, project resolution, selected location/model, and an optional one-request authenticated API probe without exposing credential paths or secrets.
- Added `--generate-initial`, which refuses stale canonical extraction, runs changed-only generation, and requires strict completeness before declaring selected locale packs generated.
- Added the tracked Windows `tools/localization/generate_initial_locales.bat` helper with safe preflight, optional probe, and explicit credentialed `--run` modes.
- Kept Google credentials ignored while explicitly allowing the official locale-generation batch helper through the repository's broad `*.bat` ignore rule.
- Added locale-generation regression coverage for locale completeness reporting, non-mutating status, setup-doctor failure handling, stale-extraction refusal, strict post-generation validation, and credential-ignore policy.

### Changed-Only Translation Pipeline

- Added changed-only Google Cloud Translation v3 generation with `general/translation-llm`, Application Default Credential/project discovery, configurable model/location, bounded batching and transient retry handling.
- Added non-mutating `--dry-run` translation planning and strict `--no-network` rebuilding from source-hash-valid cache/manual overrides only.
- Upgraded `translation_cache.json` to a deterministic locale/catalog/key schema tied to the canonical extraction hashes and bootstrapped the existing 113 UI translations per target locale.
- Made reviewed manual overrides authoritative even under forced regeneration, with placeholder/protected-token validation before generated translations are accepted.
- Made translation generation fail safely: provider/auth failures occur before target locale artifacts are written, generated JSON uses atomic replacement, and the cache is committed last.
- Added translation-pipeline regression coverage for project discovery, protected-token round trips, cache bootstrap, changed-only translation, manual-override precedence, offline rebuilds, provider-failure rollback and credential-free dry-run planning.

### Development Extraction Tool

- Made canonical `en-AU` extraction fully reproducible from explicit source declarations rather than retaining stale generated catalog entries.
- Added deterministic `extraction_manifest.json` source hashes, source locations, placeholder/format contracts, duplicate-key reuse records, and dynamic `tr()` auditing.
- Added `build_locales.py --check` for non-mutating extraction drift checks and `--report` for extraction diagnostics.
- Added explicit `ui_static.json` for intentionally indirect canonical UI strings and centralized source-hash/placeholder contracts for extraction, validation, and translation tooling.
- Added extraction regression coverage for AST extraction, source hashes, duplicate conflicts, dynamic-call auditing, deterministic generation, and extraction validation.

### Added

- Phase 12 offline localization foundation with a bundled `LocalizationManager`, canonical `en-AU` fallback, `System Default`/explicit locale persistence, and initial `en-AU`, `en-GB`, `en-US`, `pt-BR`, and `fil-PH` locale packs.
- Development-only localization toolchain under `tools/localization/` for explicit `tr()` AST extraction, semantic Help/Glossary extraction, Google Cloud Translation generation, changed-string caching, protected technical terminology, manual overrides, and catalog/placeholder validation.
- Separate `requirements-localization.txt` so Google translation tooling is never required or bundled for normal SalixTorrent runtime/build use.
- Phase 12 localization diagnostics reporting requested/active/canonical locale, bundled catalog size, English fallbacks, format errors, and catalog health.
- Phase 12 regression coverage for locale normalization, offline fallback, translated UI loading, placeholder safety, developer extraction/protection tools, settings persistence, and PyInstaller locale packaging.
- Phase 12 presentation-only translation helpers for stable torrent states, priorities, protocol policies and combo values, keeping engine/persistence tokens locale-independent.
- Phase 12 UI-localization regression coverage auditing direct Dear PyGui user-facing literals, canonical-value round trips, CLI extraction and localization-aware `.gitignore` policy.
- Phase 12 renderer-neutral semantic documentation sources under `app/localization/content/`, with stable Help topic/section IDs, stable Glossary term IDs, and locale-neutral cross-links.
- Phase 12 semantic-documentation validation for duplicate/missing semantic IDs, broken related-term links, canonical catalog drift, and frozen-resource packaging.
- Phase 11 platform-neutral desktop integration controller with semantic tray actions, independent tray/window capability tracking and fail-safe hide/restore policy.
- Linux/BSD pystray desktop backend with X11 viewport hide/restore/focus support, backend capability reporting and desktop-notification fallback.
- macOS menu-bar backend with pystray plus AppKit window restore/activation and notification capability detection.
- Separate Close window to tray preference plus live tray/menu/notification/window-recovery diagnostics in Preferences, Help and Diagnostics.
- Phase 11 regression coverage for tray policy, capability snapshots, backend selection contracts, packaging dependencies and source/frozen lifecycle safeguards.
- Phase 10 centralized runtime-path policy for source, frozen installed and portable execution, removing process-working-directory assumptions from state, default downloads, UI error logs and documentation media resources.
- PyInstaller release specification plus Windows build script producing a windowed standalone `SalixTorrent.exe`, console `SalixTorrentCLI.exe`, and portable ZIP with `portable.flag`.
- Inno Setup 6 installer definition with per-user installation, Start Menu/optional desktop shortcuts, optional `.torrent` and `magnet:` integration, and clean unregister behavior.
- Dependency-free Windows shell integration commands: `--shell-status`, `--register-torrent-handler`, `--unregister-torrent-handler`, `--register-magnet-handler`, and `--unregister-magnet-handler`.
- Conservative `.torrent` OpenWith ProgID registration and opt-in `magnet:` ownership with previous-handler backup/restore protection.
- Phase 10 regression coverage for portable/frozen path behavior, cwd-independent defaults, resource resolution, shell command construction and packaging contracts.
- Phase 9 BitTorrent v2 peer networking, BEP-52 hash exchange, `btmh` magnets with verified piece-layer acquisition, v2-only transfers, dual-swarm hybrid operation, protocol provenance and v1/v2/hybrid torrent creation.
- Phase 9 real-wire regression coverage for v2 seeding/downloading, BEP-52 hash servicing, hybrid v1-to-v2 upgrade, btmh piece-layer acquisition and BEP-47 virtual padding.
- Phase 8 BEP-52 metainfo/SHA-256/file-tree/Merkle/piece-layer validation foundation.
- Phase 7 shared desktop/headless transfer-add architecture and clean headless lifecycle.

### Changed

- Phase 12 UI localization migrates the primary transfer/detail views, Preferences, dialogs, status/progress text, Create Torrent, completion notifications and human-facing CLI output to semantic `tr()` calls; structured/machine-readable data remains locale-independent.
- Canonical `en-AU` UI extraction now includes presentation values and currently produces 688 UI strings, while incomplete target locales continue to fall back offline to `en-AU` until translation generation is run.
- `.gitignore` now tracks the Phase 12 design document, locale catalogs, manual overrides, protected terminology and deterministic translation cache while excluding localization credentials and retaining existing build/payload/local-test exclusions.
- Windows tray/menu commands, the main application menu/toolbar, core Desktop preferences, Help/Glossary shell navigation and diagnostics now consume semantic localization keys while preserving stable internal protocol/state values.
- Semantic Help topics and the shared hover-help glossary can now be overlaid from bundled locale catalogs without changing topic/term IDs, renderer structure, links or layout policy.
- Canonical Help/Glossary prose no longer lives in Dear PyGui view modules: `help_topics_view.py` and `help_terms.py` now consume semantic source documents through `app.localization.documents`, while locale catalogs overlay wording by stable IDs.
- Help section translation keys now use explicit stable section IDs instead of list positions, so article reordering or heading translation does not invalidate existing locale entries.
- Windows tray actions now restore, raise and focus the Dear PyGui viewport, and tray lifetime is monitored so source and frozen builds share the same recovery behavior.
- System-tray and native-notification preference wording is platform-neutral and unsupported desktop controls are capability-gated instead of silently accepting unusable settings.
- The CMD `packaging/build_windows.bat` workflow is tracked as the primary Windows release builder while the PowerShell builder remains available.
- New installations no longer derive their default download directory from the process working directory; installed profiles default to the user's Downloads/SalixTorrent folder while portable profiles default beside the executable.
- UI error logging and application state now share one centralized state-directory policy.
- Documentation image resources resolve relative to the application/bundle instead of the launch working directory.
- `TorrentFile`, `TorrentSession`, storage verification, tracker/DHT/PEX discovery and torrent creation are generation-aware across v1, v2 and hybrid metainfo.

### Fixed

- Windows Phase 11 viewport binding no longer depends on a non-portable Dear PyGui native-handle accessor: the Win32 backend discovers the real top-level SalixTorrent HWND by process, subclasses its native window procedure for close/minimize events, and binds that HWND to the tray backend.
- Windows tray `Open SalixTorrent` now performs native restore/foreground activation while servicing the tray user action, with a main-thread restore fallback, so source and frozen builds share the same focus path.
- `Open SalixTorrent` from the Windows notification-area menu now performs an explicit restore/raise/focus sequence rather than only making the viewport visible.
- Minimize/close-to-tray can no longer hide SalixTorrent when no live recoverable tray is available; tray `Exit` always performs a real shutdown.
- Frozen launches from Start Menu shortcuts, Explorer `.torrent` handlers or `magnet:` protocol handlers cannot accidentally place writable state/download defaults in an unrelated working directory.
- Hybrid BEP-47 padding remains virtual storage while still being serviceable to v1 peers, and v2 disk recheck uses generation-aware verification rather than a hard-coded SHA-1 assumption.

## v0.3.0 - 2026-08-31

### Added

- Generic framework property-cascade resolver with an explicit `UNSET` inheritance sentinel, Default/Theme/Instance provenance, per-property validation fallback, and rejected-candidate diagnostics.
- Phase 6.5 documentation-layout policy split with hard-coded safe framework defaults, sparse `DocumentationLayoutTheme` overrides, sparse per-`DocPage` `DocLayout` instance overrides, and independent margin/padding/document/title/media alignment properties.
- Runtime documentation constraint geometry that preserves valid configured values while temporarily fitting them to smaller parent bounds instead of treating responsive contraction as invalid configuration.
- Inspectable documentation layout snapshots exposing configured values, property source layers, rejected candidates, and effective document/content rectangles for programmatic theme development.

- Phase 6.5 semantic Documentation subsystem with renderer-neutral `DocPage`/section/paragraph/link/callout/code/media models and a Dear PyGui renderer.
- Parent-relative `ContentBounds` geometry and horizontal/vertical alignment primitives so reusable components can align inside their current pane instead of assuming viewport coordinates.
- Semantic documentation typography roles for page titles, leads, section/subsection headings, body text, captions, code and index headings, backed by pre-registered scalable font sizes.
- Independent Documentation Scale preference (90/100/115/130%) plus an in-Help scale control; document hierarchy scales together without enlarging data tables/toolbars.
- Centered bounded-width documentation composition: page titles center within the current readable content rectangle and long body text keeps a capped reading measure on wide monitors.
- Reusable documentation icon/callout and rich-media plumbing with portable ASCII icon fallback, lazy responsive static-image textures, captions/alt text, and graceful animation/video fallback until timed playback is implemented.
- Documentation subsystem regression coverage for content bounds, semantic typography hierarchy, scale normalization, media aspect-ratio fitting and renderer-neutral models.

- Reusable event-driven `ResponsiveLayout` service for Dear PyGui viewport/item resize dispatch, memoized geometry writes, proportional splits, fill regions, and resizable-dialog content anchoring.
- Responsive geometry regression tests covering bounds, proportional split allocation, narrow-window fallback, and growable content-height calculations.
- BEP-48 HTTP/HTTPS tracker scrape support with standards-derived scrape endpoints, repeated `info_hash` parameters, and bounded multi-torrent batching.
- BEP-15 UDP tracker scrape action support with bounded multi-info-hash datagrams and connection-ID reuse across batches.
- One application-wide timer-driven scrape coordinator that groups active torrents by tracker, caches results, and avoids UI-driven or per-torrent scrape polling.
- Per-tracker scrape telemetry for seeds, leechers, cumulative completed downloads, scrape status/age/latency, endpoint, protocol, and batch size.
- General, Sources, Properties, Diagnostics, Help Topics, and Glossary coverage for scrape S/L/C statistics and batching semantics.
- Dual-stack BitTorrent peer networking with explicit IPv4/IPv6 listeners, outbound peer TCP, family-aware endpoint telemetry, and bracket-safe IPv6 display formatting.
- IPv6 tracker support through BEP-7 `peers6`, IPv6 UDP tracker announces/responses, and concurrent per-family tracker announces with one stable session key.
- IPv6 Peer Exchange using BEP-11 `added6`/`dropped6` compact endpoints.
- IPv6 DHT participation using BEP-32 `nodes6`, family-appropriate `want` requests, hybrid compact-peer parsing, and separate IPv4/IPv6 UDP telemetry.
- IPv6-aware network-interface/VPN binding and Interface Lock diagnostics, including an `IPv6 Direct` state that distinguishes routed IPv6 from IPv4 NAT mapping.
- Bounded 64 MiB asynchronous piece write-behind pipeline with one sleeping disk worker, byte-level backpressure, and fail-closed disk-write error handling.
- Bounded 32 MiB recent-piece LRU cache plus pinned pending-piece reads so freshly verified data can be seeded without immediate read-after-write disk I/O.
- O(1) disk telemetry for queued bytes/writes, write latency, backpressure events/time, cache usage/hits/misses, completed writes, and failures.
- Explicit per-peer outstanding block-request ownership with a reverse index for O(pipeline-size) cleanup on choke, disconnect and timeout.
- Bounded Endgame Mode for the final 32 wanted blocks, including duplicate tail requests, targeted peer-wire `CANCEL` frames, and received-CANCEL handling for pending uploads.
- Adaptive per-peer request pipelines (8-64 blocks) with sent-request timeout and immediate stalled-block reassignment.
- Incremental per-piece peer-availability accounting driven by BITFIELD, HAVE, and disconnect events.
- File-priority-preserving rarest-first piece scheduling with randomized equal-rarity tie-breaking.
- BitTorrent MSE/PE peer transport with `Disabled`, `Prefer Encryption`, and `Require Encryption` policies; `Prefer Encryption` is the default.
- RC4-protected MSE incoming and outgoing peer streams, with fresh-connection plaintext fallback only under `Prefer Encryption`.
- Dependency-free internal RC4 stream implementation for MSE/PE; the existing project requirements remain sufficient.
- Network-interface/VPN source binding for peer TCP, the incoming listener, HTTP/UDP trackers, DHT, LPD, and magnet metadata retrieval.
- Optional Interface Lock / kill switch that fails a torrent closed if its selected local address disappears.
- Per-peer and per-session transport-security telemetry (`MSE/RC4` versus `Plaintext`).
- Optional display-only peer IP masking, disabled by default.
- Transport/privacy Preferences controls and expanded Help/Glossary documentation.
- Event-driven seeding telemetry for uploaded-this-session bytes, received/served upload requests, last successful PIECE upload, and active/this-session incoming peers.
- Exact listener-endpoint reporting plus separate UPnP and NAT-PMP result diagnostics.
- Structured incoming-connectivity diagnosis with mapping stage/result codes, actionable next-step guidance, and conservative public/private/Shared-CGNAT external-address classification.
- Offline Help/Glossary coverage for tracker timeouts, mapping diagnosis, manual port forwarding, double NAT, CGNAT, and external-address scope.

### Changed

- SalixTorrent's active Help/Glossary layout theme now widens the framework's conservative 980 px default reading measure to 1180 px with smaller inner insets, reducing excessive dead margin while page titles remain centered inside the resolved content bounds.
- Documentation visual tokens and geometry policy are now separate concerns: `DocumentationTheme` owns colors/spacing while `DocumentationLayoutTheme`/`DocLayout` own responsive geometry.

- The entire Help Topics and Glossary detail pane now renders through the Documentation subsystem; topic titles are visually significant centered page headings, section hierarchy is semantic, related links share one component, and glossary definitions use the same document renderer.
- Help content no longer maintains an ad-hoc list of wrapped text widgets; one resize-event-driven renderer reapplies cached content bounds, wrapping, anchoring and typography only when geometry or documentation scale changes.
- Global UI font registration now covers the bounded semantic size range once at startup, allowing item-level document roles without runtime font-atlas rebuilds.
- Diagnostics now reports Interface Text Size, Documentation Scale and the selected scalable UI font for presentation troubleshooting.

- Primary application scenes now occupy the available viewport region as real child workspaces instead of fixed-content groups, allowing native-style expansion and scrolling.
- Active Transfers now gives additional height to the queue on tall windows, lets the detail workspace consume the remaining area, expands Peers/Pieces/Files/Sources/Speed tables and plots, and proportionally resizes the General panels with live wrap widths.
- Create Torrent now grows the tracker editor with available vertical space; Preferences uses responsive two-column widths and adaptive field/text wrapping; Help uses a responsive navigator/content split.
- Diagnostics, Torrent Properties, and Open Magnet are resizable data dialogs whose growable content keeps their action rows attached to the lower content boundary. Small destructive confirmations and transient notices remain intentionally fixed-size.
- Help text wrapping is now driven by resize events instead of checking pane geometry every UI frame.
- Tracker announce health and tracker scrape statistics are now represented independently so a scrape timeout/unsupported endpoint cannot make an otherwise healthy discovery source look failed.
- Sources now exposes scrape S/L/C alongside announce-derived Swarm S/L and summarizes scrape active/pending/warning/error state separately.
- Manual tracker refresh also schedules a coalesced scrape refresh, while normal scrape refreshes use one shared low-frequency timer.
- Any-interface torrent sessions now use IPv4 and IPv6 concurrently where available, while a specific address bind remains fail-closed to that address family.
- BEP-32 DHT selects a concrete route-derived IPv6 source address under Any interface and skips IPv6 DHT cleanly when no routable IPv6 source exists.
- Tracker Sources telemetry now records returned IPv4/IPv6 peer counts and the address families used for the latest announce cycle.
- BEP-14 Local Peer Discovery is explicitly disabled under an IPv6-only bind because the protocol is IPv4 multicast.
- Verified piece filesystem writes and resume-state fsync work now run away from the asyncio peer/UI hot path; torrent completion waits for the bounded disk queue to flush.
- Fast-resume metadata now records only persisted pieces, while verified-but-buffered pieces remain temporarily uploadable from memory.
- Pieces telemetry now exposes scheduler mode, wanted blocks remaining, outstanding wire requests, and endgame duplicate counts without adding a polling loop.
- Download workers refill bounded pipelines in small bursts and start request timeout clocks only after REQUEST frames are actually transmitted.
- Pieces telemetry now reads the incremental availability cache instead of rebuilding availability by rescanning every connected peer bitfield.
- Download block selection now uses cached rarity buckets rather than sequentially scanning pieces from index zero.
- Tracker announces advertise encrypted-peer support and request encrypted peers when `Require Encryption` is selected.
- Changing the selected network path or peer-encryption policy closes existing torrent sockets so subsequent connections use the new policy.
- Incoming connectivity now tracks every active torrent listen port independently instead of exposing one global port as if it belonged to every torrent.
- General transfer wording now distinguishes persisted `Uploaded Total` from process-local `Uploaded This Session`, and `Active Time` from wall-clock age.
- Finite UPnP/NAT-PMP mapping leases are renewed before expiry using one shared low-frequency timer for all active ports rather than a polling loop per torrent.
- Sources telemetry now separates neutral pending states from amber timeout warnings and red source errors instead of grouping them together as generic problems.
- NAT-PMP diagnostics decode standard gateway result codes; UPnP diagnostics preserve the failing discovery/SOAP stage and router fault code when available.

### Fixed
- Dear PyGui item-resize callbacks now expose only the standard sender/app_data/user_data signature under manual callback management; responsive window resizing no longer crashes `dpg.run_callbacks()` with `IndexError: tuple index out of range`.
- UDP tracker timeouts now remain source-local Timeout warnings through dual-stack address failover instead of being wrapped and misreported as protocol Errors.
- Sources labels the primary state column as Discovery and tracker help distinguishes announce status from independent scrape status.

- Windows Proactor shutdown no longer prints a traceback for the expected `ConnectionResetError` / WinError 10054 case when a remote peer resets its TCP connection during application teardown; unrelated asyncio exceptions remain visible.
- IPv6 DHT `values` parsing now accepts the BEP-32-required hybrid list containing both 6-byte IPv4 and 18-byte IPv6 peer entries.
- IPv6-bound sessions no longer attempt unrelated IPv4 UPnP/NAT-PMP mappings that could violate the selected network path.
- Slow storage can no longer block the peer event loop during verified-piece writes; bounded asynchronous backpressure limits memory growth instead.
- A disk write failure no longer leaves buffered-only pieces represented as safely completed resume data.
- Starting a second active torrent no longer removes the UPnP/NAT-PMP mapping belonging to the first torrent.
- Stopping or rebinding a torrent releases only that torrent listener's router mapping.
- General/Diagnostics connectivity reporting now follows the selected torrent's actual listen port, preventing another torrent's mapping from being shown as its own.
- A failed router-lease refresh now retains the previous mapping while retrying instead of deleting a still-valid mapping first.
- UPnP gateways that reject finite leases with `OnlyPermanentLeasesSupported` are retried with a permanent mapping rather than being reported as simply unmapped.
- NAT-PMP lease scheduling now respects the lifetime actually returned by the gateway instead of assuming the requested lifetime was granted.

## v0.2.0 - 2026-08-26

### Added

- Persistent multi-torrent session restoration and queue ordering.
- Fast-resume state with background SHA-1 checking and live checking progress.
- Seeding, external-source seeding, and upload telemetry.
- Bidirectional peer connections so verified pieces can be uploaded while downloading.
- HTTP/HTTPS and UDP tracker telemetry and manual tracker refresh.
- DHT (BEP-5), PEX (BEP-10/BEP-11), and Local Peer Discovery (BEP-14).
- BitTorrent v1 magnet support with BEP-9 metadata retrieval and metadata serving.
- Create Torrent workflow for files and directories.
- Multi-file storage views and selective per-file download priorities.
- Torrent High/Normal/Low queue priorities, Move Up/Move Down ordering, and active download slots.
- Per-torrent and global upload/download bandwidth limits.
- General, Peers, Pieces, Files, Sources, and Speed detail views.
- Compact piece map and per-piece/per-peer/source telemetry.
- Traditional application menu, keyboard shortcuts, diagnostics, properties, and expanded context actions.
- Persistent Preferences view with networking, queue, bandwidth, desktop, and display settings.
- UPnP/NAT-PMP automatic mapping attempts and incoming-connectivity reporting.
- Configurable transfer-rate display units: Automatic, KB/s, MB/s, kbps, and Mbps.
- Comprehensive contextual hover help.
- Searchable CHM-style Help Topics view and A-Z glossary.

### Changed

- File loading, checking, peer handling, and Dear PyGui refresh paths were moved away from blocking UI work.
- Live UI telemetry is coalesced/rate-limited so hidden or stale detail views do not freeze the interface.
- Remote peer disconnects are treated as normal swarm churn rather than unhandled asyncio errors.
- Private torrents no longer use public fallback trackers and disable DHT, PEX, and LPD discovery.
- UI-facing typography uses ASCII-safe separators for consistent rendering with the bundled/current monospace font.

### Fixed
- Dear PyGui item-resize callbacks now expose only the standard sender/app_data/user_data signature under manual callback management; responsive window resizing no longer crashes `dpg.run_callbacks()` with `IndexError: tuple index out of range`.

- Torrent file-picker delays and inconsistent transfer controls after newly loading a torrent.
- Pause/Stop/Resume behaviour while checking or downloading.
- Stale UI snapshot backlogs when switching views.
- Win32 tray callback pointer-width errors on 64-bit Windows.
- Tooltip parent/container-stack corruption in Dear PyGui.
- Help Topics navigation callbacks that highlighted entries without updating the content pane.
- Upload-speed reporting while the session is in Downloading state.

## v0.1.0

Initial development baseline: custom bencode/metainfo parsing, basic tracker/peer-wire download path, piece verification, and the first Dear PyGui transfer interface.
