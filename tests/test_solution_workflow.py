"""Check generation isolation and an internal Consumer extension fixture offline."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bundle_assets import bundle_configuration, required_assets  # noqa: E402
from stage_databricks_bundle import stage_bundle_assets  # noqa: E402


def snapshot(folder):
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


class SolutionWorkflowTests(unittest.TestCase):
    def test_clean_isolation_bundle_assets_and_consumer_extension(self):
        with tempfile.TemporaryDirectory(prefix="datam8-workflow-") as directory:
            root = Path(directory) / "solution"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
                ".git", ".venv", "output", "__pycache__", ".ruff_cache", ".databricks"))
            descriptor = root / "ORAYLISDatabricksSample.dm8s"

            def cli(*arguments):
                result = subprocess.run([sys.executable, "-m", "datam8", *arguments, "-s", str(descriptor)],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            cli("validate")
            targets = json.loads(descriptor.read_text())["generatorTargets"]
            for target in targets:
                cli("generate", target["name"], "--clean-output")
            baseline = {target["name"]: snapshot(root / target["outputPath"]) for target in targets}
            bundle = root / "deployment/databricks"
            stage_bundle_assets(root)
            authored = {name: snapshot(root / name) for name in ("base", "model", "utils", "deployment")}
            # A clean must remove its own stale file, and preserve every other
            # target's bytes, including unrelated files, plus authored notebooks.
            for target in targets:
                for other in targets:
                    (root / other["outputPath"] / "stale.txt").write_text("sentinel")
                cli("generate", target["name"], "--clean-output")
                self.assertFalse((root / target["outputPath"] / "stale.txt").exists())
                # Documentation deliberately records its generation timestamp.
                baseline[target["name"]] = snapshot(root / target["outputPath"])
                for other in targets:
                    if other != target:
                        sentinel = root / other["outputPath"] / "stale.txt"
                        self.assertEqual(sentinel.read_text(), "sentinel")
                        sentinel.unlink()
                    self.assertEqual(snapshot(root / other["outputPath"]), baseline[other["name"]])
                for name, contents in authored.items():
                    self.assertEqual(snapshot(root / name), contents)

            assets = required_assets(bundle, bundle / "output/databricks")
            self.assertIn("utils/MigrationFramework.py", assets)
            self.assertIn("output/databricks/runtime/uc_sources.py", assets)
            configuration = bundle_configuration(bundle, bundle / "output/databricks")
            self.assertEqual(configuration["targets"]["dev"]["mode"], "development")
            self.assertNotIn("cluster_id", configuration["targets"]["dev"])
            self.assertIn("cluster_id", configuration["variables"])
            self.assertEqual(configuration["variables"]["unpause_schedules"]["default"], "PAUSED")
            self.assertEqual(configuration["resources"]["jobs"]["Create_All_Tables"]["max_concurrent_runs"], 1)
            date_tmdl = (root / "output/powerbi/tables/Date.tmdl").read_text()
            self.assertNotIn("dataType: integer", date_tmdl)
            self.assertIn("column DateID\n\t\tdataType: int64", date_tmdl)
            for job in configuration["resources"]["jobs"].values():
                self.assertNotIn("permissions", job)
            path = bundle / "databricks.yml"
            original = path.read_text()
            changed = yaml.safe_load(original)
            changed["sync"]["exclude"] = ["utils/**"]
            path.write_text(yaml.safe_dump(changed))
            with self.assertRaisesRegex(ValueError, "excluded"):
                required_assets(bundle, bundle / "output/databricks")
            path.write_text(original)

            entity_path = root / "model/040-Consumer/MasterData/Customer/Customer.json"
            customer = json.loads(entity_path.read_text())
            customer["attributes"].append({
                "name": "SourceSystem", "ordinalNumber": len(customer["attributes"]) + 1,
                "attributeType": "Text", "dataType": {"type": "string", "nullable": False},
                "dateAdded": "2026-01-01T00:00:00Z"})
            source = next(source for source in customer["sources"] if source["sourceLocation"] == 3000)
            source["mapping"].append({"sourceName": "SourceSystem", "targetName": "SourceSystem"})
            entity_path.write_text(json.dumps(customer, indent=2))
            cli("validate")
            for target in targets:
                cli("generate", target["name"], "--clean-output")
            self.assertEqual(snapshot(root / "output/databricks"), baseline["databricks"])
            self.assertIn("column SourceSystem", (root / "output/powerbi/tables/Customer.tmdl").read_text())
            pages = list((root / "output/docs/entities/040-consumer").rglob("customer-4000.md"))
            self.assertEqual(len(pages), 1)
            self.assertIn("SourceSystem", pages[0].read_text())
            self.assertNotEqual(snapshot(root / "output/docs"), baseline["docs"])
            self.assertNotEqual(snapshot(root / "output/powerbi"), baseline["powerbi"])
            self.assertFalse((root / "output/powerbi/powerbi-tabular").exists())
