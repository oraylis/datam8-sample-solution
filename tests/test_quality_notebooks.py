"""Generate real quality notebooks and check their reviewable execution contracts."""

import ast
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
from generation_checks import check_notebook_markdown_cells  # noqa: E402
from bundle_assets import required_assets  # noqa: E402


class QualityNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dm8-readable-quality-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / "solution"
        excluded = {".git", ".venv", "output", "__pycache__", ".ruff_cache", ".databricks"}
        shutil.copytree(ROOT, cls.root, ignore=lambda directory, names: [n for n in names if n.casefold() in excluded])
        original = json.loads((ROOT / "tests/fixtures/quality/QualityProbe.json").read_text())
        for number, name, mode in [
            (9001, "QualityProbe", "mixed"),
            (9005, "QualityMonitorProbe", "monitor"),
            (9006, "QualityRowsProbe", "rows"),
            (9007, "QualitySummaryProbe", "summary"),
            (9008, "QualityEnforceProbe", "enforcement"),
            (9009, "QualityNoneProbe", "none"),
            (9010, "QualityNoDmlProbe", "no_dml"),
        ]:
            entity = json.loads(json.dumps(original))
            entity.update(id=number, name=name)
            checks = entity["quality"]["checks"]
            if mode in ("monitor", "rows"):
                for check in checks:
                    check["execution"] = "monitoring"
            if mode == "rows":
                entity["quality"]["checks"] = checks[:3]
            elif mode == "summary":
                entity["quality"]["checks"] = checks[3:]
            elif mode == "enforcement":
                entity["quality"]["checks"] = checks[:3]
            elif mode == "none":
                entity["quality"]["checks"] = []
            elif mode == "no_dml":
                entity["transformations"] = []
            path = cls.root / "model/020-Core/MasterData/Customer"
            (path / f"{name}.json").write_text(json.dumps(entity))
            (path / name).mkdir(exist_ok=True)
            shutil.copy2(ROOT / "tests/fixtures/quality/QualityProbe.py", path / "QualityProbe.py")
        native = json.loads((ROOT / "tests/fixtures/quality/QualityNativeProbe.json").read_text())
        reference = json.loads((ROOT / "tests/fixtures/quality/QualityReferenceProbe.json").read_text())
        (path / "QualityReferenceProbe.json").write_text(json.dumps(reference))
        shutil.copy2(ROOT / "tests/fixtures/quality/QualityReferenceProbe.py", path / "QualityReferenceProbe.py")
        (path / "QualityNativeProbe.json").write_text(json.dumps(native))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "datam8",
                "generate",
                "databricks",
                "-s",
                str(cls.root / "ORAYLISDatabricksSample.dm8s"),
                "--clean-output",
            ],
            cwd=cls.root,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.output = cls.root / "output/databricks"

    def notebook(self, phase, name="QualityProbe"):
        return (self.output / f"notebooks/020-Core/{phase}/MasterData/Customer/{name}.py").read_text()

    def test_fixture_function_is_present_in_generated_notebooks(self):
        functions = list(
            (self.output / "notebooks/020-Core/dml/MasterData/Customer").glob("Quality*_functions/QualityProbe.py")
        )
        self.assertGreater(len(functions), 0)
        for function in functions:
            self.assertIn("business_function = spark.table", function.read_text())

    def test_generated_cells_and_assets_are_complete(self):
        check_notebook_markdown_cells(self.output)
        for file in self.output.rglob("*.py"):
            ast.parse(file.read_text(), filename=str(file))
        required_assets(self.root / "deployment/databricks", self.output)

    def test_ddl_contains_explicit_nullable_quality_sql(self):
        code = self.notebook("ddl")
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS `{catalog_name}`.`core`.`MasterData_Customer_QualityProbe_quarantine`", code
        )
        self.assertIn("`__dm8_dq_audit` STRING", code)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS", code)
        self.assertIn("quality.dqx_metrics (", code)
        self.assertNotIn("quality_runtime.ensure_tables(", code)
        assignment = next(
            n
            for n in ast.walk(ast.parse(code))
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "quarantine_sql" for t in n.targets)
        )
        literal = assignment.value.func.value.value
        self.assertNotIn("NOT NULL", literal)
        self.assertNotIn("IDENTITY", literal)
        self.assertNotIn("PRIMARY KEY", literal)
        self.assertIn("`__InsertTimestampUTC` TIMESTAMP", literal)

    def test_enforcement_order_split_and_gate_are_visible(self):
        code = self.notebook("dml")
        self.assertIn("quality_engine.apply_checks_by_metadata", code)
        self.assertIn("where(~quality_has_errors).select(*quality_input_columns)", code)
        self.assertIn("failure_rate_pct > max_failure_rate_pct", code)
        self.assertIn("SKIPPED_EMPTY_QUALITY_OUTPUT", code)
        self.assertLess(code.index("quality_runtime.write_quarantine("), code.index("final_write_df.write"))
        self.assertLess(code.index("final_write_df.write"), code.rindex("quality_runtime.write_metrics("))
        self.assertLess(
            code.rindex("quality_runtime.write_metrics("), code.rindex("raise quality_runtime.QualityThresholdExceeded")
        )
        for removed in ["enforce(", "finish_enforcement(", "monitor(", "ensure_tables("]:
            self.assertNotIn("quality_runtime." + removed, code)

    def test_monitoring_contains_sql_dqx_statuses_and_no_target_write(self):
        code = self.notebook("quality")
        for part in [
            "COUNT(Email) * 1.0 / NULLIF(COUNT(*), 0)",
            "TIMESTAMPDIFF(MICROSECOND, MAX(Updated), :evaluated_at)",
            "IDENTIFIER(:dm8_target)",
            "quality_engine.apply_checks_by_metadata",
            '"NO_DATA"',
            "display(monitoring_metric_df.select",
        ]:
            self.assertIn(part, code)
        for part in ["quality_runtime.monitor(", ".saveAsTable(", "QualityThresholdExceeded", "write_quarantine("]:
            self.assertNotIn(part, code)

    def test_only_configured_groups_are_rendered(self):
        self.assertIn("monitoring_checked_df", self.notebook("quality", "QualityMonitorProbe"))
        self.assertIn("monitoring_sql =", self.notebook("quality", "QualityMonitorProbe"))
        self.assertNotIn("monitoring_sql =", self.notebook("quality", "QualityRowsProbe"))
        self.assertNotIn("monitoring_input_df = monitoring_df", self.notebook("quality", "QualitySummaryProbe"))
        for name in ["QualityEnforceProbe", "QualityNoneProbe"]:
            self.assertFalse((self.output / f"notebooks/020-Core/quality/MasterData/Customer/{name}.py").exists())
        self.assertNotIn("quality_runtime", self.notebook("dml", "QualityNoneProbe"))
        self.assertNotIn("enforcement_metrics", self.notebook("dml", "QualityNoDmlProbe"))

    def test_monitoring_only_has_no_dqx_in_load_notebook_or_task(self):
        for name in ["QualityMonitorProbe", "QualityRowsProbe", "QualitySummaryProbe"]:
            code = self.notebook("dml", name)
            for text in ["DQEngine", "QualityFramework", "quality_reference_dfs", "enforcement_metrics"]:
                self.assertNotIn(text, code)
            self.assertIn('dbutils.notebook.exit("SKIPPED_EMPTY_QUALITY_OUTPUT")', code)
        jobs = yaml.safe_load((self.output / "jobs/load_sales_daily.yml").read_text())["resources"]["jobs"]
        tasks = [t for job in jobs.values() for t in job["tasks"]]
        matching = [
            t for t in tasks if t.get("notebook_task", {}).get("notebook_path", "").endswith("/QualityMonitorProbe")
        ]
        self.assertEqual(len(matching), 2)
        for task in matching:
            if "/dml/" in task["notebook_task"]["notebook_path"]:
                self.assertNotIn("libraries", task)
            else:
                self.assertNotIn("run_if", task)
                self.assertIn("libraries", task)

    def test_gate_monitoring_is_attempt_guarded_and_native_references_are_resolved(self):
        code = self.notebook("quality")
        self.assertLess(code.index("quality_upstream_result"), code.index("DQEngineCore"))
        self.assertIn('quality_gate_signal.get("attempt")', code)
        self.assertIn('quality_context["attemptId"]', self.notebook("dml"))
        manifest = json.loads((self.output / "quality/9011/manifest.json").read_text())
        self.assertEqual(manifest["references"]["enforcement"], {})
        self.assertIn("MasterData_Customer_QualityReferenceProbe", manifest["references"]["monitoring"]["permitted"])
        native = yaml.safe_load((self.output / "quality/9011/enforcement.yaml").read_text())
        self.assertTrue(all(check["check"]["function"] == "sql_expression" for check in native))
        self.assertEqual(native[0]["user_metadata"]["datam8_check_id"], "native_required")
        self.assertIn("PARTITION BY Id", native[2]["check"]["arguments"]["expression"])
        jobs = yaml.safe_load((self.output / "jobs/load_sales_daily.yml").read_text())["resources"]["jobs"]
        tasks = [t for job in jobs.values() for t in job["tasks"]]
        monitor = next(t for t in tasks if t["task_key"] == "quality_monitor_9011")
        self.assertEqual(monitor["run_if"], "ALL_DONE")
        self.assertIn("{{tasks.", monitor["notebook_task"]["base_parameters"]["quality_upstream_result"])
        self.assertEqual(monitor["libraries"], [{"pypi": {"package": "databricks-labs-dqx==0.16.0"}}])
        self.assertTrue(
            any(
                "QualityReferenceProbe" in dependency["task_key"]
                or dependency["task_key"].endswith("qualityreferenceprobe")
                for dependency in monitor["depends_on"]
            )
        )

    def test_native_rule_changes_and_last_rule_deletion_remove_stale_assets(self):
        with tempfile.TemporaryDirectory(prefix="dm8-native-crud-") as temporary:
            root = Path(temporary) / "solution"
            shutil.copytree(self.root, root, ignore=shutil.ignore_patterns("output", "__pycache__"))
            entity_path = root / "model/020-Core/MasterData/Customer/QualityNativeProbe.json"
            entity = json.loads(entity_path.read_text())
            for mode in ("monitoring", "enforcement", "deleted"):
                if mode == "deleted":
                    entity["quality"]["checks"] = []
                else:
                    if mode == "enforcement":
                        entity["quality"]["checks"] = [c for c in entity["quality"]["checks"] if "sql" not in c]
                    for check in entity["quality"]["checks"]:
                        check["execution"] = mode
                entity_path.write_text(json.dumps(entity))
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "datam8",
                        "generate",
                        "databricks",
                        "-s",
                        str(root / "ORAYLISDatabricksSample.dm8s"),
                        "--clean-output",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = root / "output/databricks"
                dml = (output / "notebooks/020-Core/dml/MasterData/Customer/QualityNativeProbe.py").read_text()
                monitor = output / "notebooks/020-Core/quality/MasterData/Customer/QualityNativeProbe.py"
                self.assertEqual("DQEngineCore" in dml, mode == "enforcement")
                self.assertEqual(monitor.exists(), mode == "monitoring")
                self.assertEqual((output / "quality/9011/manifest.json").exists(), mode != "deleted")
