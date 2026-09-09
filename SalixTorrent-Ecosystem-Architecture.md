# SalixTorrent Ecosystem Architecture Direction

**Status:** v0.5.1 released; post-v0.5.1 Tranches 1 through 3 published and Tranche 4 clickable-preview selection is the current full-commit Windows-acceptance boundary on `dev`
**Reference release:** SalixTorrent v0.5.1
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

### 6.1 Dual-entry application construction

The RAD/designer work is an **optional authoring layer**, not a replacement for code-first application construction. Both paths must remain first-class:

```text
code-first application                     designer-authored application
Python component composition                metadata/project document
          \                                  /
           +-------- semantic Component tree --------+
                              |
                              v
                    framework/runtime contracts
                              |
                              v
                     presentation backend
```

A developer must always be able to create and wire an application directly in Python using the framework, just as SalixTorrent and the blank ecosystem application were originally built. A future visual designer may produce equivalent hierarchy/property/relationship data and reconstruct the same framework components, but ordinary runtime components must not depend on the designer modules to function. Designer metadata, editing, structural commands and preview ownership therefore remain in an optional tooling layer above the reusable component/runtime contracts.

The architecture should avoid two incompatible UI systems. The designer path and code path converge on the same semantic components, layout contracts, application runtime and backend adapters. Where designer metadata reveals a missing runtime semantic, the runtime contract should be improved first rather than embedding designer-only behavior into production components.

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

The next metadata pass overlays provisional component/type/property descriptions and self-describing JSON-safe hierarchy snapshots on that proven geometry. Grid cells, tab pages, split panes, and fixed/anchored placement remain explicit relationship metadata rather than being flattened into backend coordinates, while `DesignerIdentityMap` keeps stable identities for live component objects during inspection. The blank ecosystem application captures its real nested component tree through this same metadata path; it does not maintain a second designer-only mock hierarchy.

Future passes should add richer geometry and editing behavior only when proved by real application/editor surfaces: percentages and relationship constraints, tree/list/detail composition, interactive split handles, designer resize handles, property mutation/reconstruction, selection/reparenting commands, and undo/redo. Margins/padding remain useful for structured flow, but explicit placement must always remain available locally when a design requires it.

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

This stage is now active. Tranche 8 established geometry that a future designer can describe faithfully: parent-local start/centre/end/stretch anchors, minimum/maximum size constraints, optional split-pane maximums and JSON-safe fixed/anchored placement descriptors. Tranche 9 added provisional component metadata, stable identities and JSON-safe component-tree snapshots. Tranche 10 added accepted property-level document editing with typed validation, undo/redo and dirty tracking, closed at checkpoint `df675e89bf025b570a339c7b3fb3c3518262d72a`. Tranche 11 added accepted child-slot metadata plus immutable insert/remove/reorder/reparent commands and was pushed at full checkpoint `79edec6cb4531759992b4f7fdb2d63ac8f122907`. Tranche 12 added and published the first snapshot-to-preview reconstruction bridge at `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`. Tranche 13 established optional transactional preview ownership and was published at `4b0968bfdf91ce040eeefd641b1e315244a325e6`. Tranche 14 added document-level copy/paste/duplicate with deterministic subtree identity remapping and was published at `f59a9a392bf64820f59787b9449d6b7ca9b3e634`. Tranche 15 added stable-ID designer selection/focus and was published at `a0d621a8266cdf42b5b1355c417ec7d6d03bb297`; that state remains ephemeral, non-undoable and independent of toolkit/component object lifetimes while reconciling safely across document edits and preview replacement. Tranche 16 added the deliberately small project-file ownership/save-load boundary and was published at `d95f6a1987aaff1bda9fb270c6219b36b8ee2080`: a strict versioned envelope around one immutable snapshot plus atomic file ownership/dirty semantics, without defining callbacks, assets, runtime state or a final project schema. Tranche 17 added stable-ID hierarchy navigation—parent/child/sibling/preorder traversal plus reveal paths—and is published at `f07bc5cc0bda02b81ffefd35b2da3a47e1168c7d`. Tranche 18 added the backend-neutral hierarchy projection/expansion model and is published at `9bd56a7e4a758529a54bbf45c3cc98bc061fa58c`; no toolkit tree widget or project persistence contract owns expansion. Tranche 19 added and published the backend-neutral property-inspector projection at `35d0d4c0966aa9a3a6aafbe263edfbe8b383d7aa`: deterministic selected-node rows carry semantic editor hints and edit/clear affordances while validated mutations continue through the existing edit/history/preview transaction boundaries. Tranche 20 added and published the Windows-accepted backend-neutral `DesignerWorkspace` coordinator at `f3a96420a6267089198f62662ab0761475ad962a`, composing project/history, selection, hierarchy, inspector and preview state into one shell-facing snapshot without taking ownership away from those existing models. Tranche 21 adds the Windows-accepted backend-neutral editor-shell command projection over that workspace using the existing generic command contracts. Throughout, code-first applications remain completely independent of designer tooling. The mixed-layout rule remains fundamental: reconstruction restores semantic grid/tab/split/placement relationships instead of flattening a whole form into toolkit coordinates. Multi-selection, visual selection overlays, pointer hit-testing/drag-drop handles, incremental live mutation, application callback resolution, specialized field factories and the final project schema remain later Stage-F work.

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

Real-Windows acceptance ultimately passed both complete discovery forms at **591 / 591** with one expected skip after two pre-commit integration repairs: the Diagnostics error-log path moved behind the public `GuiEngine.ui_error_log_path()` seam, and the blank demo's fixed-position proof was brought inside its declared minimum split/window geometry. Dear PyGui and Tkinter visual rechecks passed. Canonical localization remained 1,337 strings and `APP_VERSION` remained `0.5.0`. The exact pushed checkpoint is `5cef12f534dfc44a8536f504d1aa7773644f5428` (`Add responsive anchors and designer geometry constraints`).

This checkpoint deliberately stopped before component/type registry metadata, a serializable component hierarchy, stable designer-object identity, command-based mutations, undo/redo, copy/paste, project schema, preview bridge, percentages or draggable split handles.

No final ecosystem/package naming, public API freeze, release tag or merge to `main` is implied.

---

## 22. Ninth post-v0.5.0 implementation checkpoint

The ninth `dev` tranche begins the metadata side of Stage F without turning the previous geometry descriptors into a premature application-project format. `app/framework/designer.py` is standard-library-only and remains inside the relocatable provisional framework boundary.

`DesignerValueKind`, `DesignerPropertySpec` and `DesignerComponentSpec` describe editor-facing component types and properties. `DesignerCatalog` validates unique provisional type keys and component-class bindings; `FRAMEWORK_DESIGNER_CATALOG` covers the framework `Component` classes currently imported by SalixTorrent views. Common layout width/height/spacing metadata is described alongside control/container/field properties. The keys are internal working identities, not a frozen public namespace.

`DesignerIdentityMap` gives live component instances stable IDs for repeated inspection and permits an explicit persisted key to be rebound by a later preview/runtime bridge. `capture_component_tree(...)` converts the live hierarchy into `DesignerNode` / `DesignerChild` objects and a self-describing `DesignerSnapshot`. The snapshot includes only JSON-safe values, validates unique node IDs/type metadata, and rejects cycles or one component object being owned from multiple tree locations.

Relationship metadata is structural rather than flattened: grid children retain row/column coordinates, tabs retain semantic page keys, split children retain pane key/weight/minimum/maximum/border values, and placed/positioned/anchored children reuse the JSON-safe placement descriptors proven in Tranche 8. This lets a future hierarchy/property inspector distinguish where a component lives from the component's own properties.

The product-neutral blank application exposes a snapshot of its existing nested component tree through `DemoView.capture_designer_snapshot()`. Repeated captures use one identity map, so IDs remain stable without consulting Dear PyGui or Tkinter. The framework relocation test copies/renames the package and round-trips a designer snapshot there as well. A SalixTorrent source-audit regression checks that every framework `Component` class currently imported by `app/views` is represented by the provisional catalog.

Preparation advanced complete discovery from 591 to **602 tests**; display-less canonical Linux discovery passed 602 / 602 with 58 expected GUI/platform skips. Real-Windows acceptance then passed both complete discovery forms at **602 / 602** with one expected skip. Dear PyGui and Tkinter resize/structure smoke checks passed, including reinforced minimum window geometry, and the accepted implementation commit is `5b54084f2d21dc331deb4614c15119ad94cab374`. The documentation closure was pushed at `d939f6443a95490881925ca8bdb93e5e94f7ec2c`. Canonical localization remains 1,337 strings and `APP_VERSION` remains `0.5.0`.

This checkpoint did **not** reconstruct executable components from snapshots, mutate live properties, copy/paste, drag/drop/reparenting, define a final project schema, restore previews, add percentages or draggable split handles. Snapshot-level property commands and undo/redo are prepared in the following tranche; those edits remain document data rather than live runtime mutation.

No final ecosystem/package naming, public API freeze, release tag or merge to `main` is implied.

---

## 23. Tenth post-v0.5.0 implementation checkpoint — Windows validated

The tenth `dev` tranche introduces the first explicit editing/history layer above the designer metadata snapshot. `app/framework/designer_editing.py` remains standard-library-only and portable with the rest of `app/framework`. It accepts and returns immutable `DesignerSnapshot` values and therefore cannot accidentally reach into Dear PyGui/Tkinter handles or SalixTorrent application models.

`SetDesignerProperty` validates and replaces one serializable editable property, while `ClearDesignerProperty` removes an explicit property so a later reconstruction/runtime can fall back to inheritance/default policy. `CompositeDesignerEdit` groups multiple property commands into one semantic edit. Property values are normalized from the metadata embedded in the snapshot: text, booleans, bounded integers/numbers, choices, lists, semantic dimensions and inset values all reject invalid edits before history is changed.

`DesignerPropertySpec.nullable` records the cases where explicit `None` is legal and distinct from an absent property; `unsettable` separately identifies sparse overrides that may legally be removed. `DesignerPropertyState` exposes that distinction to a future inspector along with editable/serializable flags, choices and bounds. This is important for the existing property-cascade model: clearing an explicit layout override is not the same operation as setting a nullable value to `None`.

`DesignerEditSession` keeps the current snapshot plus explicit undo and redo stacks. No-op commands do not create history, a new command after undo discards the obsolete redo branch, `CompositeDesignerEdit` is one history step, and `mark_clean()` establishes a save/checkpoint state for dirty tracking. Undo/redo availability is surfaced through the already-existing renderer-neutral `CommandSet` contract using stable `designer.undo` / `designer.redo` keys. Whole snapshots are retained for history in this provisional pass because correctness and recovery are more valuable than delta compression while the document model is still evolving.

The framework relocation proof now edits and undoes a snapshot after the package is copied and renamed. A product-neutral regression edits the blank application's real captured `Actions` node and proves the live `Button` object remains unchanged. This keeps the editing layer clearly document-oriented until a deliberate reconstruction/preview bridge is implemented.

Tracked `validate_tranche.bat` now automates the non-visual acceptance sequence and writes a complete report to `%USERPROFILE%\Desktop\console_output.txt`; Dear PyGui/Tkinter/SalixTorrent visual smoke remains a human gate. Preparation canonical discovery passes **616 / 616** on display-less Linux with 58 expected GUI/platform skips. After repairing the Windows validator launch path and Tk/Tcl owner-thread teardown, both complete real-Windows discovery forms pass **616 / 616** with one expected skip, the validator ends in `TRANCHE VALIDATION PASSED`, manual visual smoke passes, and the accepted implementation commit is `3968bd2`.

This checkpoint deliberately did not implement executable reconstruction, live preview mutation, hierarchy insert/remove/reparent commands, copy/paste, drag/drop or resize handles, persistent history, a final project document/schema or API/package naming freeze.

### Structural snapshot editing — Tranche 11 accepted

`DesignerChildSlotSpec` extends provisional type metadata with explicit structural relationship rules. A type can now describe named child slots, whether a slot accepts one or many children, which relationship metadata fields are required, and which fields form a sibling-unique identity. Current framework metadata covers ordinary children, grid cells, placed/positioned children, tab pages, split panes and semantic composite-field slots.

`designer_structure.py` keeps hierarchy edits in document space. `InsertDesignerChild`, `RemoveDesignerNode`, `MoveDesignerNode` and `ReparentDesignerNode` return new immutable snapshots; `DesignerNodeLocation` exposes parent/index/slot/relationship/depth state for future hierarchy inspectors. Structural validation preserves grid coordinates, page/pane keys and placement descriptors and rejects root removal/reparenting, cycles, duplicate IDs, illegal slots and ambiguous sibling identities.

The existing `DesignerEditSession` is the only history owner: structural helper methods route through the same command execution path as property edits, so undo/redo, dirty-state and redo-branch invalidation remain consistent. No live component is mutated. The blank application proves this by moving the captured `Actions` node while its real runtime component tree stays unchanged, and the relocation proof exercises insertion/undo after package rename.

Preparation passed 630 / 630 complete tests on display-less Linux, including a 14-test structural gate and 44-test combined designer/relocation gate; Xvfb canonical discovery also passed 630 / 630. Real-Windows acceptance then passed both complete discovery forms at 630 / 630 with one expected skip, manual Dear PyGui/Tkinter/SalixTorrent smoke passed, pre-commit passed, and the tranche was committed/pushed as `79edec6` (`Add designer structural hierarchy editing`).

This layer still does not define component factories, preview synchronization, copy/paste, drag/drop gestures, selection overlays, persistent undo history, project storage/versioning or a final public framework API.

### Snapshot-to-preview reconstruction — Tranche 12 accepted and published

`app/framework/designer_preview.py` introduces a separate provisional reconstruction registry rather than teaching snapshots about a concrete GUI toolkit. `DesignerPreviewCatalog` maps internal type keys to backend-neutral builders, `DesignerPreviewContext` carries only optional `LayoutCoordinator` support, and `DesignerPreviewBuild` returns a fresh root plus stable node-ID/component bindings. The module stays inside the relocatable framework and imports no SalixTorrent product or engine backend.

The first registry reconstructs the primitive controls and structural/layout containers exercised by the blank application, including local fixed/anchored placement, dense grids, semantic tab pages and weighted split panes. Application callbacks and bindings are deliberately omitted, making the result an inert preview tree rather than a second running application. Specialized semantic field composites are explicitly reported as unsupported before partial reconstruction until their constructor-specific document contracts are proven.

The blank application can rebuild its own captured 31-node designer hierarchy through this bridge and recapture it descriptor-for-descriptor with the same designer IDs. Property edits and hierarchy edits feed the same reconstruction path without touching the original live components. A real Tkinter/Xvfb test builds the reconstructed blank hierarchy through the existing renderer after injecting a Tkinter-backed `LayoutCoordinator`, proving the bridge is not merely a JSON transformation.

Preparation advanced complete discovery to **643 tests**. Real-Windows acceptance then passed the preview gate 12 / 12, combined designer/relocation focus 56 / 56, GUI components 64 / 64 and Tkinter 22 / 22; both complete discovery forms passed **643 / 643** with one expected skip, localization remained 1,337/current, the validator ended in `TRANCHE VALIDATION PASSED`, manual Dear PyGui/Tkinter/SalixTorrent visual smoke passed, and pre-commit passed. Implementation `688bcff` (`Add designer snapshot preview reconstruction`) and its documentation closure were published together at `8d05ca8b059cef0ba386f324c215f2e80a9bfa83`.

This tranche does not synchronize an already-rendered preview after every edit, resolve application callbacks/services, reconstruct the four specialized semantic-field composites, implement copy/paste/duplicate or drag/drop/resize handles, persist project documents/history, or freeze public package/type names. Transactional whole-preview ownership/rebuild is established by the following tranche; incremental toolkit mutation remains deferred.

### Transactional preview ownership/rebuild — Tranche 13 accepted and published

`app/framework/designer_preview_host.py` adds optional tooling above `DesignerEditSession` and the Tranche-12 reconstruction bridge. One host owns one accepted preview. Candidate snapshots are reconstructed first and, when a renderer is supplied, built before the current preview is disposed; failed candidates are cleaned up without advancing document/history state. Generic checked execute/undo/redo hooks validate prospective immutable snapshots without coupling the editing core to a toolkit.

The host keeps property edits, structural edits, undo, redo and explicit external-session `sync()` aligned with preview replacement while stable designer node IDs continue to resolve the newly reconstructed components. This does not change the code-first path: SalixTorrent and other applications can continue composing semantic framework components directly in Python without importing designer tooling.

Real-Windows acceptance passed the preview-host gate 11 / 11, combined designer/relocation focus 67 / 67, GUI components 64 / 64 and Tkinter 23 / 23. Both complete discovery forms passed **655 / 655** with one expected skip after repairing a pre-existing persistence-test `TemporaryDirectory` lifetime race; canonical localization remained 1,337/current, headless/compileall/Git checks passed, manual Dear PyGui/Tkinter/SalixTorrent smoke passed and `pre_commit_check.bat` passed. The accepted implementation commit is `ddfb3ef2269acb33484cd6fe2f99af47fa40140f` (`Add transactional designer preview ownership`); implementation and documentation closure were published together at `4b0968bfdf91ce040eeefd641b1e315244a325e6`.

### Document copy/paste/duplicate — Tranche 14 accepted and published

`app/framework/designer_clipboard.py` adds an optional document-tooling boundary, not a second component/runtime path. `DesignerClipboardPayload` contains one detached `DesignerNode` subtree plus its source slot/relationship metadata and can round-trip as provisional JSON-safe clipboard data. `DesignerSubtreeClone` exposes deterministic source-ID -> fresh-ID bindings, allocated in preorder as `<id>-copy`, `<id>-copy-2`, and so on against the destination snapshot.

`PasteDesignerSubtree` and `DuplicateDesignerNode` do not bypass structural rules: they delegate insertion to the Tranche-11 relationship validator, so grid coordinates, tab/split identities, single-child slots and fixed/anchored placement descriptors remain authoritative. Relationship metadata is preserved by default but can be explicitly replaced for destinations whose sibling identity must be unique.

`DesignerEditSession` keeps clipboard contents ephemeral and outside project/dirty/history state. Copy alone changes neither snapshot nor preview generation; paste/duplicate share the same undo/redo history. `DesignerPreviewHost` exposes matching operations and routes paste/duplicate through checked preview replacement, so a candidate tree must reconstruct/build before document state advances. This continues to preserve the dual-entry rule: code-first applications neither import nor depend on clipboard/designer tooling.

Real-Windows acceptance passes 12 / 12 clipboard tests, 79 / 79 combined designer/relocation tests, GUI components 64 / 64 and Tkinter 24 / 24. Both complete discovery forms pass **668 / 668** with one expected skip, localization remains 1,337/current, headless/compileall/Git checks pass, manual Dear PyGui/Tkinter/SalixTorrent smoke passes and `pre_commit_check.bat` passes. The accepted implementation commit is `450c12a` (`Add designer copy paste and duplicate commands`); implementation and documentation closure were published together at `f59a9a392bf64820f59787b9449d6b7ca9b3e634`. Operating-system clipboard integration, cut/multi-selection, pointer-driven gestures, incremental toolkit mutation, callback/service serialization and project persistence/schema remain deferred.

### Stable-ID designer selection/focus — Tranche 15 accepted and published

`app/framework/designer_selection.py` adds explicit interaction state above immutable designer documents without expanding the project schema. `DesignerSelectionModel` stores one selected node ID and one focused node ID, validates those identities against the current snapshot, and can resolve current node/location context. Selection and focus are intentionally independent so a future hierarchy, inspector and preview can coordinate object selection without conflating it with keyboard/navigation focus.

`DesignerEditSession` keeps this state ephemeral alongside clipboard state. Selection/focus changes do not dirty the document, add undo entries or rebuild previews. Accepted property edits, moves and reparenting preserve stable IDs; when selected/focused content is removed, reconciliation walks the previous hierarchy to the nearest surviving ancestor. Undo/redo changes the document but does not treat transient selection as serialized historical state.

`DesignerPreviewHost` delegates selection/focus to the session and resolves `selected_component` / `focused_component` against the currently owned preview generation. Whole-tree preview replacement can therefore dispose stale component instances while preserving the designer IDs used by editor surfaces. A real Tkinter proof exercises the blank application's `Actions` control through one replacement generation, confirming the old rendered object dies while the stable selected/focused identity resolves to the new component.

Real-Windows acceptance passed 12 / 12 dedicated selection tests, 91 / 91 combined designer/relocation tests, 64 / 64 GUI-component tests and 25 / 25 Tkinter tests. Both complete discovery forms passed **681 / 681** with one expected skip; localization remained 1,337/current, headless/compileall/Git checks passed, manual Dear PyGui/Tkinter/SalixTorrent smoke passed and `pre_commit_check.bat` passed. The accepted implementation commit is `98f64e2` (`Add stable designer selection and focus state`); implementation and documentation closure were published together at `a0d621a8266cdf42b5b1355c417ec7d6d03bb297`.

This slice deliberately stops before multi-selection, visual highlight overlays, keyboard tree traversal policy, pointer hit-testing, drag/drop/resize handles, incremental toolkit mutation and project persistence. Those should build on stable selection semantics rather than introduce parallel toolkit-owned identity.

### Provisional designer project-file ownership/save-load — Tranche 16 Windows-accepted

`app/framework/designer_project.py` introduces the first on-disk ownership seam above immutable designer snapshots. `DesignerProjectDocument` wraps exactly one `DesignerSnapshot` in a provisional `salix-designer-project` version-1 envelope. The wrapper is intentionally narrower than the eventual application-project schema: there are no callbacks, services, bindings, assets, launch settings, toolkit objects or editor interaction state in the persisted document.

Parsing is strict rather than best-effort. Duplicate JSON keys and non-finite numeric tokens are rejected; the envelope must contain exactly `kind`, `version` and `snapshot`; unsupported versions and invalid embedded snapshots fail deterministically. Serialization is sorted UTF-8 JSON with portable finite numbers and a single terminal newline when written. The implementation deliberately mandates no final filename extension.

`DesignerProjectFile` owns one `DesignerEditSession` plus an optional absolute path. A new in-memory project is unsaved/dirty even when its initial snapshot equals the session baseline; an opened file begins persisted/clean. Save and Save As write a temporary sibling, flush it, then replace the target atomically. Only a successful replacement updates owned-path state and calls `mark_clean()`, so a failed Save As neither loses dirty edits nor changes which file the project owns. Selection/focus, clipboard and undo/redo history are intentionally recreated rather than persisted.

This remains optional tooling over the same runtime. The code-first blank application's captured hierarchy saves/reopens without mutating its live component tree; the reopened session feeds the existing preview host; and a real Tkinter regression renders the reopened blank-application snapshot through the established preview/backend contracts. The copied/renamed framework probe uses the same file API without importing SalixTorrent or Dear PyGui. Real-Windows acceptance passes 12 / 12 project tests, 103 / 103 designer/relocation tests, 64 / 64 GUI-component tests and 26 / 26 Tkinter tests; both complete discovery forms pass **694 / 694** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks and manual visual smoke pass, and `pre_commit_check.bat` passes. The accepted implementation commit is `a86acae`; implementation and documentation closure were published together at `d95f6a1987aaff1bda9fb270c6219b36b8ee2080`.

Multi-document/editor-window ownership, migrations, autosave/crash recovery, resource manifests, callback/service/binding serialization, a final extension/project schema, pointer hit-testing and drag/drop/resize handles remain deferred.

### Stable-ID hierarchy navigation — Tranche 17 Windows-accepted

`app/framework/designer_navigation.py` introduces a read-only hierarchy seam over `DesignerSnapshot`. `DesignerHierarchyNavigator` indexes the existing immutable tree and exposes stable-ID parent, first/last-child, previous/next-sibling and previous/next-preorder targets. It follows semantic snapshot child order and returns `None` at hierarchy boundaries rather than wrapping or inventing toolkit traversal policy.

`DesignerHierarchyReveal` carries only the target ID and its root-to-parent ancestor path. A future hierarchy tree can expand those ancestors to reveal the target while keeping expansion state outside project persistence, undo/redo and component/runtime identity. `DesignerEditSession` and `DesignerPreviewHost` add relative selection/focus navigation and reveal helpers; these are ephemeral operations and never rebuild a preview merely because navigation changed.

The real blank-application proof remains code-first. Navigation operates on the captured designer document/preview only, while a Tkinter regression proves rendered parent/child traversal can change stable selected/focused IDs and resolve the corresponding rendered component without increasing preview generation. The relocated framework probe uses the same navigator after package rename. Real-Windows acceptance passes 12 / 12 navigation tests, 115 / 115 combined designer/relocation tests, 64 / 64 GUI-component tests and 27 / 27 Tkinter tests; both complete discovery forms pass **707 / 707** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes. The accepted implementation commit is `34b2084`; implementation and documentation closure are published together at `f07bc5cc0bda02b81ffefd35b2da3a47e1168c7d`.

This slice deliberately stops before a concrete hierarchy widget, persistent expanded/collapsed state, platform key bindings, range/multi-selection, pointer hit-testing, visual selection overlays, drag/drop/reparent gestures, resize handles or incremental toolkit mutation.

### Hierarchy projection and ephemeral expansion — Tranche 18 Windows-accepted

`app/framework/designer_hierarchy.py` turns the accepted immutable snapshot/navigation semantics into a backend-neutral hierarchy presentation model. `DesignerHierarchyProjection` owns a set of expanded stable node IDs and projects only the rows currently visible through those expansions. `DesignerHierarchyRow` carries stable ID, type key, depth, parent ID, child count/expandability, expanded state and selected/focused markers; a concrete tree widget therefore renders semantic rows instead of rediscovering hierarchy rules from toolkit items.

Expansion is explicitly editor interaction state. The root begins expanded by default when it has children, leaves cannot be expanded, and reveal expands the ancestor path already computed by `DesignerHierarchyReveal`. Selection/focus remains a separate model but is reflected in each row on projection. `DesignerEditSession` reconciles expansion after accepted document transitions so surviving expandable IDs persist across moves/reparenting while removed or now-leaf IDs disappear. Undo/redo changes the document but does not replay historical expansion state. Project save/load continues to persist only the designer snapshot envelope, so reopened projects receive fresh hierarchy expansion state.

`DesignerPreviewHost` delegates hierarchy rows and expansion operations without increasing preview generation. The real Tkinter proof selects/reveals the blank application's rendered `Actions` control, collapses its hierarchy parent, confirms the row becomes hidden while the same rendered component remains resolvable, and proves no preview reconstruction occurs. The copied/renamed framework probe uses the same projection after package relocation. Real-Windows acceptance passes 12 / 12 hierarchy-projection tests, 127 / 127 combined designer/relocation tests, 64 / 64 GUI-component tests and 28 / 28 Tkinter tests; both complete discovery forms pass **720 / 720** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes.

This slice still does not add a Dear PyGui/Tkinter hierarchy widget, persisted expansion, platform keyboard shortcut policy, range/multi-selection, pointer hit-testing, visual overlays, drag/drop/reparent gestures, resize handles or incremental toolkit mutation. Code-first applications continue to bypass designer tooling entirely.

### Property-inspector projection — Tranche 19 Windows-accepted

`app/framework/designer_inspector.py` is the presentation-model counterpart to the existing property editing contract. `DesignerPropertyInspector` reads the current stable selection from one `DesignerEditSession` and projects an immutable `DesignerInspectorState` with selected node ID/type/label/category plus ordered `DesignerInspectorRow` records. Each row wraps the already-proven `DesignerPropertyState`, adds a semantic `DesignerInspectorEditorKind`, and derives whether the current property can be edited or cleared. This keeps type validation, nullable/unsettable semantics, choices and numeric bounds authoritative in one existing metadata/editing path rather than duplicating them inside toolkit code.

The inspector owns no selection, document snapshot, undo history, preview generation or toolkit object. Selection changes merely retarget the next projection. Read-only filtering changes presentation only. Session selected-property set/clear helpers delegate to existing commands, and preview-host selected-property edits still pass through the checked candidate-build transaction before document/history state advances. Project save/load remains unchanged and therefore does not persist an inspector target.

A real Tkinter regression proves a selected rendered blank-application control can be inspected without rebuilding, then edited through the inspector-facing preview-host helper so the old rendered component is retired and the same stable designer ID resolves to the replacement. The copied/renamed framework probe exercises the same inspector after package relocation. Real-Windows acceptance passes 12 / 12 inspector tests, 139 / 139 designer/relocation tests, 64 / 64 GUI-component tests and 29 / 29 Tkinter tests; both complete discovery forms pass **733 / 733** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes.

This remains optional authoring tooling. Code-first applications continue to construct the same semantic component/runtime/backend objects directly and never require the inspector. Concrete toolkit property editors, validation-message surfaces, mixed multi-selection values, property grouping/search, pointer hit-testing, drag/drop/resize gestures and final public naming remain later work.

### Designer workspace coordination — Tranche 20 Windows-accepted

`app/framework/designer_workspace.py` is a composition seam rather than another designer subsystem owner. `DesignerWorkspace` holds one `DesignerProjectFile` and one `DesignerPreviewHost` over the exact same `DesignerEditSession`; if a caller supplies an existing preview host backed by another session, construction fails instead of silently coordinating divergent documents. `DesignerWorkspaceState` is an immutable shell-facing snapshot carrying project path/persisted/dirty/save requirements, undo/redo availability and labels, clipboard presence, selected/focused IDs, hierarchy expansion and visible rows, current inspector state, plus preview generation/availability/rendered state. Its descriptor is presentation data only, not a persistence format.

All mutations remain delegated to the established owner. Project Save/Save-As stays atomic and does not rebuild the preview. Selection, hierarchy expansion/reveal and inspector projection do not enter document history. Selected-property edits and paste/duplicate/undo/redo route through `DesignerPreviewHost`, preserving checked transactional replacement. `sync_preview()` simply exposes the existing explicit synchronization seam for external session edits; it does not create incremental toolkit mutation. Closing the workspace closes preview ownership but does not invent a new project-file close lifecycle.

The relocation probe imports and exercises the coordinator after package rename, and a real Tkinter workspace test proves a rendered selected component can be inspected, transactionally edited, saved without another rebuild and observed through one composed state snapshot. Real-Windows acceptance passes 12 / 12 workspace tests, 151 / 151 designer/relocation tests, 64 / 64 GUI-component tests and 30 / 30 Tkinter tests; both complete discovery forms pass **746 / 746** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke was completed before automated validation, and `pre_commit_check.bat` passes. Concrete Dear PyGui/Tkinter editor-shell widgets, multi-document/autosave policy, pointer hit-testing, drag/drop/resize gestures, mixed-value multi-selection, callback/service/binding serialization and final public naming remain deferred. The code-first path remains independent of designer workspace tooling.

### Editor-shell command projection — Tranche 21 Windows-accepted

`app/framework/designer_shell.py` projects a future editor shell's semantic command surface from the accepted `DesignerWorkspace` rather than adding another state owner. `DesignerShellCommandState` contains the current File/Edit/Navigate command tree using generic `CommandSpec` records. Save, Undo/Redo, Copy, Duplicate, Paste availability, Reveal and parent/child/sibling/preorder navigation are therefore backend-neutral presentation data that can be consumed by a menu bar, toolbar, command palette or keyboard adapter.

`DesignerShellCommands` delegates fully-specified actions to the existing owners. Direct Save remains project-file owned; Undo/Redo and Duplicate retain checked preview transactions; Copy/Reveal/navigation remain ephemeral. New/Open/Save-As and Paste deliberately return immutable shell requests because template creation, file-dialog paths and paste placement have not been defined as framework policy. This avoids turning a convenience command layer into a second project lifecycle or hierarchy-placement model.

The relocation probe exercises the shell command tree after package rename, and a real Tkinter regression proves the same commands can drive a rendered workspace without importing or owning Tkinter semantics: Copy does not rebuild, Duplicate rebuilds through the existing transaction, and Undo removes the duplicate through the same stable command ID. Real-Windows acceptance passes 12 / 12 command tests, 163 / 163 combined designer/relocation tests, 64 / 64 GUI-component tests and 31 / 31 Tkinter tests; both complete discovery forms pass **759 / 759** with one expected skip. Localization remains 1,337/current, headless/compileall/Git checks pass, the manual visual smoke passed, and `pre_commit_check.bat` passes. After this tranche is published, the planned next step is a dedicated v0.5.1 release closure/tag checkpoint before concrete editor surfaces begin.

### v0.5.1 release checkpoint

The v0.5.1 checkpoint marks completion of the backend-neutral semantic prerequisites needed before concrete RAD/editor shells are introduced. The accepted chain now spans designer metadata and stable identity, validated immutable editing/history, structural hierarchy mutation, snapshot reconstruction, transactional preview ownership, clipboard/duplicate, selection/focus, project-file ownership, stable-ID navigation and visible hierarchy projection, property-inspector presentation, workspace coordination and shell-command projection.

This release does **not** collapse the permanent dual-entry architecture: code-first Python composition and designer/RAD authoring remain equal first-class inputs to the same semantic `Component` / runtime / backend contracts. SalixTorrent remains the code-first reference application. The v0.5.1 tag therefore records a proven internal architecture milestone rather than a final public package/API freeze. Concrete editor-shell widgets, pointer interaction, multi-document/autosave policy and final project/package naming remain subsequent work.

### Concrete designer command-menu surface — post-v0.5.1 Tranche 1 Windows-accepted

The first post-v0.5.1 surface tranche binds the accepted semantic command layer to an already-existing presentation host instead of creating toolkit-specific editor semantics. `DesignerShellMenu` in `app/framework/designer_shell_menu.py` composes `DesignerShellCommands` with the renderer-neutral `CommandMenu` / `CommandMenuHost` contract. The framework module imports neither Dear PyGui nor Tkinter; those concrete hosts remain in the engine adapter layer.

The presenter refreshes its command set from live workspace state immediately before showing the surface, so dynamic Undo/Redo labels, selection-dependent actions and navigation enablement are never copied into a second owner. Menu activation is revalidated through `DesignerShellCommands`. Shell-owned requests for New/Open/Save-As/Paste placement are forwarded to an optional request callback rather than resolved by framework policy. Completed actions continue through the same project/session/workspace/preview owners established before v0.5.1.

A dedicated `examples/ecosystem_designer_shell.py` proof renders a semantic preview and this command surface on Dear PyGui and Tkinter. The copied/renamed framework probe exercises the same presenter without product or toolkit dependencies, while a real Tkinter regression invokes actual menu items and proves Copy is preview-neutral and Duplicate/Undo retain checked preview replacement. Real-Windows acceptance passes 12 / 12 command-surface tests, 175 / 175 combined designer/relocation tests, 64 / 64 GUI-component tests, 32 / 32 Tkinter tests and both complete discovery forms at **772 / 772** with one expected skip; localization/headless/compile/Git/manual visual/pre-commit gates also pass. Implementation and acceptance documentation are published together at `376ae76409bbdc47bda0c06e49ba8e3bed920203` (`Add designer command-menu surface`). This is the first concrete shell surface, not a full RAD IDE: hierarchy and inspector widgets, file dialogs/templates, pointer selection, drag/drop/resize, multi-document/autosave policy and final public naming remain later work.

### Concrete designer hierarchy-panel surface — post-v0.5.1 Tranche 2 Windows-accepted

The second post-v0.5.1 surface tranche turns the accepted hierarchy projection into a concrete editor panel without moving hierarchy semantics into either GUI toolkit. `DesignerHierarchyPanel` in `app/framework/designer_hierarchy_panel.py` consumes one `DesignerWorkspace` and one injected `DesignerHierarchyPanelHost`. Its rows are always the current `DesignerHierarchyRow` projection; selection/focus, expansion/collapse and reveal delegate back through `DesignerWorkspace`, so the panel never owns another selected ID, expanded-ID set, document snapshot, history stack or preview generation.

Concrete host implementations are isolated under `app/engine/designer_hierarchy_panel_hosts/`. Dear PyGui presents explicit indented expand/collapse controls plus selectable rows. Tkinter uses a native `ttk.Treeview`; native select/open/close events are deferred and guarded while the tree is repopulated so presentation-generated events cannot recursively manufacture semantic changes. Both hosts treat their native items as disposable bindings and may rebuild them from the complete visible projection. Incremental in-place toolkit mutation is intentionally not a framework contract in this tranche.

The designer-shell proof now composes a live hierarchy panel beside the reconstructed preview while retaining the Tranche-1 command surface. A row selection updates the existing stable selection/focus owner without rebuilding the preview; expansion and reveal remain ephemeral; document-changing shell commands still use the previously accepted checked preview transaction. Relocation coverage exercises the framework presenter after package copy/rename, and real Tkinter tests drive native hierarchy events through the same semantic boundary. Real-Windows acceptance passes 12 / 12 hierarchy-panel tests, 187 / 187 combined designer/relocation tests, 64 / 64 GUI-component tests, 34 / 34 Tkinter tests and both complete discovery forms at **786 / 786** with one expected skip; localization/headless/compile/Git/manual Dear PyGui/Tkinter/SalixTorrent visual/pre-commit gates also pass. Implementation and acceptance documentation are published together at `079eaf6e05b678aa2708d83c69bb9cdc37db0433` (`Add designer hierarchy-panel surface`).

Persisted hierarchy expansion, drag/drop/reparent gestures, pointer hit-testing/click-to-select in the preview, visual selection overlays, concrete property-editor controls, file-dialog/template policy, multi-document ownership, autosave/recovery and final public naming remain deferred. The permanent dual-entry architecture is unchanged: code-first Python composition and designer/RAD authoring continue to converge on the same semantic component/runtime/backend contracts.

### Concrete designer property-inspector/editor surface — post-v0.5.1 Tranche 3 Windows-accepted

The third post-v0.5.1 surface tranche binds the already-proven selected-node property-inspector projection to concrete editor controls without transferring property semantics into a GUI toolkit. `DesignerInspectorPanel` in `app/framework/designer_inspector_panel.py` consumes one `DesignerWorkspace` and one injected `DesignerInspectorPanelHost`. Its target and rows are always re-read from the current `DesignerInspectorState`; set/clear operations delegate back through the workspace, preserving the existing typed metadata validation, immutable edit history, project dirty tracking and transactional preview replacement. A native callback also carries the stable node ID it was created for, so stale controls cannot silently edit a different selection.

Dear PyGui and Tkinter hosts are isolated under `app/engine/designer_inspector_panel_hosts/`. Both adapters render the same semantic editor hints, including text/toggle/numeric/choice controls plus deterministic text forms for lists, dimensions and insets. Nullable properties receive an explicit `None` affordance, while unsettable explicit values receive a separate inherited/default action; those states are not conflated. Renderer-neutral presentation codecs translate text into ordinary Python values, but final type/bounds/choice/nullability validation still occurs only in the existing designer edit/session layer. Native controls are disposable bindings and may be rebuilt from the complete inspector projection.

The hierarchy presenter gains an optional presentation-only change callback so direct tree selection can refresh a sibling inspector without creating a new selection coordinator. `examples/ecosystem_designer_shell.py` now composes three panes—Hierarchy, reconstructed Preview and Inspector—while retaining the semantic Designer Commands surface. Hierarchy selection remains preview-neutral; property edits rebuild through the established checked transaction and update existing undo/redo/dirty state. Real-Windows acceptance passes 18 / 18 inspector-panel tests, 206 / 206 designer/relocation tests, 64 / 64 GUI-component tests, 36 / 36 Tkinter tests and both complete discovery forms at **807 / 807** with one expected skip. Localization/headless/compile/Git, the Dear PyGui/Tkinter/SalixTorrent visual smoke and pre-commit also pass. Implementation and acceptance documentation are published together at `6675ee00013e2b7f7b185843843f15d8f21b9427` (`Add designer property-inspector surface`).

This surface still does not define multi-selection/mixed-value editing, specialized callback/service/binding editors, drag/drop/reparent/resize gestures, file-dialog/template/paste policy, multi-document/autosave/recovery, incremental native-widget mutation or final public package/project-schema naming. Code-first applications remain independent of designer modules and continue to use the same semantic component/runtime/backend contracts.

### Clickable designer preview selection and visual reveal — post-v0.5.1 Tranche 4 full-commit gate

The fourth post-v0.5.1 surface tranche makes the reconstructed preview itself an editor selection surface without moving stable identity or selection semantics into a GUI backend. `DesignerPreviewSelectionSurface` in `app/framework/designer_preview_selection.py` derives ephemeral targets from the current `DesignerPreviewHost` stable-ID/component map, revalidates a clicked ID against the current snapshot, then delegates selection/focus and hierarchy reveal through `DesignerWorkspace`. Merely selecting a preview control therefore remains dirty-neutral, history-neutral and preview-generation-neutral.

Concrete hosts are isolated under `app/engine/designer_preview_selection_hosts/`. Dear PyGui performs native hover hit-testing only inside the adapter, resolves nested hits to the deepest semantic target and draws a transient viewport rectangle around the selected rendered item. Tkinter binds the current native preview widgets/mounts and uses a transient highlight on the renderer-created mount frame. Neither outline is part of the semantic `Component` tree or designer project data. Whole-preview replacement continues to invalidate native items by design; the surface refreshes after accepted edits/history operations and rebinds the same stable IDs to the new native handles.

The three-pane designer-shell proof now supports two equivalent selection entry points: hierarchy-row selection and direct preview click. Either route converges on the same `DesignerWorkspace` selection/focus state, reveals the selected path in the hierarchy and retargets the same property inspector. The command surface and all document-changing operations retain their previously accepted ownership and checked preview-replacement semantics.

Preparation passes 12 / 12 preview-selection tests, 218 / 218 designer/relocation tests, 64 / 64 GUI-component tests, 38 / 38 live Tkinter tests under Xvfb and complete discovery at **821 / 821**. The tranche is distributed as a full-commit bundle rather than a separate implementation/acceptance-doc pair: before commit, real Windows must pass the tracked validator at the same counts, dual-backend designer/blank-app visual smoke, the normal SalixTorrent smoke and `pre_commit_check.bat`. Any failure keeps the tranche uncommitted.

Drag/drop/reparent/resize gestures, multi-selection/mixed-value editing, specialized callback/service/binding editors, file-dialog/template/paste policy, multi-document/autosave/recovery, incremental native-widget mutation and final public package/project-schema naming remain deferred. The permanent architecture remains dual-entry: code-first Python composition and designer/RAD authoring continue to converge on the same semantic component/runtime/backend contracts.
