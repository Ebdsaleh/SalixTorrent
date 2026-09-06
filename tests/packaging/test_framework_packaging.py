"""Framework packaging and relocation regressions.

Regression lineage:
- introduced during the post-v0.4.0 GUI/RAD framework extraction.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT


FRAMEWORK_ROOT = PROJECT_ROOT / "app" / "framework"


class FrameworkPackagingTests(unittest.TestCase):
    def _framework_python_files(self):
        return sorted(FRAMEWORK_ROOT.rglob("*.py"))

    def test_framework_internal_imports_are_package_relative(self):
        offenders = []
        for path in self._framework_python_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level == 0 and (
                        module == "app.framework" or module.startswith("app.framework.")
                    ):
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: from {module}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "app.framework" or alias.name.startswith(
                            "app.framework."
                        ):
                            offenders.append(
                                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: import {alias.name}"
                            )
        self.assertEqual([], offenders)

    def test_framework_absolute_dependencies_are_standard_library_only(self):
        third_party = []
        stdlib = set(sys.stdlib_module_names)

        for path in self._framework_python_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)

                for name in names:
                    root = name.split(".", 1)[0]
                    if root not in stdlib and root != "__future__":
                        third_party.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {name}"
                        )

        self.assertEqual([], third_party)

    def test_framework_tree_imports_after_copy_and_package_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            relocated = temp_root / "portable_framework"
            shutil.copytree(FRAMEWORK_ROOT, relocated)

            probe = textwrap.dedent(
                f"""
                import importlib
                import pkgutil
                import sys

                sys.path.insert(0, {str(temp_root)!r})
                package = importlib.import_module("portable_framework")
                imported = [package.__name__]
                for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                    importlib.import_module(module.name)
                    imported.append(module.name)

                assert "portable_framework.components" in imported
                assert "portable_framework.documentation" in imported
                assert "portable_framework.geometry" in imported
                assert "portable_framework.property_cascade" in imported
                assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
                assert not any(name == "dearpygui" or name.startswith("dearpygui.") for name in sys.modules)
                print(len(imported))
                """
            )

            result = subprocess.run(
                [sys.executable, "-I", "-c", probe],
                cwd=temp_root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            self.assertGreaterEqual(int(result.stdout.strip()), 19)

    def test_relocated_framework_contracts_are_usable_without_application_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(FRAMEWORK_ROOT, temp_root / "portable_framework")

            probe = textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {str(temp_root)!r})

                from portable_framework.components import Button, ComponentLayoutProfile
                from portable_framework.documentation import DocPage, DocumentationTheme
                from portable_framework.geometry import ContentMetrics, content_bounds
                from portable_framework.property_cascade import PropertySource, resolve_property
                from portable_framework.responsive import LayoutCoordinator

                button = Button("Run")
                profile = ComponentLayoutProfile("probe")
                page = DocPage(title="Portable")
                theme = DocumentationTheme()
                bounds = content_bounds(1000, metrics=ContentMetrics(horizontal_padding=20, maximum_width=700))
                resolved = resolve_property(
                    default="fallback",
                    validator=lambda value: isinstance(value, str),
                )

                class Host:
                    def install_viewport_resize(self, callback):
                        return True
                    def watch_item_resize(self, item, callback):
                        return None
                    def unwatch_item_resize(self, watch):
                        return None
                    def item_size(self, item):
                        return (400, 300)
                    def configure(self, item, **kwargs):
                        return True

                coordinator = LayoutCoordinator(Host())

                assert button.label == "Run"
                assert profile.name == "probe"
                assert page.title == "Portable"
                assert theme is not None
                assert bounds.width == 700
                assert coordinator.item_size("panel") == (400, 300)
                assert coordinator.width("panel", 320) is True
                assert resolved.value == "fallback"
                assert resolved.source is PropertySource.DEFAULT
                assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
                """
            )

            result = subprocess.run(
                [sys.executable, "-I", "-c", probe],
                cwd=temp_root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_framework_package_root_does_not_freeze_a_final_public_api(self):
        source = (FRAMEWORK_ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("__version__", source)
        self.assertNotIn("from .components import *", source)
        self.assertNotIn("from .documentation import *", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
