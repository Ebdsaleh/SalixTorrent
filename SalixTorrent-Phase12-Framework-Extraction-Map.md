# SalixTorrent Phase 12 — Localization Framework Extraction Map

**Status:** SalixORM translation-memory integration checkpoint

**Purpose:** Define the boundary between reusable localization infrastructure and SalixTorrent-specific adapters before the future umbrella application framework is split into its own repository.

---

## 1. Why this extraction boundary exists

SalixTorrent remains the reference application and proving ground. The localization subsystem should therefore continue to run inside SalixTorrent until its contracts are stable, but reusable components must stop accumulating torrent-client, Dear PyGui, packaging, and provider assumptions.

Stages 10–11 do **not** create a second framework repository and does **not** make SalixTorrent depend on unfinished external projects. It introduces explicit generic contracts, isolates application adapters, and adds an offline audit that prevents framework-candidate modules from drifting back toward product-specific coupling.

The intended future dependency direction is:

```text
SalixTorrent
    |
    v
Salix application/framework adapters
    |
    v
Reusable localization services
```

not:

```text
Reusable localization services
    |
    v
SalixTorrent / Dear PyGui / BitTorrent engine
```

---

## 2. Extractable now

The following modules are deliberately constrained so they can later be moved with little or no source modification:

### `app/localization/framework.py`

Owns provider-neutral runtime contracts:

- `LocaleDescriptor`
- `LocalizationProfile`
- `CatalogRepository`
- `JsonCatalogRepository`

It does not import SalixTorrent engine/view modules, Dear PyGui, runtime-path helpers, Google libraries, or provider tooling.

### `app/localization/runtime.py`

Owns provider-neutral offline runtime behavior:

- catalog loading through `CatalogRepository`;
- canonical per-key fallback;
- placeholder/format contracts;
- pseudo-locale transform injection;
- fallback/load-health diagnostics;
- runtime generation tracking.

Applications inject locale-resolution policy and storage/resource adapters. The module does not import SalixTorrent, Dear PyGui, runtime-path helpers, BitTorrent code, or translation providers.

### `app/localization/semantic.py`

Owns renderer-neutral semantic documentation contracts and services:

- `HelpTopic`;
- `SemanticDocumentRepository`;
- `JsonSemanticDocumentRepository`;
- `SemanticDocumentationSource`;
- `SemanticDocumentationService`.

Stable Help/Glossary IDs and localization-key generation are reusable; application content paths and the active translator are injected.

### `app/localization/pseudo.py`

Owns deterministic development pseudo-localization. It has no application/runtime dependency and preserves formatting placeholders while expanding visible text.

### `tools/localization/contracts.py`

Owns canonical source hashing and Python-format placeholder contracts. These operations are application-neutral and are shared by extraction, validation, review, translation memory, and translation providers.

### `tools/localization/translation_memory.py`

Owns the storage-neutral translation-memory service contract plus the deterministic JSON reference/default backend. The framework-boundary refactor removed the architectural requirement that its source locale must be `en-AU`; `en-AU` remains only the backward-compatible default for the current SalixTorrent memory. The SalixORM integration completes the store contract with iteration/statistics/audit/save operations plus shared semantic validation and fail-closed merge behavior.

The optional SalixORM implementation lives in a development adapter rather than this extractable module, so generic callers continue to depend only on `TranslationMemoryStore`.

---

## 3. SalixTorrent application adapters

These modules intentionally remain product-facing for now:

### `app/localization/profile.py`

Maps SalixTorrent runtime policy into framework-neutral contracts:

- application ID;
- canonical locale;
- supported locale metadata;
- catalog names;
- pseudo-locale policy;
- bundled catalog resource roots;
- semantic documentation content roots.

All SalixTorrent resource-path knowledge should converge here rather than leaking into generic catalog loading.

### `app/localization/locale_info.py`

Owns SalixTorrent's supported-locale list, OS locale mapping/fallback policy, user-facing locale labels, and current provider-code compatibility metadata.

Provider-specific language codes should eventually move fully into provider adapters when the localization module is extracted.

### `app/localization/manager.py`

Now a thin SalixTorrent compatibility singleton subclassing the generic `LocalizationRuntime`. It supplies the SalixTorrent profile, JSON catalog root, locale resolver and pseudo transform while preserving `LocalizationManager`, `tr()`, `localization_manager()` and existing diagnostics behavior.

### `app/localization/documents.py`

Now a thin SalixTorrent adapter over `SemanticDocumentationSource` and `SemanticDocumentationService`. It supplies the application's semantic-content path and active runtime translator while preserving the existing Help/Glossary helper API used by views and tests.

---

## 4. Development/provider adapters

These modules are not runtime-framework candidates as-is:

### `tools/localization/provider_registry.py`

Provider-neutral at the public contract level, but currently bootstraps the built-in Google provider. Future framework packaging can move built-in provider registrations to plugins or entry-point configuration.

### `tools/localization/google_translate.py`

Google-specific development provider. It must remain optional and development-only.

### `tools/localization/translation_memory_factory.py`

Development-time storage selection seam. It keeps JSON as the default/reference store, resolves optional SalixORM configuration, and lazily imports the SalixORM adapter only when selected. It intentionally stays outside the six generic extraction candidates.

### `tools/localization/translation_memory_salixorm.py`

Optional SalixORM `v0.2.0` / SQLite development-storage adapter implementing the generic translation-memory contract. It owns physical schema/migration policy and transactional persistence; generic runtime localization never imports it.

### `tools/localization/salixorm_memory_audit.py`

Offline integration/parity audit used to prove the complete checked-in JSON memory can be imported, reopened and audited through the SalixORM adapter without semantic drift. It is verification tooling rather than runtime framework code.

### `tools/localization/review.py`

The review model is broadly reusable, but the current implementation still knows SalixTorrent catalog locations, override locations, and extraction-manifest layout. Extract only after those paths are injected through a project/tooling profile.

### `tools/localization/extract_strings.py`

The AST extractor is reusable in principle, but it currently knows SalixTorrent source roots plus the Help/Glossary semantic-document conventions. A future framework version should receive project source/catalog providers rather than hard-coded repository paths.

---

## 5. Runtime boundary introduced by the framework-extraction work

Before the framework-boundary refactor, `LocalizationManager` directly implemented JSON parsing and directly knew the bundle catalog root.

The boundary is now:

```text
LocalizationManager                    SalixTorrent adapter
        |
        v
JsonCatalogRepository                  reusable
        |
        v
catalog-root resolver                  injected callback
        |
        v
salixtorrent_catalog_root()            SalixTorrent adapter
        |
        v
resource_path(...)                     application engine
```

This lets catalog format/storage evolve independently from SalixTorrent's resource-location policy.

---

## 6. Generic runtime and semantic-service boundary

The runtime-kernel refactor changes the runtime boundary from a repository-only seam into an actual reusable kernel:

```text
LocalizationManager                    SalixTorrent compatibility facade
        |
        v
LocalizationRuntime                    reusable
        |
        +-- LocalizationProfile         injected contract
        +-- CatalogRepository           injected storage
        +-- locale resolver             injected policy
        +-- pseudo transform            optional injected development behavior
```

Semantic documentation follows the same direction:

```text
app/localization/documents.py           SalixTorrent adapter
        |
        v
SemanticDocumentationService            reusable
        |
        +-- SemanticDocumentationSource
        +-- SemanticDocumentRepository
        +-- translator callback
```

The runtime-boundary audit rejects regressions where the SalixTorrent facades start reclaiming JSON parsing, placeholder/runtime state machinery, or semantic-document parsing.

---

## 7. Translation-memory storage boundary

Translation memory is now explicitly source-locale aware:

```text
TranslationMemoryStore
        |
        +-- JsonTranslationMemory(source_locale="en-AU")       default/reference project store
        |
        +-- JsonTranslationMemory(source_locale="fr-FR")       supported generic contract
        |
        +-- SalixORMTranslationMemory(SQLite file / URL)        optional SalixORM development backend
```

A memory file cannot be silently merged into another memory with a different canonical source locale. Cross-source-locale merge attempts fail rather than reinterpreting hashes under the wrong source language.

The SalixORM integration makes the storage seam concrete: provider/pipeline code obtains a `TranslationMemoryStore` through one development factory, while the SalixORM adapter stages writes until `save()` and persists them in one explicit transaction. JSON remains the default/reference implementation; storage choice does not enter runtime localization.

---

## 8. Extraction audit

The offline audit is implemented in:

```text
tools/localization/framework_audit.py
```

Framework-candidate modules are rejected if they gain direct dependencies on:

```text
app.engine
app.logic
app.views
dearpygui
google
```

or contain SalixTorrent product branding.

The audit is intentionally small and strict. It is not a generic linter; it protects the declared extraction boundary.

Commands:

```bat
python tools\localization\build_locales.py --framework-report
python tools\localization\build_locales.py --framework-audit
python tools\localization\build_locales.py --framework-check
```

Windows one-shot validation:

```bat
tools\localization\validate_framework_extraction.bat
```

---

## 9. What is deliberately deferred

The SalixORM storage integration still does **not**:

- create the umbrella framework repository;
- rename SalixTorrent packages prematurely;
- make ordinary SalixTorrent runtime localization depend on SalixORM;
- remove the deterministic JSON translation-memory reference/default backend;
- switch the project default memory backend to SalixORM before application mileage;
- add another offline translation-provider implementation;
- change runtime locale behavior;
- resume machine-translation population;
- perform manual language review.

Those tasks should happen only when their dependencies and extraction boundaries are mature.

---

## 10. Future extraction sequence

Recommended order after the contracts have remained stable in the reference application:

1. Keep exercising both JSON and SalixORM translation-memory implementations in SalixTorrent development tooling; convert any real defect into a storage-contract regression.
2. Extract `framework.py`, `runtime.py`, `semantic.py` and `pseudo.py` into the umbrella framework when the repository boundary is intentionally created.
3. Extract source/placeholder contracts and the generic translation-memory interface/JSON reference implementation into framework development tooling.
4. Keep the SalixORM adapter as an optional storage plugin/adapter rather than making the generic runtime depend on an ORM.
5. Replace SalixTorrent's generic-module imports with the framework package while keeping locale/content data and thin application adapters in SalixTorrent.
6. Adapt review/extraction tooling to a project profile instead of repository constants.
7. Add optional translation-provider plugins independently of the runtime.
8. Only then remove compatibility copies from SalixTorrent.

At every step SalixTorrent remains the regression/reference application.

---

## 11. Extraction invariants

1. Runtime localization must never require a translation provider.
2. Generic runtime code must not depend on Dear PyGui.
3. Generic localization code must not depend on BitTorrent/domain logic.
4. Product resource paths are injected by an application adapter.
5. Translation memory is storage-neutral.
6. Translation memory identity remains source-hash and semantic-context aware.
7. Source-locale mismatch is fail-closed.
8. SalixTorrent's existing `tr()` call sites remain source-compatible during extraction.
9. Framework extraction must not make the application less testable or less offline-capable.
10. SalixTorrent remains the proving ground until the extracted component passes both its own contract tests and the application's full regression suite.

---

**Storage-integration principle:** prove storage interchangeability and transactional durability behind the generic memory contract before changing defaults or physically splitting repositories.
