"""Offline audit for future extraction of localization infrastructure.

The audit does not move modules or change runtime behavior. It identifies a small
set of files that must remain application/GUI/provider neutral so they can later be
lifted into the umbrella Salix framework with minimal surgery.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

# These files are intended to be extractable without SalixTorrent, Dear PyGui,
# the torrent engine, Google libraries, or runtime path helpers.
EXTRACTABLE_MODULES = (
    Path("app/localization/framework.py"),
    Path("app/localization/runtime.py"),
    Path("app/localization/semantic.py"),
    Path("app/localization/pseudo.py"),
    Path("tools/localization/contracts.py"),
    Path("tools/localization/translation_memory.py"),
)

# These remain intentional adapters/consumers. The extraction map documents the seam
# rather than pretending the whole subsystem is generic already.
APPLICATION_ADAPTERS = (
    Path("app/localization/profile.py"),
    Path("app/localization/locale_info.py"),
    Path("app/localization/manager.py"),
    Path("app/localization/documents.py"),
)

DEVELOPMENT_ADAPTERS = (
    Path("tools/localization/provider_registry.py"),
    Path("tools/localization/google_translate.py"),
    Path("tools/localization/translation_memory_factory.py"),
    Path("tools/localization/translation_memory_salixorm.py"),
    Path("tools/localization/salixorm_memory_audit.py"),
    Path("tools/localization/review.py"),
    Path("tools/localization/extract_strings.py"),
)

PROHIBITED_IMPORT_PREFIXES = (
    "app.engine",
    "app.logic",
    "app.views",
    "dearpygui",
    "google",
)


@dataclass(frozen=True)
class ModuleAudit:
    path: str
    imports: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class FrameworkAudit:
    modules: tuple[ModuleAudit, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and all(item.ok for item in self.modules)

    @property
    def extractable_count(self) -> int:
        return len(self.modules)


def _imports(tree: ast.AST) -> tuple[str, ...]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                module = "." * node.level + str(node.module or "")
            else:
                module = str(node.module or "")
            found.add(module)
    return tuple(sorted(found))


def audit_module(relative_path: Path) -> ModuleAudit:
    path = ROOT / relative_path
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ModuleAudit(str(relative_path), (), (f"cannot read module: {exc}",))

    try:
        tree = ast.parse(source, filename=str(relative_path))
    except SyntaxError as exc:
        return ModuleAudit(str(relative_path), (), (f"syntax error: {exc}",))

    imports = _imports(tree)
    for imported in imports:
        normalized = imported.lstrip(".")
        if any(normalized == prefix or normalized.startswith(prefix + ".") for prefix in PROHIBITED_IMPORT_PREFIXES):
            errors.append(f"prohibited dependency {imported!r}")

    # A framework candidate must not carry application branding in executable or
    # documentation text. Generic 'Salix' identifiers are allowed because they are
    # intended framework names; the product name is not.
    if "salixtorrent" in source.lower():
        errors.append("contains SalixTorrent-specific product text")

    return ModuleAudit(str(relative_path), imports, tuple(errors))


def framework_audit() -> FrameworkAudit:
    modules = tuple(audit_module(path) for path in EXTRACTABLE_MODULES)
    errors: list[str] = []
    missing_adapters = [str(path) for path in (*APPLICATION_ADAPTERS, *DEVELOPMENT_ADAPTERS) if not (ROOT / path).is_file()]
    if missing_adapters:
        errors.append("missing documented adapter(s): " + ", ".join(missing_adapters))
    return FrameworkAudit(modules=modules, errors=tuple(errors))



def runtime_boundary_audit() -> tuple[str, ...]:
    """Verify SalixTorrent facades delegate to the generic runtime/services."""
    errors: list[str] = []
    manager_path = ROOT / "app/localization/manager.py"
    documents_path = ROOT / "app/localization/documents.py"
    manager = manager_path.read_text(encoding="utf-8")
    documents = documents_path.read_text(encoding="utf-8")

    if "LocalizationRuntime" not in manager:
        errors.append("manager.py does not delegate to LocalizationRuntime")
    for forbidden in ("import json", "import string", "import threading", "collections import Counter"):
        if forbidden in manager:
            errors.append(f"manager.py still owns generic runtime concern: {forbidden}")

    if "SemanticDocumentationService" not in documents or "SemanticDocumentationSource" not in documents:
        errors.append("documents.py does not delegate to semantic documentation services")
    for forbidden in ("import json", "from dataclasses import dataclass", "from functools import lru_cache"):
        if forbidden in documents:
            errors.append(f"documents.py still owns generic semantic concern: {forbidden}")

    return tuple(errors)

def extraction_map() -> dict[str, tuple[str, ...]]:
    return {
        "extractable_now": tuple(str(path) for path in EXTRACTABLE_MODULES),
        "application_adapters": tuple(str(path) for path in APPLICATION_ADAPTERS),
        "development_adapters": tuple(str(path) for path in DEVELOPMENT_ADAPTERS),
    }
