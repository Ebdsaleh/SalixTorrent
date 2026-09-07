"""Application-runtime packaging and relocation regressions."""

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


RUNTIME_ROOT = PROJECT_ROOT / "app" / "runtime"


class RuntimePackagingTests(unittest.TestCase):
    def _runtime_python_files(self):
        return sorted(RUNTIME_ROOT.rglob("*.py"))

    def test_runtime_absolute_dependencies_are_standard_library_only(self):
        third_party = []
        stdlib = set(sys.stdlib_module_names)
        for path in self._runtime_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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

    def test_runtime_tree_imports_after_copy_and_package_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(RUNTIME_ROOT, temp_root / "portable_runtime")
            probe = textwrap.dedent(
                f"""
                import importlib
                import pkgutil
                import sys

                sys.path.insert(0, {str(temp_root)!r})
                package = importlib.import_module("portable_runtime")
                imported = [package.__name__]
                for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                    importlib.import_module(module.name)
                    imported.append(module.name)

                assert "portable_runtime.lifecycle" in imported
                assert "portable_runtime.scenes" in imported
                assert "portable_runtime.network" in imported
                assert "portable_runtime.paths" in imported
                assert "portable_runtime.diagnostics" in imported
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
            self.assertGreaterEqual(int(result.stdout.strip()), 6)

    def test_relocated_runtime_contracts_are_usable_without_application_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(RUNTIME_ROOT, temp_root / "portable_runtime")
            probe = textwrap.dedent(
                f"""
                import socket
                import sys
                from pathlib import Path
                sys.path.insert(0, {str(temp_root)!r})

                from portable_runtime.lifecycle import ApplicationRuntime, CallbackService
                from portable_runtime.network import format_endpoint, normalise_bind_address
                from portable_runtime.paths import RuntimePathSpec, RuntimePaths
                from portable_runtime.scenes import SceneRegistry

                calls = []
                runtime = ApplicationRuntime()
                runtime.services.register("probe", CallbackService(on_update=lambda delta: calls.append(delta)))
                runtime.start()
                runtime.update(0.5)
                runtime.stop()

                class Host:
                    def exists(self, item): return True
                    def show(self, item): calls.append(("show", item))
                    def hide(self, item): calls.append(("hide", item))

                scenes = SceneRegistry(Host())
                scenes.register("main", object(), container="container")
                assert scenes.activate("main") is True

                paths = RuntimePaths(
                    RuntimePathSpec("PortableProbe"),
                    bundle_directory=Path({str(temp_root)!r}),
                    application_directory=Path({str(temp_root)!r}),
                    environ={{}},
                    home=Path({str(temp_root)!r}),
                )

                assert calls[0] == 0.5
                assert normalise_bind_address("2001:0db8::1") == "2001:db8::1"
                assert format_endpoint("2001:db8::1", 80) == "[2001:db8::1]:80"
                assert paths.default_download_directory().name == "PortableProbe"
                assert scenes.current_name == "main"
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

    def test_runtime_package_root_does_not_freeze_final_api_or_version(self):
        source = (RUNTIME_ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("__version__", source)
        self.assertNotIn("from .lifecycle import *", source)
        self.assertNotIn("from .network import *", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
