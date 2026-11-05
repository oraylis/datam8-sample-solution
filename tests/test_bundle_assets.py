"""Verify configurable asset paths and Git-style sync filters without cloud access."""
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bundle_assets import required_assets  # noqa: E402


class BundleAssetsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="datam8-bundle-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bundle = self.root / "delivery"
        self.bundle.mkdir()
        self.write("code/nested/entry.py", "# MAGIC %run ../../shared/helper\n")
        self.write("shared/helper.py", "# Shared notebook\n")
        self.write("extensions/extra.py", "# Additional authored notebook\n")
        self.write(".gitignore", "code/\nshared/*.py\n")
        resource = {"resources": {"jobs": {"example": {"tasks": [{"task_key": "entry", "notebook_task": {
            "notebook_path": "${workspace.file_path}/${var.notebook_dir}/entry"}}]}}}}
        self.write("artifacts/jobs/main.yaml", yaml.safe_dump(resource))
        extra = {"resources": {"pipelines": {"example": {"libraries": [{"file": {
            "path": "${workspace.file_path}/extensions/extra.py"}}]}}}}
        self.write("authored/pipeline.yml", yaml.safe_dump(extra))
        self.configuration = {
            "bundle": {"name": "example"},
            "include": ["../artifacts/**/*.yaml", "../authored/*.yml"],
            "variables": {"notebook_dir": {"default": "code/nested"}},
            "sync": {"paths": ["../code", "../shared", "../extensions"],
                     "include": ["../code/**/*.py", "../shared/[h]elper.py"]}}

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def check(self):
        (self.bundle / "databricks.yml").write_text(yaml.safe_dump(self.configuration), encoding="utf-8")
        return required_assets(self.bundle, self.root / "artifacts")

    def test_custom_layout_recursive_includes_extra_resources_and_globs(self):
        self.assertEqual(self.check(), ["code/nested/entry.py", "extensions/extra.py", "shared/helper.py"])

    def test_unignored_assets_do_not_need_explicit_sync_include(self):
        (self.root / ".gitignore").unlink()
        self.configuration["sync"].pop("include")
        self.assertIn("extensions/extra.py", self.check())

    def test_ignored_assets_require_reinclusion(self):
        self.configuration["sync"]["include"] = ["../shared/*.py"]
        with self.assertRaisesRegex(ValueError, "excluded from bundle sync"):
            self.check()

    def test_exclude_glob_rejects_referenced_dependency(self):
        self.configuration["sync"]["exclude"] = ["../shared/*.py"]
        with self.assertRaisesRegex(ValueError, "excluded from bundle sync: shared/helper.py"):
            self.check()

    def test_include_negation_does_not_reinclude_ignored_asset(self):
        self.configuration["sync"]["include"].append("!../code/nested/entry.py")
        with self.assertRaisesRegex(ValueError, "excluded from bundle sync"):
            self.check()

    def test_include_cannot_add_assets_outside_selected_sync_paths(self):
        self.configuration["sync"]["paths"].remove("../shared")
        with self.assertRaisesRegex(ValueError, "excluded from bundle sync: shared/helper.py"):
            self.check()

    def test_missing_transitive_notebook_dependency_fails(self):
        (self.root / "shared/helper.py").unlink()
        with self.assertRaisesRegex(ValueError, "Missing %run dependency"):
            self.check()

    def test_generated_resource_coverage_remains_required(self):
        self.write("artifacts/omitted.yml", "resources: {}\n")
        with self.assertRaisesRegex(ValueError, "cover every generated resource YAML"):
            self.check()

    def test_inline_resources_and_default_sync_root(self):
        self.write("delivery/notebook.py", "# Local notebook\n")
        self.configuration = {"resources": {"jobs": {"local": {"tasks": [{"notebook_task": {
            "notebook_path": "${workspace.file_path}/notebook"}}]}}}}
        (self.bundle / "databricks.yml").write_text(yaml.safe_dump(self.configuration), encoding="utf-8")
        self.assertEqual(required_assets(self.bundle), ["notebook.py"])
