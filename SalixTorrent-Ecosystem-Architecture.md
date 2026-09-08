# SalixTorrent Ecosystem Architecture Direction

**Status:** post-v0.5.0 development direction
**Reference release:** SalixTorrent v0.5.0
**Development branch:** `dev`
**Purpose:** guide reverse-pyramid extraction from the working SalixTorrent application into a modular application ecosystem without freezing names or public APIs before the boundaries are proven.

---

## 1. North star

SalixTorrent is both a production BitTorrent application and the primary proving ground for a broader application-development ecosystem.

The long-term goal is not only to extract a reusable widget library. The project is intended to yield three cooperating layers:

1. a reusable **application engine/runtime** that knows how to start, run, supervise and shut down an application;
2. an optional **RAD/application framework** that provides reusable presentation, composition, data and visualization facilities;
3. a future **WYSIWYG RAD environment** that uses the same engine and framework to create new applications visually.

The desired project experience is closer to creating a blank Windows Forms or Unity project than assembling unrelated infrastructure from scratch. A new project should inherit the application/runtime machinery it needs, then opt into presentation and capability modules appropriate to that project.

Current names such as `app.framework`, `Component`, `Dialog`, `LayoutHost`, `SceneManager`, and other extraction-era identifiers remain working names. They are not a frozen external API.

---

## 2. One ecosystem, modular capabilities

Cohesion and modularity are both requirements.

The ecosystem should feel like one family of cooperating modules, while allowing applications to depend only on the capabilities they need.

Conceptually:

```text
Application / Project
        |
        +-- product/domain code
        |
        v
RAD / Application Framework                    optional
        |
        +-- components
        +-- forms and composition
        +-- layout and documentation
        +-- live tables / state views
        +-- visualization / realtime graphs
        +-- validation and explicit bindings
        |
        v
Application Engine / Runtime                   reusable
        |
        +-- lifecycle and shutdown
        +-- services and scheduling
        +-- events / task ownership
        +-- resources and runtime paths
        +-- presentation-host selection
        +-- input/window integration
        +-- networking/runtime awareness
        +-- persistence integration points
        |
        v
Backend / Platform Adapters
        |
        +-- Dear PyGui                         current reference GUI backend
        +-- Tkinter                            validated compatibility GUI backend
        +-- headless / CLI                     already proven presentation mode
        +-- OS-specific desktop/network adapters
        +-- future GLFW/OpenGL or other backends where justified
```

SalixORM is a separate reusable ecosystem library rather than a hidden dependency of every application. Applications should continue to opt into it only where transactional/schema-managed persistence is the right abstraction.

---

## 3. Execution profiles

The engine must not require a GUI merely to exist.

Three execution profiles are the immediate architectural target:

### Reference desktop

```text
engine/runtime
+ RAD framework
+ Dear PyGui presentation backend
```

Dear PyGui remains the preferred and most capable desktop implementation while the ecosystem is being extracted from SalixTorrent.

### Compatibility desktop

```text
engine/runtime
+ RAD framework
+ Tkinter presentation backend
```

Tkinter is the validated standard-library-compatible compatibility implementation for the common desktop surface. It proves that framework contracts can be implemented without Dear PyGui while keeping application definitions backend-neutral.

Tkinter is **not** a complete SalixTorrent presentation rewrite and this tranche does not claim feature parity with Dear PyGui. The compatibility backend is introduced incrementally behind the same framework-facing contracts and is first proven by the product-neutral blank-application example.

### Headless / CLI

```text
engine/runtime
+ nonvisual services/framework modules
+ no graphical backend
```

This mode already has a strong proof in SalixTorrent: `main.py` defers desktop imports, and `app/cli/headless.py` consumes structured engine events without importing Dear PyGui.

Headless operation is a first-class target, not a degraded GUI mode.

---

## 4. Presentation backend policy

Backend neutrality does not mean every backend must provide identical capabilities or performance.

The preferred rule is:

> Applications depend on semantic framework/engine contracts. Backends implement those contracts and advertise capabilities. Application code should not branch on Dear PyGui versus Tkinter for ordinary framework behavior.

A future presentation-backend aggregate may coordinate several smaller contracts such as:

```text
component renderer
layout host
window host
plot host
input host
dialog host
image/texture host
capability set
```

The exact aggregate and names are deliberately deferred until a second GUI backend provides evidence about the real boundary.

Backend selection and hardware acceleration are separate concerns. A future `--ui-backend`-style option may select Dear PyGui, Tkinter or headless operation; an acceleration setting should describe actual rendering acceleration and must not be used as a synonym for choosing a UI toolkit.

No such new command-line backend selector is implemented by this document.

---

## 5. Application-engine extraction goal

The application engine should eventually be reusable as an intact runtime layer that a newly created project can inherit.

The engine is expected to own generic concerns such as:

- application startup and orderly shutdown;
- composition-root ownership;
- service registration/lifecycle;
- scheduling, timers and background-task ownership;
- application-level events;
- scene/view lifecycle contracts where they prove generic;
- presentation backend installation and teardown;
- window/runtime host integration;
- input integration;
- resource and runtime-path services;
- generic desktop capabilities and notifications;
- generic networking/runtime awareness;
- persistence integration points;
- diagnostics and failure isolation.

SalixTorrent currently contains useful engine candidates, but several are still coupled to Dear PyGui or product behavior. `GuiEngine`, `MasterViewport` and `SceneManager` are therefore extraction inputs rather than finished generic APIs.

The goal is not to copy those modules unchanged. The goal is to separate their reusable runtime mechanics from concrete Dear PyGui and SalixTorrent ownership.

---

## 6. RAD/framework extraction goal

The framework sits above the runtime and describes reusable application construction and presentation.

v0.5.0 already proved a substantial foundation:

- backend-neutral component primitives and composites;
- semantic sizing and component layout profiles;
- explicit value binding;
- renderer-neutral events;
- explicit component disposal/state operations;
- semantic documentation contracts;
- pure geometry;
- responsive coordination through an injected layout host;
- package-relative imports and relocation tests.

Post-v0.5.0 extraction should broaden that foundation before any final public API or naming freeze.

Priority candidates include:

- realtime time-series data;
- rolling history and statistics;
- renderer-neutral plot/graph descriptions;
- live/refreshable table models;
- state-grid / heat-map style visualizations;
- generic status/diagnostic panels;
- reusable master/detail presentation patterns;
- richer resource/image abstractions;
- validation/property metadata needed by a future designer.

Complex SalixTorrent views should not be wrapped cosmetically. A subsystem moves only when its reusable semantics are clear.

---

## 7. Immediate extraction candidates in current SalixTorrent

### 7.1 Realtime speed/telemetry view

`app/views/speed_view.py` is currently a concrete Dear PyGui view. It combines several concerns that should be separated:

```text
SalixTorrent transfer telemetry
        |
        v
generic rolling/time-series model
        |
        v
generic realtime graph contract
        |
        +-- Dear PyGui plot adapter
        +-- Tkinter Canvas adapter       prepared in ecosystem tranche 3
```

Likely reusable concepts include:

- timestamp/age-based samples;
- bounded rolling windows;
- multiple named series;
- current/average/peak statistics;
- reference/limit lines;
- semantic axis metadata;
- visible-window filtering;
- automatic plot-range calculation.

Torrent-specific rate units, labels, help terms and the source `speed_view` snapshot remain application concerns unless a more general contract emerges.

### 7.2 Network/runtime awareness

`app/logic/network_binding.py` already contains broadly reusable mechanisms such as IP normalization, family detection, endpoint formatting, interface discovery and bind-availability checks.

Those mechanisms are candidates for an engine/network capability module.

BitTorrent-specific routing policy, DHT recommendations, peer/listener behavior, tracker semantics, MSE/PE, PEX and seeding interpretation remain SalixTorrent responsibilities.

The extraction rule is:

```text
generic mechanism -> engine/runtime
protocol/product policy -> SalixTorrent
OS-specific implementation -> platform adapter
```

### 7.3 Application lifecycle and presentation host

`GuiEngine`, `MasterViewport` and `SceneManager` currently demonstrate working lifecycle, view switching, renderer setup, callback serialization, responsive refresh and shutdown integration, but they still know Dear PyGui directly.

They should be audited for:

- reusable application lifecycle;
- presentation-host ownership;
- scene/view registration and activation;
- backend installation;
- main-loop/update integration;
- teardown ordering.

A Tkinter implementation should consume the same higher-level contracts rather than requiring a second application architecture.

### 7.4 Desktop/platform services

`DesktopIntegration`, shell integration, runtime-path handling, notifications and native window behavior already contain reusable platform ideas. They should be split only where a generic application contract can be stated without SalixTorrent policy.

### 7.5 Rich live views

Peers, Pieces, Sources and the transfer queue should be audited for reusable patterns such as:

- stable row identity;
- incremental high-frequency updates;
- filtering/sorting;
- live master/detail selection;
- bounded large-state visualization;
- status/health presentation.

These are candidates, not promises. Protocol-specific meaning stays in SalixTorrent.

---

## 8. Reverse-pyramid extraction rule

For every useful subsystem discovered in SalixTorrent, classify it before moving code.

### Product/domain-specific

Examples:

```text
BitTorrent piece verification
tracker/DHT/PEX semantics
torrent seeding policy
.torrent creation
peer-wire behavior
```

Keep it in SalixTorrent.

### Generic application runtime

Examples:

```text
application lifecycle
service lifecycle
timers/scheduling
network interface discovery
generic notifications
resource lookup
presentation-host ownership
```

Move toward the engine/runtime.

### Reusable application presentation

Examples:

```text
forms
components
realtime graphs
live tables
state grids
documentation rendering contracts
status panels
```

Move toward the RAD/framework.

### Backend/platform implementation

Examples:

```text
Dear PyGui widget/plot calls
Tkinter widgets/Canvas
Win32 window control
GLFW window/context handling
OpenGL drawing
```

Keep behind adapters.

If a proposed abstraction merely renames one backend's API, leave it in the backend until another implementation proves the generic contract.

---

## 9. WYSIWYG RAD editor destination

The eventual RAD editor is not merely a visual wrapper around Python source. It requires a describable application model.

Future designer prerequisites are expected to include:

- a component/type registry;
- property metadata;
- serializable component hierarchy;
- stable object identity;
- parent/child composition rules;
- selection and inspector state;
- drag/drop and reparent operations;
- command-based mutations;
- undo/redo;
- copy/paste;
- project documents and versioned project schema;
- preview/runtime bridge;
- build/run integration.

The designer should itself be built using the same engine and framework wherever practical. That makes it a second demanding reference application and prevents the ecosystem from being designed only around SalixTorrent.

Designer metadata should not be bolted onto every runtime component prematurely. It should be introduced when the underlying component/engine contracts are stable enough to describe faithfully.

---


### Mixed layout composition

The future RAD designer must support both structured layout and direct placement without forcing an entire window to choose one geometry model. Layout policy is therefore **container-local**: each region owns how its direct children are arranged, while regions themselves remain ordinary children of a larger layout.

A valid application can therefore compose layouts such as:

```text
Application Window
+-- flow/stack region
|   +-- transfer queue table
|
+-- split region
    +-- tabbed detail region
    |   +-- flow/grid content
    |   +-- a local explicit-position panel
    |
    +-- file tree / rendered viewport region
        +-- future 2D/3D surface
```

The rule is deliberately not "automatic layout or absolute layout". It is "choose the right layout strategy for each local container and nest them freely." A designer should be able to drag a structured table into one region, place a tab container beside it, and put one widget at an explicit `(x, y)` inside a bounded panel without converting the surrounding application into pixel-positioned coordinates.

The first runtime proof is intentionally small: `PositionedPanel` is a normal component container whose direct children receive explicit local coordinates through the renderer's `place(...)` contract. `Placement` holds non-negative parent-local `(x, y)` plus margins, and `PlacedComponent` can wrap any ordinary component—including another `PositionedPanel`—so the parent still places the wrapper structurally while the child receives a local offset inside that assigned content space. Parent padding/margins therefore translate the child's coordinates naturally instead of turning them into window-global pixels.

Explicit placement also participates in measurement in this first pass. A placed child's occupied extent is its local offset + margins + measured/declared child size. `PlacedComponent` reserves that extent, and `ControlGrid` consumes the wrapper's semantic size hint so an affected column can grow to fit content placed at, for example, `(200, 100)` rather than clipping or overlapping it. Row height likewise follows the wrapper's reserved physical extent. A `PositionedPanel` can itself contain automatic layouts, and an automatic grid can contain a positioned panel; layout strategies are recursively nestable.

Dear PyGui translates local placement through its item-position API; Tkinter translates it through `place()` only inside the bounded positioned region. This is a foundation, not the final designer layout API.

The next structural proof adds two more local strategies rather than inventing a global form layout. `TabContainer`/`TabPage` provide keyed tab regions, while `SplitPanel`/`SplitPane` divide one region horizontally or vertically using weights, per-pane minimums and responsive reflow through `LayoutCoordinator`. Non-measuring overlay placement is also explicit: an overlay still uses parent-local coordinates but reports no occupied extent, so HUD labels, decorations, drag handles or similar surfaces need not enlarge the surrounding structured layout.

SalixTorrent itself now supplies the proof rather than relying only on the blank application: Download detail pages use the generic tab contract, Download General uses a three-pane split, and Help uses both a Contents/Glossary tab container and a two-pane index/document split. These structures remain recursively nestable with automatic controls and positioned panels.

The first designer-geometry pass now adds parent-local anchors and constraints without changing that rule. `AxisAnchor` selects start/centre/end/stretch independently per axis, `AnchoredPlacement` resolves edge offsets from its margins, and `SizeConstraints` bounds the resulting width/height. A `PositionedPanel` can watch its rendered size through `LayoutCoordinator` and reflow anchored children without exposing toolkit resize callbacks. Fixed and anchored placement objects also emit JSON-safe descriptors that can be restored without a GUI backend.

Future passes should add richer geometry only when proved by real application/editor surfaces: percentages and relationship constraints, tree/list/detail composition, interactive split handles, designer resize handles, and eventually full component/property/hierarchy documents. Margins/padding remain useful for structured flow, but explicit placement must always remain available locally when a design requires it.

## 10. Branch and release discipline

`main` is the stable/release line.

The `v0.5.0` release is the rollback boundary before the broader ecosystem extraction.

Active post-v0.5.0 work occurs on:

```text
dev
```

Development policy:

```text
main
    stable/released checkpoints

dev
    engine extraction
    framework extraction
    second-backend work
    telemetry/visualization work
    RAD/designer prerequisites
```

`dev` should merge back into `main` only after a deliberate release/integration gate. Short-lived feature branches can be introduced later when parallel or especially risky experiments justify them; they are not required for every tranche.

---

## 11. Planned extraction sequence

The sequence is architectural rather than calendar-driven.

### Stage A — inventory and ownership map

The initial ownership map is now established for the first extraction candidates: Speed telemetry/plotting, network/runtime awareness, application lifecycle/presentation hosting, desktop/platform services, and rich live-data views. The inventory remains a living audit as deeper seams are discovered. Record why each candidate belongs to a layer before moving it.

### Stage B — realtime data and visualization

The first implementation tranche is complete, Windows-validated, committed and pushed on `dev` at `ef8b4be998a714a86455940d8642fdd926a6609d`. Backend-neutral rolling telemetry/statistics and realtime graph coordination live in the provisional framework, while Dear PyGui plot operations live in a concrete plot host. SalixTorrent's existing Speed snapshot/labels/rate semantics remain application-owned. Ecosystem tranche 3 now provides a Tkinter Canvas implementation that consumes the same plot-facing contract rather than duplicating application logic.

### Stage C — engine/runtime services

The second implementation tranche is complete and pushed at `8e707efeb0cda162ee038a028a39a77663c2fa4e`. A standard-library-only `app/runtime/` package now owns explicit application/service lifecycle, scene registration, generic failure reporting, parameterized runtime paths, and generic dual-stack interface/address/source-binding mechanisms. Dear PyGui scene visibility remains a concrete engine adapter and BitTorrent network policy remains in SalixTorrent. The same `ApplicationRuntime` drives desktop and headless lifecycle.

### Stage D — second GUI implementation

The third implementation tranche is completed and pushed as a real second-backend proof rather than an interface exercise. Tkinter implements the common component, responsive-layout, scene, and realtime-plot contracts. Small Dear PyGui/Tkinter/headless presentation bundles and application hosts keep toolkit loops outside the runtime. `examples/ecosystem_blank_app.py` runs one product-neutral component/graph definition through either GUI backend and the same runtime headlessly.

This remains a compatibility surface, not a wholesale Tkinter rewrite of SalixTorrent and not a feature-parity promise.

### Stage E — rich RAD presentation

This stage is substantially proven. Tranche 4 extracted keyed live tables and categorical state grids; Tranche 5 added backend-neutral data projection, selection and command-state semantics; Tranche 6 added physical Dear PyGui/Tkinter command-menu hosts, stable generic item-order operations and parent-aware explicit placement; Tranche 7 added keyed tab regions, responsive weighted split regions and non-measuring overlays and migrated real Download/Help structures onto those contracts. Richer status/diagnostic surfaces, interactive table hosts and additional structural containers remain candidates only where the application demonstrates reusable semantics.

### Stage F — designer prerequisites

This stage is now active. Tranche 8 begins with geometry that a future designer can describe faithfully: parent-local start/centre/end/stretch anchors, minimum/maximum size constraints, optional split-pane maximums and JSON-safe fixed/anchored placement descriptors. The mixed-layout rule remains fundamental: designer geometry metadata is local to a container strategy rather than assuming that a whole form uses one universal table/grid or one universal absolute-coordinate plane. Component/property metadata, hierarchy documents, command-based edits and undo/redo remain later Stage-F work.

### Stage G — naming, API and package boundaries

Only after the wider engine/framework surface has been proven with multiple applications/backends should the project:

- choose final ecosystem/package names;
- freeze a supported public API;
- split repositories/packages where useful;
- remove compatibility facades deliberately;
- publish project templates/tooling.

---

## 12. Conditions before a public API freeze

Do not freeze names merely because the current code is relocatable.

A naming/API pass becomes appropriate when most of the following are true:

- the reusable engine lifecycle is separated from SalixTorrent;
- Dear PyGui is a concrete backend rather than an architectural assumption;
- a meaningful Tkinter compatibility slice implements the same contracts;
- headless operation remains first-class;
- realtime visualization is renderer-neutral;
- the live-table/state-view audit is substantially complete;
- application/backend capability negotiation is understood;
- designer metadata requirements are understood;
- at least one small non-SalixTorrent application can be created without copying application-specific code.

Until then, working names may evolve.

---

## 13. Non-goals

The current direction does **not** require:

- rewriting SalixTorrent in Tkinter;
- implementing every possible renderer;
- promising feature parity across all backends;
- making OpenGL a mandatory dependency;
- forcing GUI modules into CLI/headless applications;
- moving BitTorrent protocol code into the generic engine;
- moving every persistent artifact into SalixORM;
- introducing implicit observer/reactive behavior without a demonstrated need;
- freezing public names before the extraction inventory is complete.

The architecture should allow additional backends without designing for hypothetical users at the expense of the working reference application.

---

## 14. Relationship to SalixTorrent

SalixTorrent remains the source of requirements and regression proof.

The desired dependency direction is:

```text
SalixTorrent product/domain code
        |
        v
reusable framework + application engine
        |
        v
backend/platform adapters
```

not:

```text
generic framework/engine
        |
        v
BitTorrent-specific behavior
```

Every extraction must preserve SalixTorrent's working transfer engine, headless path, desktop behavior, persistence compatibility and release discipline.

The broader ecosystem succeeds when SalixTorrent becomes one application built on it, rather than when SalixTorrent is distorted merely to make an abstraction look generic.
---

## 15. First post-v0.5.0 implementation checkpoint

The first `dev` implementation tranche applies the reverse-pyramid rule to the live Speed subsystem.

```text
TorrentSession transfer counters
        |
        v
RollingTelemetry                      app/framework/telemetry.py
        |
        v
existing SalixTorrent speed snapshot  application compatibility boundary
        |
        v
PlotFrame / RealtimeGraph             app/framework/visualization.py
        |
        v
PlotHost
        |
        +-- DearPyGuiPlotHost          current concrete adapter
        +-- Tkinter Canvas host          prepared second-backend proof
```

The generic telemetry layer has no GUI dependency and is therefore usable by desktop, CLI/headless, tests, and future designer/runtime consumers. The visualization layer describes complete graph updates without importing Dear PyGui. Concrete plot creation, axis mutation, line-series updates, existence checks, and disposal remain adapter-owned.

The SalixTorrent Speed view deliberately still owns localized labels, Help/tooltips, transfer-rate unit conversion, torrent/global limit wording, and visible-window selection. This tranche proves a reusable data/plot seam without pretending the entire Speed view is a generic component.

Validation added 7 telemetry tests and 9 realtime-visualization tests while keeping the existing five framework-relocation tests. Both complete real-Windows discovery paths passed 432 / 432 with one expected non-Windows skip, and live Speed/application behavior plus the broader button/action surface was smoke-tested before commit/push. The exact pushed checkpoint is `ef8b4be998a714a86455940d8642fdd926a6609d` (`Extract realtime telemetry and plot boundary`). `APP_VERSION` remains `0.5.0`; this is development work on `dev`, not a release/tag boundary.

---

## 16. Second post-v0.5.0 implementation checkpoint

The second `dev` implementation tranche applies the same extraction discipline to the application engine/runtime and generic network mechanisms. It deliberately does **not** move the whole Dear PyGui engine or BitTorrent connectivity subsystem into a generic package.

```text
Dear PyGui desktop                    headless CLI
        |                                 |
        +---------------+-----------------+
                        |
                        v
                ApplicationRuntime
                        |
        +---------------+-------------------+
        |               |                   |
        v               v                   v
 service lifecycle   SceneRegistry       generic runtime policy
 ordered start/stop  SceneHost contract  diagnostics / paths / network
        |               |
        |               +-- DearPyGuiSceneHost
        |
        +-- desktop: application-menu + active-scene update services
        +-- headless: torrent-engine start/shutdown service
```

The committed generic package is:

```text
app/runtime/
├── application.py        application metadata/host contract added by tranche 3
├── presentation.py       presentation capability/bundle contract added by tranche 3
├── lifecycle.py
├── scenes.py
├── diagnostics.py
├── paths.py
└── network.py
```

`lifecycle.py` provides explicit service supervision without owning a render loop, worker thread, observer graph, or model. Startup is ordered; teardown is reversed; partial starts receive best-effort cleanup; earlier services roll back when a later service fails; restart is supported; update failures can be isolated through an injected reporter; and control-flow `BaseException` types are not swallowed.

`scenes.py` separates scene identity/activation from physical widget visibility. `app/engine/scene_manager.py` remains the SalixTorrent compatibility/composition facade, including its historical `view_container_<Name>` convention, while `app/engine/scene_hosts/dearpygui.py` owns the concrete Dear PyGui `show_item` / `hide_item` / existence operations.

`diagnostics.py` extracts duplicate-rate-suppressed exception reporting and optional append-only logging. `GuiEngine` composes it with SalixTorrent's existing `ui_errors.log` path rather than duplicating the mechanism.

`paths.py` parameterizes application name, portable flag/environment names, state/download overrides and bundled resources. `app/engine/runtime_paths.py` supplies SalixTorrent's product-specific policy while preserving the established source/frozen/portable function API.

`network.py` moves the already generic IPv4/IPv6 interface/address/source-binding mechanism out of BitTorrent logic. SalixTorrent callers consume it directly, while `app/logic/network_binding.py` remains a compatibility facade. The extraction covers address normalization/families, wildcard and endpoint helpers, interface discovery, local-address inventories, route-source probing, bind availability, and display masking. It does **not** absorb trackers, DHT/PEX/LPD, peer sessions, MSE/PE, torrent listener policy, Interface Lock policy, or BitTorrent-specific connectivity diagnosis.

The desktop and headless paths now provide the most important engine proof so far: **the same generic runtime lifecycle can supervise an application with or without a graphical presentation backend**. The Dear PyGui render/callback loop, tray/native-window policy, component/layout/plot hosts, and `MasterViewport` composition remain concrete while their reusable seams continue to be discovered.

Validation added 50 focused runtime/scene/network/adapter/relocation regressions and passed both complete real-Windows discovery paths at **482 / 482** with one expected non-Windows shell-behavior skip. The exact pushed checkpoint is `8e707efeb0cda162ee038a028a39a77663c2fa4e` (`Extract application runtime and network foundation`). Canonical localization remains 1,337 strings.

No final ecosystem naming, public API freeze, version bump, release tag, or merge to `main` is implied by this checkpoint.

---

## 17. Third post-v0.5.0 implementation checkpoint

The third `dev` tranche proves that the extracted engine/framework contracts can support a second real GUI implementation and a small application that is not SalixTorrent.

```text
                         ApplicationSpec / ApplicationRuntime
                                      |
                         PresentationBackend capabilities
                         /            |             \
                        /             |              \
                Dear PyGui         Tkinter          headless
                    |                 |                |
        component/layout/      component/layout/      runtime only
        scene/plot hosts       scene/Canvas plot
                    \                /
                     \              /
                      same framework components
                      same RealtimeGraph contract
                      same DemoView definition
```

New backend-neutral runtime contracts are `ApplicationSpec`, the minimal `ApplicationHost` protocol, `PresentationCapability`, and `PresentationBackend`. They describe application/window metadata and which presentation adapters are available without importing a GUI toolkit into `app/runtime`.

Tkinter now implements `ComponentRenderer`, `LayoutHost`, `SceneHost`, and `PlotHost`. Common controls, value/state mutation, rows/columns/grids, dialogs, tooltips, responsive callbacks, scene visibility, and realtime line plotting therefore have two concrete implementations. The Tkinter plot host uses Canvas and consumes the same `PlotFrame` updates as Dear PyGui.

The concrete backend bundle factories assemble Dear PyGui, Tkinter, or headless adapters explicitly. Minimal application hosts own the toolkit-specific event loops and drive `ApplicationRuntime`; this keeps GUI loop ownership out of the reusable runtime while making blank application startup repeatable.

`examples/ecosystem_blank_app.py` is the first product-neutral proof. Its `DemoView` contains one component tree and one realtime graph definition. The outer `--ui-backend dearpygui|tkinter|headless` choice changes the host, not the view. Headless mode proves the runtime remains usable without loading a graphical toolkit.

Validation added 34 focused regressions and passed both complete real-Windows discovery paths at **516 / 516** with the existing one non-Windows shell-behavior skip. Live Dear PyGui and Tkinter blank-application proof and the unchanged SalixTorrent desktop smoke also passed. The exact pushed checkpoint is `522ac8467fc55a5ac0e3d71fe5fd470251e13562` (`Add Tkinter compatibility application backend`). `APP_VERSION` remains `0.5.0`.

Dear PyGui remains SalixTorrent's reference desktop backend. This checkpoint does not rewrite SalixTorrent in Tkinter, promise identical backend capabilities, freeze final ecosystem names/API, tag a release, or merge `dev` into `main`. After this proof, the next major extraction target returns to rich live-data/RAD surfaces: transfer/peer/source tables, piece/state maps, status/diagnostic presentation, and the reusable data models beneath them.

---

## 18. Fourth post-v0.5.0 implementation checkpoint

The fourth `dev` tranche begins extracting the rich live-data surfaces that make the future RAD environment useful for dashboards, diagnostics, monitors and data-heavy desktop tools.

The framework now has two new provisional presentation contracts under `app/framework/live_data.py`:

```text
LiveTable
  -> TableColumnSpec / TableCell / TableRow / TableFrame
  -> stable keyed row identity
  -> changed-row updates
  -> removal + reorder
  -> TableHost

StateGrid
  -> StateGridCell / StateGridFrame
  -> compact categorical/high-density state maps
  -> StateGridHost
```

Dear PyGui and Tkinter each provide concrete table and state-grid hosts. `PresentationBackend` advertises `LIVE_TABLES` and `STATE_GRIDS` separately so a future backend can support one capability without falsely claiming the other. Headless remains free of graphical dependencies.

SalixTorrent now proves the contracts in real product surfaces rather than only a demo:

- **Peers** uses stable connection IDs to keep live table rows across telemetry frames instead of deleting/recreating the complete table every render;
- **Sources** uses stable source IDs with the same live-table coordinator while retaining application-owned tracker/DHT/PEX/LPD wording, response formatting, source-specific diagnostics and status colors;
- **Pieces** routes focused detail rows through `LiveTable` and the compact piece map through `StateGrid`; torrent-specific piece bucketing, scheduler/disk telemetry, state meanings and colors remain in SalixTorrent.

The product-neutral blank application is expanded again: one `DemoView` definition now exercises semantic components, a keyed live table, a categorical state grid and a realtime graph. Dear PyGui and Tkinter implement those presentation capabilities independently; the view still contains no toolkit-name branch.

Tranche 4 completed with both real Windows discovery paths at **529 / 529** and was pushed as `a561b50ddc64520d1dc10b362fb4180378da5dc8` (`Extract live table and state grid presentation`).

### Interactive data and command semantics

The fifth post-v0.5.0 tranche separates *what an interactive data surface means* from *how a toolkit draws it*. `DataView` owns deterministic keyed search, exact-choice filtering and stable multi-column sorting over ordinary records. `SelectionModel` owns explicit single-selection identity. `CommandSpec`/`CommandSet` describe stable command keys and enabled/checked/submenu state without embedding callbacks or backend objects. All of these contracts are standard-library-only and relocatable with `app/framework`.

SalixTorrent proves those semantics in two real surfaces. Active Transfers keeps its current Dear PyGui table and rich torrent context menu, but queue ordering/filter visibility now come from `DataView` rather than product-local sorting/filter loops. Files moves its physical rows to `LiveTable` and describes file-priority availability through a `CommandSet`; torrent mutation remains application-owned.

Tranche 5 passed both complete real-Windows discovery paths at **547 / 547** with one expected skip and was pushed as `e16e46884acc53adf54a29a35dbfd09bba40ed26` (`Extract interactive data and command models`). Canonical localization remains 1,337 strings and `APP_VERSION` remains `0.5.0`.

---

## 19. Sixth post-v0.5.0 implementation checkpoint

The sixth `dev` tranche turns the proven semantic command model into reusable physical presentation while also extracting two related application-building primitives: stable item reordering and local explicit placement.

`OrderedItems` is a backend-neutral keyed order model with `move_item_up`, `move_item_down`, `move_item_to`, boundary queries and explicit replace/append/remove operations. SalixTorrent's Active Transfers view now uses those semantics for durable queue reordering instead of calling Dear PyGui's `move_item_up` / `move_item_down` directly. The scheduler remains authoritative because the resulting key order is still committed explicitly through `TorrentManager.set_queue_order(...)`.

`CommandMenu` coordinates a `CommandSet` with an injected `CommandMenuHost`. Dear PyGui and Tkinter each implement the host, including nested command trees, enabled state and checked state. The Files view now uses one shared command-menu surface for file-priority actions instead of constructing a separate Dear PyGui popup menu for every file row. File-priority mutation still belongs to SalixTorrent.

The same presentation bundles now advertise command-menu capability explicitly. The product-neutral blank application exercises the command surface without branching on toolkit name.

The first mixed-layout runtime primitive is also introduced. `PositionedPanel` positions its direct children with local `(x, y)` coordinates, while `PlacedComponent` lets any component carry an offset/margins inside the content space assigned by an automatic parent. The placed wrapper reserves offset + margins + child size, and `ControlGrid` consumes that occupied size so a positioned child can grow the affected structured cell. This deliberately proves parent-aware mixed layouts rather than replacing structured layouts with absolute positioning.

The real Windows gate passed both discovery forms at **563 / 563** with one expected non-Windows shell-behavior skip, and the mixed-layout/command surfaces were exercised under both Dear PyGui and Tkinter. The exact pushed checkpoint is `19ee1ba92826501e2061132e2a514a38862082a1` (`Add command menus and mixed layout foundation`). Canonical localization remains 1,337 strings.

The tranche does **not** claim a final form designer, generic torrent lifecycle menu, or complete interactive-table migration. It establishes the parent-aware geometry and command surfaces needed for later structural composition without making absolute positioning the application default.

No final ecosystem/package naming, public API freeze, release tag or merge to `main` is implied.

---

## 20. Seventh post-v0.5.0 implementation checkpoint

The seventh `dev` tranche turns the mixed-layout rule into reusable structural regions. `TabContainer`/`TabPage` own stable semantic page identity and normalized page-change events independently of the physical toolkit. `SplitPanel`/`SplitPane` own horizontal or vertical weighted allocation, pane minimums, gaps and responsive reflow through the existing `LayoutCoordinator` rather than embedding geometry arithmetic in product views.

The placement model also gains an explicit non-measuring overlay mode. Overlays still use parent-local coordinates and therefore compose with `PositionedPanel`, but they do not contribute occupied bounds to parent measurement. This distinguishes ordinary positioned content—which can grow its structured parent—from overlays such as HUD labels, decorations or future designer handles that should float without changing layout size.

SalixTorrent now proves the structural contracts in production surfaces. Download detail pages use a generic `TabContainer`; the General page's Transfer, Swarm Status and Torrent Info regions use a responsive three-pane `SplitPanel`; application-menu navigation selects tabs by semantic key rather than backend item ID. Help uses a generic Contents/Glossary tab container plus a two-pane index/document split, while documentation rendering and localization remain application-owned.

The product-neutral blank application also nests tabs, weighted splits, automatic content, parent-aware explicit placement and a non-measuring overlay alongside its command menu, live table, state grid and realtime graph. Dear PyGui and Tkinter implement the same component contracts; the view still does not branch on toolkit name.

Real-Windows acceptance passed both complete discovery forms at **581 / 581** with one expected non-Windows shell-behavior skip. The acceptance pass also tightened an important cross-backend rule: a `SplitPanel` does not delegate pane placement to whatever flow/group behavior a toolkit happens to provide. The framework computes pane sizes, then places each pane explicitly in a parent-local positioned root through the renderer contract. Likewise, tab-change semantics are normalized from either callback payload or the backend current tab value. These fixes were driven by real Dear PyGui behavior where Help/document panes and split-hosted live surfaces could silently disappear and the Speed tab could stop receiving live render updates without producing a traceback. Canonical localization remains 1,337 strings. The exact pushed checkpoint is `731303d847a46c1e7e250d34d8b78a9e51f485ef` (`Add structural tabs, split regions and overlays`).

This checkpoint deliberately left anchors/edge offsets, percentages, richer min/max constraints, draggable split handles, generic tree/detail structures and serializable designer geometry to later passes.

No final ecosystem/package naming, public API freeze, release tag or merge to `main` is implied.

---

## 21. Eighth post-v0.5.0 implementation checkpoint

The eighth `dev` tranche begins Stage F with geometry rather than prematurely inventing a complete editor document model. `AxisAnchor` defines start, centre, end and stretch semantics independently for each parent-local axis. `AnchoredPlacement` combines those semantics with edge offsets represented by `Insets`, optional `SizeConstraints`, and the existing layout-participation flag. `AnchoredChild` lets ordinary components use that policy inside `PositionedPanel`.

When a positioned panel is supplied a `LayoutCoordinator`, it watches the rendered parent size and re-resolves anchored children through the existing renderer-neutral `configure(...)` and `place(...)` contracts. Fixed `(x, y)` children remain unchanged. Non-measuring anchored overlays are supported for future badges, HUD decorations and designer handles. Only axes whose anchor/constraints actually control size are configured, so simple edge-pinned labels do not require backend-specific size properties.

The geometry metadata is deliberately serializable before a full designer schema exists. `Placement.to_descriptor()` and `AnchoredPlacement.to_descriptor()` return JSON-safe data, while `placement_from_descriptor(...)` restores the corresponding backend-neutral object. This proves a small persistence seam without claiming stable component-type names, a project format or an external public API.

Structural sizing also gains optional maximums. `SplitPane.maximum` flows through `split_sizes(..., maximums=...)`; callers that omit maximums retain the historical allocation behavior. Help is the first real SalixTorrent proof: its Contents/Glossary index pane keeps a 260 px minimum but is capped at 480 px, allowing the documentation pane to consume additional ultrawide space.

The blank ecosystem application adds anchored start/end/stretch content with a constrained stretch control and continues to use one toolkit-neutral `DemoView`. The live Tkinter backend proves resize reflow through the same contracts.

Initial prepared validation advanced canonical discovery from **581 to 589 tests**. Real-Windows validation passed both 589-test discovery forms, then live acceptance identified two pre-commit integration repairs: a stale private Diagnostics error-log accessor and a blank-demo minimum-geometry mismatch that could clip the fixed-position Actions proof. The diagnostics seam is now public through `GuiEngine.ui_error_log_path()`, and the product-neutral demo's composition metrics fit its declared minimum split/window geometry. Regression coverage is now **591 tests**; display-less canonical Linux discovery passes 591 / 591 with 58 expected GUI/platform skips, and relocation/package-boundary proof remains green. Final real-Windows Dear PyGui/Tkinter visual recheck remains the commit gate. Canonical localization remains 1,337 strings and `APP_VERSION` remains `0.5.0`.

This checkpoint does **not** yet introduce component/type registry metadata, a serializable component hierarchy, stable designer-object identity, command-based mutations, undo/redo, copy/paste, project schema, preview bridge, percentages or draggable split handles. Those remain later Stage-F work.

No final ecosystem/package naming, public API freeze, release tag or merge to `main` is implied.
