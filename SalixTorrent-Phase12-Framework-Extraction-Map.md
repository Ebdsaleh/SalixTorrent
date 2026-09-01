# SalixTorrent Phase 12 — Localization Framework Extraction Map

**Status:** Stage 10 framework-extraction readiness checkpoint  
**Purpose:** Define the boundary between reusable localization infrastructure and SalixTorrent-specific adapters before the future umbrella application framework is split into its own repository.

---

## 1. Why this stage exists

SalixTorrent remains the reference application and proving ground. The localization subsystem should therefore continue to run inside SalixTorrent until its contracts are stable, but reusable components must stop accumulating torrent-client, Dear PyGui, packaging, and provider assumptions.

Stage 10 does **not** create a second framework repository and does **not** make SalixTorrent depend on unfinished external projects. It introduces explicit generic contracts, isolates application adapters, and adds an offline audit that prevents framework-candidate modules from drifting back toward product-specific coupling.

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

### `app/localization/pseudo.py`

Owns deterministic development pseudo-localization. It has no application/runtime dependency and preserves formatting placeholders while expanding visible text.

### `tools/localization/contracts.py`

Owns canonical source hashing and Python-format placeholder contracts. These operations are application-neutral and are shared by extraction, validation, review, translation memory, and translation providers.

### `tools/localization/translation_memory.py`

Owns the storage-neutral translation-memory service contract plus the current deterministic JSON backend. Stage 10 removes the architectural requirement that its source locale must be `en-AU`; `en-AU` remains only the backward-compatible default for the current SalixTorrent memory.

A future SQLite/SalixORM store should implement the same `TranslationMemoryStore` contract rather than forcing translation-pipeline callers to change.

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

Remains the compatibility singleton consumed throughout the current application. Stage 10 moves JSON catalog parsing/metadata checking into `JsonCatalogRepository` while preserving the public `LocalizationManager`, `tr()`, and `localization_manager()` API.

A future framework extraction can convert this into a generic runtime object receiving a `LocalizationProfile` and `CatalogRepository`, while SalixTorrent keeps a tiny singleton adapter if desired.

### `app/localization/documents.py`

Remains the SalixTorrent semantic Help/Glossary adapter. Its content path now resolves through the application profile boundary rather than directly owning bundle-path policy.

The semantic documentation engine itself already lives separately under `app/engine/documentation` and can be evaluated as its own framework extraction later.

---

## 4. Development/provider adapters

These modules are not runtime-framework candidates as-is:

### `tools/localization/provider_registry.py`

Provider-neutral at the public contract level, but currently bootstraps the built-in Google provider. Future framework packaging can move built-in provider registrations to plugins or entry-point configuration.

### `tools/localization/google_translate.py`

Google-specific development provider. It must remain optional and development-only.

### `tools/localization/review.py`

The review model is broadly reusable, but the current implementation still knows SalixTorrent catalog locations, override locations, and extraction-manifest layout. Extract only after those paths are injected through a project/tooling profile.

### `tools/localization/extract_strings.py`

The AST extractor is reusable in principle, but it currently knows SalixTorrent source roots plus the Help/Glossary semantic-document conventions. A future framework version should receive project source/catalog providers rather than hard-coded repository paths.

---

## 5. Runtime boundary introduced in Stage 10

Before Stage 10, `LocalizationManager` directly implemented JSON parsing and directly knew the bundle catalog root.

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

## 6. Translation-memory boundary introduced in Stage 10

Translation memory is now explicitly source-locale aware:

```text
TranslationMemoryStore
        |
        +-- JsonTranslationMemory(source_locale="en-AU")   current project
        |
        +-- JsonTranslationMemory(source_locale="fr-FR")   supported contract
        |
        +-- SQLiteTranslationMemory(...)                    future SalixORM backend
```

A memory file cannot be silently merged into another memory with a different canonical source locale. Cross-source-locale merge attempts fail rather than reinterpreting hashes under the wrong source language.

---

## 7. Extraction audit

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

The audit is intentionally small and strict. It is not a generic linter; it protects the extraction boundary that Stage 10 declares.

Commands:

```bat
python tools\localization\build_locales.py --framework-report
python tools\localization\build_locales.py --framework-audit
python tools\localization\build_locales.py --stage10-check
```

Windows one-shot validation:

```bat
tools\localization\stage10_validate_framework_readiness.bat
```

---

## 8. What is deliberately deferred

Stage 10 does **not**:

- create the umbrella framework repository;
- rename SalixTorrent packages prematurely;
- make SalixTorrent depend on SalixORM;
- replace JSON translation memory with SQLite;
- add an Argos/local-LLM provider;
- change runtime locale behavior;
- resume Stage 6B machine-translation population;
- perform Stage 8B human language review.

Those tasks should happen only when their dependencies and extraction boundaries are mature.

---

## 9. Future extraction sequence

Recommended order after the contracts have remained stable in the reference application:

1. Extract `app/localization/framework.py` and `pseudo.py` into the umbrella framework.
2. Extract source/placeholder contracts and translation-memory interfaces into framework development tooling.
3. Replace SalixTorrent's profile import with the framework package while keeping current locale/content data in SalixTorrent.
4. Move the generic localization runtime behind profile/repository injection.
5. Adapt review/extraction tooling to a project profile instead of repository constants.
6. Add the SalixORM-backed translation-memory storage adapter when SalixORM is stable.
7. Add optional offline/provider plugins independently of the runtime.
8. Only then remove compatibility copies from SalixTorrent.

At every step SalixTorrent remains the regression/reference application.

---

## 10. Extraction invariants

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

**Stage 10 principle:** separate contracts first, repositories later.
