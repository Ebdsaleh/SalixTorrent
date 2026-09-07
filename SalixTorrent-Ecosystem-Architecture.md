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
        +-- Tkinter                            planned compatibility GUI backend
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

Tkinter is the planned standard-library-compatible reference implementation for the common desktop surface. It should prove that framework contracts are not merely Dear PyGui concepts moved behind different names.

Tkinter is **not yet** a complete SalixTorrent presentation backend. Current source uses Tk support only for native file/folder dialogs. A full Tkinter backend must be introduced incrementally behind the same framework-facing contracts.

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
        +-- future Tkinter Canvas adapter
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

The first implementation tranche is prepared from the proven Speed view. Backend-neutral rolling telemetry/statistics and realtime graph coordination now live in the provisional framework, while Dear PyGui plot operations live in a concrete plot host. SalixTorrent's existing Speed snapshot/labels/rate semantics remain application-owned. A future Tkinter Canvas implementation should consume the same plot-facing contract rather than duplicate application logic.

### Stage C — engine/runtime services

Extract generic lifecycle, service, presentation-host and network-awareness mechanisms where the current application demonstrates a real reusable contract.

### Stage D — second GUI implementation

Build a small Tkinter compatibility backend incrementally, beginning with the common component/layout/window surface. Use it to challenge assumptions in the existing Dear PyGui-facing contracts.

The first proof should be a small backend-neutral demonstration application, not a wholesale Tkinter rewrite of SalixTorrent.

### Stage E — rich RAD presentation

Generalize live tables, state maps, diagnostic/status surfaces and other high-value patterns only when the application demonstrates reusable semantics.

### Stage F — designer prerequisites

Introduce component/property metadata, serialization and command/undo infrastructure needed for WYSIWYG editing.

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
        +-- future Tkinter Canvas host second-backend proof
```

The generic telemetry layer has no GUI dependency and is therefore usable by desktop, CLI/headless, tests, and future designer/runtime consumers. The visualization layer describes complete graph updates without importing Dear PyGui. Concrete plot creation, axis mutation, line-series updates, existence checks, and disposal remain adapter-owned.

The SalixTorrent Speed view deliberately still owns localized labels, Help/tooltips, transfer-rate unit conversion, torrent/global limit wording, and visible-window selection. This tranche proves a reusable data/plot seam without pretending the entire Speed view is a generic component.

Prepared validation adds 7 telemetry tests and 9 realtime-visualization tests while keeping the existing five framework-relocation tests. Full discovery is expected to advance from 416 to 432 tests on Windows with the same one expected non-Windows skip. `APP_VERSION` remains `0.5.0`; this is development work on `dev`, not a release/tag boundary.
