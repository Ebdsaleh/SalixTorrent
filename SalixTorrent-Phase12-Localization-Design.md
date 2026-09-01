# SalixTorrent Phase 12 Design
## Offline Localization Framework and Build-Time Translation Pipeline

**Project:** SalixTorrent
**Phase:** 12
**Status:** Design / Implementation Plan
**Primary source locale:** `en-AU`
**Initial supported locales:** `en-AU`, `en-GB`, `en-US`, `pt-BR`, `fil-PH`

---

## 1. Purpose

Phase 12 introduces a complete localization system for SalixTorrent.

The core design principle is:

> **Translation may require internet access during development, but the released SalixTorrent client must never require internet access merely to display a language.**

Translations are generated before release, stored as static locale resources, packaged with SalixTorrent, and loaded locally at runtime.

The localization system must cover:

- menus
- buttons
- headings
- tabs
- preferences
- dialogs
- confirmations
- status messages
- errors
- notifications
- tooltips
- Help
- Glossary
- diagnostics labels and explanatory text
- Create Torrent UI
- tray-menu text
- CLI/help text where appropriate
- About and shortcut text

The system must be extensible so additional languages can be added later without redesigning the application.

---

## 2. Initial Locale Set

SalixTorrent will initially support:

| Locale | Display Name | Role |
|---|---|---|
| `en-AU` | English (Australia) | Canonical/source locale |
| `en-GB` | English (United Kingdom) | Regional English localization |
| `en-US` | English (United States) | Regional English localization |
| `pt-BR` | Português (Brasil) | Full translation |
| `fil-PH` | Filipino | Full translation |

### 2.1 Canonical Locale

`en-AU` is the authoritative source language.

All source strings are authored first in Australian English. Other locale packs are derived from the canonical catalog.

### 2.2 Translation Provider Mapping

The runtime locale name and the translation provider's language code do not have to be identical.

For example:

```text
SalixTorrent locale    Translation target
-------------------    ------------------
fil-PH                 fil
```

The localization layer owns runtime locale identifiers. The development translation adapter owns provider-specific language identifiers.

This prevents the application from becoming coupled to Google or any other translation provider.

---

## 3. Key Requirements

### 3.1 Runtime Must Be Fully Offline

The installed, standalone, and portable builds must:

- contain all supported locale data
- never call Google Translate at runtime
- never require Google credentials
- never require a translation Python package
- never download a language pack before use
- switch language using local resources only

### 3.2 Translation Is a Development Tool

Online translation is permitted only in the development pipeline.

The translation tool may:

- connect to Google Cloud Translation
- translate new or changed source strings
- cache translations
- preserve reviewed/manual translations
- validate generated locale data
- emit packaged locale resources

### 3.3 English Must Always Be Available

If any locale resource is:

- missing
- incomplete
- invalid
- malformed
- incompatible with the current catalog

SalixTorrent must remain usable by falling back to canonical `en-AU` text.

Localization failure must never prevent startup.

---

## 4. Proposed Runtime Architecture

```text
Application UI / Documentation / CLI / Tray
                    |
                    v
          LocalizationManager
                    |
          +---------+---------+
          |                   |
          v                   v
   Active locale        en-AU fallback
          |                   |
          +---------+---------+
                    |
                    v
             Rendered text
```

Suggested source layout:

```text
app/
└── localization/
    ├── __init__.py
    ├── manager.py
    ├── locale_info.py
    └── locales/
        ├── en-AU/
        │   ├── ui.json
        │   ├── help.json
        │   └── glossary.json
        ├── en-GB/
        │   ├── ui.json
        │   ├── help.json
        │   └── glossary.json
        ├── en-US/
        │   ├── ui.json
        │   ├── help.json
        │   └── glossary.json
        ├── pt-BR/
        │   ├── ui.json
        │   ├── help.json
        │   └── glossary.json
        └── fil-PH/
            ├── ui.json
            ├── help.json
            └── glossary.json
```

The exact file layout may evolve during implementation, but locale content must remain data-driven and independent of the renderer.

---

## 5. LocalizationManager Responsibilities

The runtime localization manager should provide one authoritative interface for translated text.

Conceptually:

```python
tr(
    "queue.showing",
    "Showing {visible} / {total}",
    visible=visible,
    total=total,
)
```

The manager is responsible for:

- resolving the configured locale
- loading locale resources
- loading canonical `en-AU`
- returning translated values
- falling back to canonical values
- substituting named placeholders
- reporting missing keys
- reporting fallback counts
- exposing locale metadata
- supporting runtime language changes where practical
- providing diagnostics information

### 5.1 Source Text Beside the Call Site

Where practical, UI strings should retain their canonical source text beside the localization key.

Example:

```python
dpg.add_menu_item(
    label=tr("menu.file.open_torrent", "Open Torrent...")
)
```

Benefits:

- source code remains readable
- translators have context
- fallback text is immediately available
- extraction can be automated through Python AST parsing
- missing locale entries do not expose internal localization keys to users

### 5.2 Formatted Strings

Formatted text must use named placeholders:

```python
tr(
    "queue.showing",
    "Showing {visible} / {total}",
    visible=visible,
    total=total,
)
```

Avoid positional formatting such as:

```python
"Showing {} / {}"
```

Named placeholders are safer for languages that require different word order.

---

## 6. What Must and Must Not Be Translated

### 6.1 Translate SalixTorrent-Owned Human-Facing Text

Translate:

- UI labels
- menu items
- buttons
- tooltips
- dialog content
- confirmation text
- explanatory errors
- status messages
- notification text
- preferences descriptions
- diagnostics labels
- Help content
- Glossary content
- tray menu text
- CLI help and messages intended for humans

### 6.2 Do Not Translate Runtime Data

Do not translate:

- torrent filenames
- filesystem paths
- tracker URLs
- peer addresses
- peer client names
- torrent metadata authored by third parties
- hashes
- info hashes
- protocol values
- internal state identifiers
- error codes
- environment variables
- file extensions
- command-line flags

### 6.3 Protect Technical Vocabulary

The development translation pipeline must protect technical terms that should remain unchanged unless explicitly overridden.

Initial protected terms should include at least:

```text
SalixTorrent
BitTorrent
DHT
PEX
UPnP
NAT-PMP
IPv4
IPv6
BEP-5
BEP-9
BEP-10
BEP-20
BEP-52
MSE
MSE/PE
.torrent
magnet:
SHA-1
SHA-256
HTTP
UDP
TCP
```

This list should live in a data file rather than being hardcoded into translation logic.

Suggested file:

```text
tools/localization/protected_terms.json
```

---

## 7. Help and Glossary Localization

The existing semantic documentation system must be preserved.

Localization should affect human-readable content only.

The following must remain stable across locales:

- topic IDs
- glossary IDs
- cross-reference IDs
- media/resource paths
- semantic document structure
- layout properties
- internal links
- navigation relationships

Example canonical document:

```json
{
  "getting_started": {
    "title": "Getting Started",
    "summary": "...",
    "sections": []
  }
}
```

A translated locale may contain:

```json
{
  "getting_started": {
    "title": "...translated...",
    "summary": "...translated...",
    "sections": []
  }
}
```

The renderer should not contain English assumptions. It should render whichever locale document the localization subsystem supplies.

---

## 8. Development Tooling

Suggested development-tool layout:

```text
tools/
└── localization/
    ├── build_locales.py
    ├── extract_strings.py
    ├── google_translate.py
    ├── validate_locales.py
    ├── translation_cache.json
    ├── protected_terms.json
    └── manual_overrides/
        ├── en-GB.json
        ├── en-US.json
        ├── pt-BR.json
        └── fil-PH.json
```

The exact implementation may combine some scripts later, but responsibilities should remain separated.

---

## 9. Extraction Tool

`extract_strings.py` should discover only strings that are intentionally marked as localizable.

It must **not** blindly translate every string literal in the Python source tree.

### 9.1 Extraction Targets

The extractor should support:

- `tr(key, source_text, ...)` calls
- semantic Help documents
- Glossary documents
- explicit localization data sources
- CLI/help catalogs
- tray text
- other deliberately marked user-facing content

### 9.2 Python AST Parsing

Python source extraction should use the Python AST rather than regex where possible.

This provides safer discovery of calls such as:

```python
tr("menu.file.open_torrent", "Open Torrent...")
```

The extractor should record:

- localization key
- canonical text
- source file
- source line
- placeholders
- optional context/category
- source hash

Source-file information is for development diagnostics and should not be required at runtime.

---

## 10. Translation Provider

Google Cloud Translation is the first implemented development provider, not the localization architecture.

It must exist only in development tooling.

Suggested dependency separation:

```text
requirements.txt
requirements-build.txt
requirements-localization.txt
```

`requirements-localization.txt` contains packages required only to generate translations.

Normal SalixTorrent users must never need those packages.

Normal developers who do not generate translations should not be required to install them either.

---

## 11. Credentials and Security

Google credentials must:

- never be embedded in SalixTorrent
- never be committed to Git
- never appear in locale files
- never be bundled by PyInstaller
- never be stored in the portable package
- never be stored in the installer

The development tool should use standard environment-based or Google-supported authentication.

Example conceptual workflow:

```text
Developer environment
    |
    +--> authenticated translation tool
    |
    +--> generated locale files
             |
             v
           Git
             |
             v
         PyInstaller
```

Only translated output enters the application package.

---

## 12. Translation Cache

The localization pipeline must maintain a cache to avoid retranslating unchanged content.

Each cached item should identify at least:

- localization key
- source locale
- target locale
- source text
- source hash
- translated text
- translation status
- optional provider metadata
- optional review state

Conceptually:

```json
{
  "queue.showing": {
    "source_hash": "...",
    "pt-BR": {
      "translation": "...",
      "status": "machine"
    }
  }
}
```

### 12.1 Cache Rule

If:

```text
current source hash == cached source hash
```

then the existing translation should be reused.

If the canonical source changes, only the changed entry should be sent for translation again.

This reduces:

- API usage
- translation cost
- build time
- unnecessary translation churn
- accidental loss of reviewed wording

---

## 13. Manual Overrides and Review

Machine translation is a starting point, not absolute authority.

The pipeline must allow a human-reviewed translation to override machine-generated output.

Conceptual precedence:

```text
Canonical source
      |
      v
Machine translation
      |
      v
Manual reviewed override
      |
      v
Packaged locale
```

Once an entry is reviewed/locked, routine translation regeneration should not overwrite it unless:

- its source text changed
- the reviewer explicitly unlocks it
- a force-regeneration option is supplied

This is especially important for:

- BitTorrent terminology
- network terminology
- Help
- Glossary
- warnings
- security/privacy explanations
- technical diagnostics

---

## 14. Placeholder Validation

Translations must preserve formatting placeholders exactly.

Canonical:

```text
Connected peers: {count}
```

Valid translated entry:

```text
... {count} ...
```

Invalid translated entry:

```text
... {contador} ...
```

The validator must compare placeholder sets.

Examples:

```text
{count}
{path}
{port}
{rate}
{visible}
{total}
{torrent_name}
```

A translation is invalid if:

- a placeholder is missing
- an unexpected placeholder is added
- placeholder syntax is damaged
- formatting braces are malformed

Invalid translations must not silently enter release packages.

---

## 15. Structural Validation

For every locale, validation should check:

- JSON syntax
- expected files exist
- locale metadata is valid
- keys are known
- duplicate keys do not exist
- required document structure is preserved
- placeholders match
- protected terms are intact where required
- semantic Help IDs are preserved
- Glossary IDs are preserved
- links target valid IDs
- untranslated/missing entries are reported
- stale entries are reported
- encoding is UTF-8
- control characters are valid
- format strings compile safely

The validator should return a non-zero exit status when release-blocking errors exist.

---

## 16. Runtime Fallback Policy

Runtime lookup:

```text
Requested locale
      |
      v
Does translated key exist and validate?
      |
  +---+---+
  |       |
 Yes      No
  |       |
  v       v
Use it   en-AU fallback
```

Example:

```text
Requested locale: pt-BR
Localized entries available: 2103
Missing entries: 1
Fallback entries used: 1
```

The missing Portuguese key should display canonical English, not an internal localization key and not an empty UI control.

---

## 17. Locale Selection

Preferences should expose:

```text
LANGUAGE

Application language
[ System Default              v ]

    System Default
    English (Australia)
    English (United Kingdom)
    English (United States)
    Português (Brasil)
    Filipino
```

Suggested persisted values:

```json
{
  "language": "auto"
}
```

or:

```json
{
  "language": "pt-BR"
}
```

### 17.1 System Default

`auto` should inspect the local operating-system/user locale without network access.

Conceptual mapping:

```text
en-AU  -> en-AU
en-GB  -> en-GB
en-US  -> en-US
pt-BR  -> pt-BR
fil-PH -> fil-PH
```

Unsupported system locales fall back to:

```text
en-AU
```

The user can always manually select a supported locale.

---

## 18. Runtime Language Switching

Preferred behavior:

- changing the language updates the UI without restarting where practical
- if specific complex windows cannot be safely updated live, SalixTorrent may request a restart

The implementation should favor a clean centralized rebuild/update mechanism rather than manually updating hundreds of widgets one by one.

During Phase 12 implementation, live switching should be evaluated against Dear PyGui behavior and current application architecture.

A restart requirement is acceptable if it produces significantly safer behavior.

---

## 19. Diagnostics

Help -> Diagnostics should expose localization information.

Suggested fields:

```text
Localization
Requested locale: pt-BR
Active locale: pt-BR
Canonical locale: en-AU
Locale source: User preference
Locale pack: Bundled
UI entries loaded: 2103
Fallback entries used: 1
Help locale: pt-BR
Glossary locale: pt-BR
Catalog validation: Warning
```

When fully complete:

```text
Catalog validation: OK
Fallback entries used: 0
```

This will make localization problems easy to diagnose without requiring users to inspect files.

---

## 20. Layout Expansion

Translations may be longer than canonical English.

Phase 12 must therefore audit fixed-size UI assumptions.

The development tooling should calculate approximate expansion ratios.

Example report:

```text
Potential layout expansion

settings.interface_lock
    en-AU: 31 characters
    pt-BR: 54 characters
    ratio: 1.74x

menu.update_trackers
    en-AU: 26 characters
    pt-BR: 41 characters
    ratio: 1.58x
```

This report is advisory, not automatically an error.

The responsive-layout system should remain responsible for rendering.

Items with extreme expansion ratios should be manually inspected.

---

## 21. Font and Unicode Requirements

SalixTorrent must use fonts capable of displaying all characters used by supported locales.

The localization phase should verify:

- UTF-8 resource loading
- Portuguese diacritics
- Filipino text
- punctuation variants
- typographic apostrophes/quotes where used
- fallback-glyph behavior
- Dear PyGui font atlas compatibility

Future language additions may require broader Unicode ranges and alternative bundled/system font strategies.

---

## 22. CLI Localization

CLI output should be categorized.

Translate:

- user help
- normal explanatory output
- user-facing errors
- progress labels where useful

Do not translate:

- machine-readable output modes
- shell flags
- paths
- hashes
- protocol tokens
- stable diagnostic identifiers intended for automation

If SalixTorrent later gains JSON/machine output, it must remain locale-independent.

---

## 23. Tray Localization

Tray backends should consume semantic localization keys rather than platform-specific English text.

Example conceptual actions:

```text
tray.open
tray.pause_all
tray.resume_all
tray.exit
```

All backends use the same localized values supplied by the application localization manager.

Native operating-system text that is not owned by SalixTorrent does not need translation.

---

## 24. Notifications

Notification titles and messages owned by SalixTorrent should be localized.

Example:

```text
notification.download_complete.title
notification.download_complete.body
```

Runtime torrent names inserted into notifications are data and must not be translated.

---

## 25. Packaging

PyInstaller must bundle the locale resources into:

- standalone build
- portable build
- installer build

The resource-path layer introduced in Phase 10 must be used to locate bundled locale resources.

Locale files must never depend on the development working directory.

Portable mode changes writable-state paths but should not change where immutable bundled locale data is resolved.

---

## 26. Development Workflow

Recommended commands:

### Extract/update canonical catalog

```bat
python tools\localization\build_locales.py --extract
```

### Translate new/changed strings

```bat
python tools\localization\build_locales.py --translate
```

### Validate locale packs

```bat
python tools\localization\build_locales.py --validate
```

### Full localization generation

```bat
python tools\localization\build_locales.py --all
```

Useful future options may include:

```text
--locale pt-BR
--locale fil-PH
--force
--dry-run
--report
--changed-only
--no-network
```

`--no-network` should still be able to rebuild final locale resources entirely from cache/manual overrides.

---

## 27. Suggested Build Pipeline

```text
                    DEVELOPMENT

Canonical en-AU source
        |
        +--> marked UI strings
        +--> Help
        +--> Glossary
        +--> CLI/tray/notifications
        |
        v
String extraction
        |
        v
Canonical catalog
        |
        +-------------------------------+
        |                               |
        v                               v
Translation cache               Manual overrides
        |                               |
        +---------------+---------------+
                        |
                        v
              Google translation
               (changed only)
                        |
                        v
                  Validation
                        |
                        v
              Static locale packs
                        |
                        v
                   PyInstaller
                        |
                        v

                       RELEASE

                 SalixTorrent.exe
                        |
          +-------------+-------------+
          |             |             |
        en-AU         en-GB         en-US
          |             |             |
        pt-BR         fil-PH          ...
                        |
                        v
                NO NETWORK REQUIRED
```

---

## 28. Source Control Policy

Commit:

- localization runtime
- locale manifests
- generated locale packs
- canonical catalogs
- protected-term definitions
- manual overrides
- translation tool source
- validation tooling

Do not commit:

- Google API credentials
- service-account private keys
- local authentication tokens
- machine-specific credential files

Whether `translation_cache.json` is committed should be decided during implementation.

Preferred approach:

- commit deterministic translation cache if it contains no secrets
- this improves reproducibility and prevents unnecessary API calls across machines

If the provider returns metadata that should not be stored, normalize the cache before committing.

---

## 29. Testing Strategy

### 29.1 Unit Tests

Test:

- locale resolution
- unsupported-locale fallback
- missing-key fallback
- placeholder substitution
- malformed placeholder rejection
- locale metadata
- translation cache behavior
- override precedence
- protected-term handling
- OS-locale mapping
- catalog validation
- Help/Glossary structural equivalence

### 29.2 Integration Tests

Test:

- UI boots in every locale
- Preferences language selection persists
- Help loads in every locale
- Glossary loads in every locale
- CLI starts in every locale
- tray labels resolve correctly
- notifications resolve correctly
- locale resources resolve in source mode
- locale resources resolve in frozen mode
- portable mode resolves bundled resources correctly
- missing locale file falls back safely

### 29.3 Release Validation

For each supported locale:

```text
[ ] Application starts
[ ] Main menus readable
[ ] Preferences readable
[ ] Torrent list readable
[ ] Details panels readable
[ ] Create Torrent readable
[ ] Help readable
[ ] Glossary readable
[ ] Diagnostics readable
[ ] Tray menu readable
[ ] Notifications readable
[ ] No localization exceptions
[ ] No exposed localization keys
[ ] No broken placeholders
[ ] No missing-glyph boxes
```

---

## 30. Translation Quality Policy

Machine translation should be treated as:

> **Generated draft localization**

not as guaranteed editorial quality.

Priority for manual review:

1. warnings and destructive-action confirmations
2. security/privacy wording
3. networking explanations
4. Help
5. Glossary
6. Preferences descriptions
7. common UI labels
8. diagnostics
9. low-impact status text

Regional English packs should also be reviewed where terminology differences matter.

---

## 31. Failure Policy

Localization must fail safely.

### Development failures

The development tool may stop the build on:

- malformed locale resources
- placeholder mismatch
- broken semantic document structure
- invalid locale manifest
- duplicated keys
- missing canonical source values

### Runtime failures

Runtime localization should not terminate SalixTorrent.

On runtime locale failure:

1. log the error
2. activate canonical `en-AU`
3. continue startup
4. expose the failure in Diagnostics

---

## 32. Phase 12 Implementation Order

### Stage 1 - Localization Foundation

- [x] Add `LocalizationManager`
- [x] Define supported locale metadata
- [x] Define `tr()` API
- [x] Add `en-AU` canonical fallback
- [x] Add Preferences language setting
- [x] Add system-locale detection
- [x] Add diagnostics fields

### Stage 2 - UI String Migration

- [x] Main menus
- [x] torrent list/view
- [x] torrent details
- [x] Preferences
- [x] dialogs
- [x] errors
- [x] status messages
- [x] notifications
- [x] tray
- [x] Create Torrent
- [x] CLI human-facing text

**Stage 2 status (2026-09-01): implementation complete.** Primary direct Dear
PyGui strings are localization-aware and stable internal values are translated
only for presentation. The canonical UI catalog contains 649 entries. Target
locale population is intentionally deferred until the canonical catalog is
stable; missing target entries continue to fall back to bundled `en-AU`.

### Stage 3 - Semantic Documentation Migration

- [x] Help content extracted from renderer assumptions
- [x] Glossary content extracted
- [x] stable topic/glossary IDs preserved
- [x] locale-specific Help resources
- [x] locale-specific Glossary resources

**Stage 3 status (2026-09-01): implementation complete.** Canonical Help and
Glossary authoring data now lives under `app/localization/content/` rather than
in Dear PyGui view modules. Help topics, sections and Glossary terms use stable
locale-neutral IDs; related-term links are validated against the Glossary; and
locale catalogs carry only translated wording. Canonical `en-AU` Help/Glossary
catalogs are generated from the semantic sources and frozen builds package both
the source topology and locale overlays. Target-language document wording remains
intentionally deferred to the translation-generation stage and therefore uses
offline `en-AU` fallback for now.

### Stage 4 - Development Extraction Tool

- [x] Python AST extraction
- [x] documentation extraction
- [x] canonical catalog generation
- [x] source hash tracking
- [x] duplicate-key detection
- [x] placeholder discovery

**Stage 4 checkpoint:** Canonical extraction is reproducible from authoritative
source rather than carrying old generated entries forward. `--check` performs a
non-mutating drift check, while `--report` exposes source locations, safe key
reuse, placeholder contracts, and dynamic `tr()` audit results. The committed
`extraction_manifest.json` records deterministic source hashes and formatting
contracts for all UI, Help, and Glossary keys.

### Stage 5 - Translation Pipeline

- [x] Google Cloud Translation adapter
- [x] `requirements-localization.txt`
- [x] protected-term handling
- [x] translation cache
- [x] changed-only translation
- [x] manual override support
- [x] reviewed/locked translations

**Stage 5 checkpoint:** Translation generation is development-only and defaults
to Google Cloud Translation v3 using `general/translation-llm`, with project
discovery through explicit CLI/environment configuration or Application Default
Credentials. `--dry-run` produces a non-mutating changed-only plan, while
`--no-network` rebuilds only from source-hash-valid cache entries and manual
overrides. Pre-Stage-5 bundled translations are adopted once into the deterministic
cache; new/changed strings are batched for the provider, technical tokens and
format placeholders are protected and validated, manual overrides are treated as
reviewed/locked authority, and provider failures leave the previous packaged
locale/cache intact. Stage 6 is responsible for actually generating the remaining
locale-pack translations with development credentials.

### Stage 6 - Generate Initial Locale Packs

- [x] local generation-status report
- [x] Google client/auth/project preflight doctor
- [x] optional authenticated one-request API probe
- [x] stale-extraction guard before provider calls
- [x] one-shot changed-only generation + strict validation
- [x] tracked Windows Stage-6 generation helper
- [ ] `en-GB` generated and strict-validated
- [ ] `en-US` generated and strict-validated
- [ ] `pt-BR` generated and strict-validated
- [ ] `fil-PH` generated and strict-validated

**Stage 6 generation checkpoint:** The generation harness is implemented and can
be exercised before translation through `--status`, `--dry-run` and `--doctor`.
The actual four locale packs are not marked complete until the credentialed
`--generate-initial` run succeeds on a developer machine and strict validation
reports zero missing translations. Google credentials are never committed or
bundled with SalixTorrent.

**Stage 6B population is currently on hold by design.** The provider-neutral/global
translation-memory direction is being evaluated before spending on bulk cloud
translation. This does not block Stage 7 validation/packaging or Stage 8 review
infrastructure.

### Stage 7 - Validation and Packaging

- [x] locale validator hardening
- [x] placeholder/format validation
- [x] Help/Glossary structural validation
- [x] catalog metadata/hash validation
- [x] stale translation provenance validation
- [x] protected technical terminology validation
- [x] deterministic locale metadata manifest
- [x] locale script/direction/font-profile capability metadata
- [x] `en-XA` pseudo-locale expansion audit
- [x] runtime missing/corrupt target-pack fallback diagnostics
- [x] PyInstaller resource inclusion contract
- [x] offline Stage-7 Windows validation helper
- [ ] native standalone smoke validation
- [ ] native portable smoke validation
- [ ] native installer smoke validation

**Stage 7 implementation checkpoint (2026-09-01):** Offline hardening is
implemented. `--extract` now regenerates both canonical catalogs and the runtime
locale manifest; `--check` verifies both manifests; and `--stage7-check` combines
pseudo-localization, packaging-resource and hardened catalog validation without
contacting any translation provider. Runtime target-catalog corruption is fail-closed
to canonical `en-AU` and surfaced through structured catalog-health/fallback
diagnostics. The remaining Stage-7 items are native Windows frozen/portable/installer
smoke tests on the developer machine, not architecture work.

### Stage 8A - Translation Review Infrastructure

- [x] provider-neutral review-state classification
- [x] missing / review-needed / reviewed / locked / stale / invalid states
- [x] deterministic offline review-bundle export
- [x] canonical source hash and extraction-context handoff
- [x] reviewer notes and provenance metadata
- [x] reviewed/locked promotion into rich manual overrides
- [x] stale-source fail-closed import
- [x] placeholder and protected-term import validation
- [x] reviewed override freshness validation
- [x] tracked offline Windows review-audit helper

**Stage 8A implementation checkpoint (2026-09-01):** Review infrastructure is
complete and fully offline. `--review-report` separates missing content from existing
translations awaiting human review. `--review-export` produces an ignored working
bundle containing source text/hash, placeholders, source locations, translation and
provider provenance. Reviewers explicitly promote entries to `reviewed` or `locked`;
`--review-import` validates the complete handoff before changing project artifacts and
records accepted strings as source-hash-bound authoritative manual overrides. Canonical
source changes therefore invalidate prior review rather than silently carrying approval
forward. Stage 8A can remain green while Stage 6B translation population is paused.

### Stage 8B - Manual Language Review

- [ ] warnings
- [ ] confirmations
- [ ] security/privacy terminology
- [ ] BitTorrent terminology
- [ ] Help
- [ ] Glossary
- [ ] high-visibility UI

**Stage 8B is content-dependent and remains on hold with Stage 6B.** The review
infrastructure is ready; actual language review begins once target locale packs contain
the strings to be reviewed.

### Stage 9 - Provider-Neutral Translation Memory Foundation

- [x] provider-neutral translation-provider contract/registry
- [x] lazy Google Cloud provider registration
- [x] explicit provider selection in development tooling
- [x] storage-neutral translation-memory service contract
- [x] deterministic JSON memory backend
- [x] target-locale + semantic-catalog + source-hash identity
- [x] placeholder/source-hash integrity checks
- [x] source-based reuse independent of SalixTorrent localization keys
- [x] translation-cache to translation-memory bootstrap
- [x] fail-closed memory merge/conflict reporting
- [x] configurable project/shared memory path
- [x] no-network translation-memory reuse
- [x] provider/memory diagnostics and Windows validation helper
- [ ] future SQLite/SalixORM translation-memory backend
- [ ] future offline/local translation provider adapter

**Stage 9 implementation checkpoint (2026-09-01):** The development translation
pipeline no longer treats the Google/key cache as the long-term reusable architecture.
`translation_cache.json` remains the SalixTorrent key-level incremental cache, while
`translation_memory.json` is an exact-source memory keyed by target locale, semantic
catalog and canonical source hash. The checked-in project memory bootstraps the current
452 seeded key records into 432 deduplicated candidates (108 per target locale).
Translation planning/generation now checks reviewed overrides, the key cache, and then
translation memory before a provider is contacted. Memory files can be relocated via
`SALIX_LOCALIZATION_MEMORY`/`--memory-path` or merged fail-closed from another compatible
memory. The initial JSON backend is intentionally transitional: a future SalixORM/SQLite
store can implement the same service boundary without coupling SalixTorrent runtime
localization to an ORM or translation provider. Stage 6B and Stage 8B remain paused.

---

### Stage 10 - Framework Extraction Readiness

- [x] provider-neutral `LocaleDescriptor` and `LocalizationProfile` contracts
- [x] storage-neutral runtime `CatalogRepository` contract
- [x] deterministic reusable `JsonCatalogRepository`
- [x] explicit SalixTorrent localization/resource profile adapter
- [x] runtime manager delegates JSON parsing/metadata validation to repository boundary
- [x] semantic document resource location routed through the SalixTorrent profile adapter
- [x] translation-memory source locale made explicit/configurable
- [x] fail-closed cross-source-locale memory loading/merge behavior
- [x] offline framework-extraction dependency/product-coupling audit
- [x] framework extraction map/report
- [x] tracked Windows Stage-10 validation helper
- [ ] physically extract localization components into the future umbrella framework
- [ ] replace JSON translation-memory storage with a future SQLite/SalixORM adapter

**Stage 10 implementation checkpoint (2026-09-01):** SalixTorrent remains the
reference application, but the first reusable localization contracts are now explicitly
product/GUI/provider neutral. `LocalizationManager` remains the compatibility facade;
JSON catalog parsing is delegated to a generic repository and SalixTorrent bundle-path
policy is isolated in `app.localization.profile`. The current translation memory still
defaults to `en-AU`, but the storage contract accepts other canonical source locales and
refuses accidental cross-source-locale merges. `framework_audit.py` protects the modules
that are intended to be extractable unchanged and records the application/provider
adapters that still require injection work. Physical repository extraction and the
SalixORM-backed memory store remain deliberately deferred. Stage 6B and Stage 8B remain
paused.

---

## 33. Phase 12 Completion Criteria

Phase 12 is complete when:

- [ ] `en-AU` is the canonical locale
- [ ] `en-GB` is bundled and usable offline
- [ ] `en-US` is bundled and usable offline
- [ ] `pt-BR` is bundled and usable offline
- [ ] `fil-PH` is bundled and usable offline
- [ ] language selection persists
- [ ] system-default language selection works
- [ ] unsupported system locales fall back to `en-AU`
- [ ] all SalixTorrent-owned user-facing strings are localization-aware
- [ ] Help is localized
- [ ] Glossary is localized
- [ ] tray text is localized
- [ ] relevant CLI text is localized
- [ ] notifications are localized
- [ ] runtime requires no translation service or internet connection
- [ ] development translation uses changed-only caching
- [ ] manual overrides are preserved
- [ ] placeholders are validated
- [ ] protected technical terms are handled
- [ ] missing translations fall back to `en-AU`
- [ ] Diagnostics reports localization state
- [ ] locale resources are packaged correctly
- [ ] source, standalone, portable, and installed Windows builds pass localization smoke tests
- [ ] full regression suite passes

---

## 34. Non-Goals for Phase 12

Unless implementation exposes a strong need, Phase 12 does not initially require:

- runtime downloading of language packs
- community translation servers
- automatic user-generated translation uploads
- cloud synchronization of language preferences
- right-to-left language support
- runtime machine translation
- translating torrent metadata supplied by third parties
- translating tracker/server responses
- localizing machine-readable protocol output

The architecture should not prevent future right-to-left or additional-script support, but those are not required for the first localization release.

---

## 35. Future Expansion

Once this framework is stable, adding another language should primarily involve:

1. add locale metadata
2. map provider language code
3. run translation tool
4. review terminology
5. validate
6. package
7. smoke-test

The application itself should require little or no new localization-specific code.

Possible future locales may be added without changing the Phase 12 architecture.

---

## 36. Architectural Principle

The intended long-term boundary is:

```text
SalixTorrent application
        |
        v
LocalizationManager
        |
        v
Bundled static locale data
```

Translation providers exist only here:

```text
Developer tooling
        |
        v
Provider registry + translation memory
        |
        +--> Google adapter (optional)
        +--> future offline/local adapters
        |
        v
Validated static locale data
```

The released application does not know, need to know, or care how the translation was produced.

That separation is the central design rule for Phase 12.

---

## 37. Proposed Roadmap Entry

```text
Phase 12
    Offline localization framework
    en-AU canonical source catalog
    en-GB localization
    en-US localization
    pt-BR localization
    fil-PH localization
    system/user locale selection
    runtime fallback to en-AU
    Help/Glossary localization
    UI/CLI/tray/notification localization
    build-time string extraction
    provider-neutral translation development tool
    optional Google translation adapter
    source-hash translation cache
    reusable translation memory
    manual/reviewed translation overrides
    translation review/provenance infrastructure
    protected technical terminology
    placeholder/catalog validation
    locale diagnostics
    frozen/portable packaging validation
    framework-neutral localization contracts
    framework extraction readiness audit
```

---

**Design rule summary:**
**Online during translation generation is acceptable. Online during application localization is not.**
