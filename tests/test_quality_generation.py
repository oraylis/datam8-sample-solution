import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml
from datam8.errors import Datam8ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generate/databricks-lake/__modules"))
sys.path.insert(0, str(ROOT / "scripts"))
from quality_payloads import (  # noqa: E402
    native_check,
    notebook_quality,
    quality_files,
    quality_ddl,
    sql_python_literal,
    quality_spec,
)
from convert_quality_definitions import convert_quality  # noqa: E402


def entity(quality):
    return SimpleNamespace(id=77, quality=SimpleNamespace(checks=quality["checks"], model_dump=lambda **_: quality))


class QualityGenerationTests(unittest.TestCase):
    def test_model_definitions_produce_native_checks_and_explicit_sql(self):
        quality = json.loads((ROOT / "tests/fixtures/quality/QualityProbe.json").read_text())["quality"]
        files = quality_files(entity(quality))
        self.assertEqual(files, quality_files(entity(quality)))
        native = yaml.safe_load(files[Path("quality/77/enforcement.yaml")])
        self.assertEqual(native[0]["check"]["function"], "is_not_null")
        self.assertEqual(native[0]["user_metadata"]["datam8_check_id"], "id_required")
        summary = yaml.safe_load(files[Path("quality/77/monitoring_summary.yaml")])
        self.assertEqual(len(summary), 3)
        self.assertTrue(all("datam8" not in c for c in summary))
        spec = notebook_quality(entity(quality))
        self.assertIn("COUNT(`Email`) / NULLIF(COUNT(*), 0)", spec["quality"]["settings"]["inputs"]["summary"]["sql"])
        self.assertNotIn('rule["type"]', (ROOT / "generate/databricks-lake/quality_notebook.py.jinja2").read_text())
        self.assertEqual(quality_files(SimpleNamespace(id=77, quality=None)), {})

    def test_native_passthrough_has_no_function_catalogue_or_mutation(self):
        for function in ["is_unique", "foreign_key", "future_native_function"]:
            definition = {
                "name": "display",
                "criticality": "warn",
                "filter": "Id > 0",
                "check": {"function": function, "arguments": {"any": [None, {"nested": 2}]}},
                "user_metadata": {"owner": "team"},
            }
            original = copy.deepcopy(definition)
            result = native_check({"id": "stable", "definition": definition})
            self.assertEqual(definition, original)
            result["user_metadata"].pop("datam8_check_id")
            self.assertEqual(result, original)

    def test_only_the_selected_target_rejects_another_tools_dialect(self):
        with self.assertRaisesRegex(Datam8ValidationError, "DQX target"):
            quality_spec(
                entity({"checks": [{"id": "other", "execution": "monitoring", "definition": {"assertion": "x"}}]})
            )

    def test_invalid_target_options_have_structured_validation_errors(self):
        for option in [{"user_metadata": 0}, {"datam8": {"input": []}}]:
            with self.subTest(option=option), self.assertRaises(Datam8ValidationError):
                quality_spec(entity({"checks": [{
                    "id": "check", "execution": "monitoring",
                    "definition": {"check": {"function": "is_not_null"}, **option},
                }]}))

    def test_arbitrary_sql_inputs_and_metrics_are_declared_without_check_categories(self):
        quality = {
            "settings": {"inputs": {"custom_total": {"sql": "SELECT SUM(Price) AS amount FROM {target_table}"}}},
            "checks": [
                {
                    "id": "sum_limit",
                    "execution": "monitoring",
                    "definition": {
                        "check": {"function": "sql_expression", "arguments": {"expression": "amount > 50"}},
                        "datam8": {
                            "input": "custom_total",
                            "metrics": {"checked_rows": "1", "measured_value": "amount"},
                        },
                    },
                }
            ],
        }
        spec = notebook_quality(entity(quality))
        self.assertEqual(spec["monitoring_groups"][0]["input"], "custom_total")
        self.assertIn("SUM(Price)", spec["monitoring_groups"][0]["sql_literal"])

    def test_explicit_metadata_conversion_is_idempotent_and_preserves_aggregate_policy(self):
        old = {
            "checks": [
                {
                    "id": "required",
                    "type": "not_null",
                    "execution": "enforcement",
                    "severity": "error",
                    "attribute": "Id",
                },
                {
                    "id": "complete",
                    "type": "completeness",
                    "execution": "monitoring",
                    "severity": "warning",
                    "attribute": "Email",
                    "parameters": {"minCompleteness": 0.95},
                },
                {
                    "id": "fresh",
                    "type": "freshness",
                    "execution": "monitoring",
                    "severity": "error",
                    "attribute": "Updated",
                    "parameters": {"maxAgeSeconds": 300},
                },
                {
                    "id": "count",
                    "type": "row_count",
                    "execution": "monitoring",
                    "severity": "error",
                    "parameters": {"minCount": 1},
                },
            ]
        }
        original = copy.deepcopy(old)
        result = convert_quality(old)
        self.assertEqual(old, original)
        self.assertEqual(convert_quality(result), result)
        self.assertEqual([c["id"] for c in result["checks"]], [c["id"] for c in old["checks"]])
        self.assertTrue(all("type" not in c for c in result["checks"]))
        checks = result["checks"]
        self.assertIn("no_data_when", checks[1]["definition"]["datam8"]["metrics"])
        self.assertNotIn("no_data_when", checks[2]["definition"]["datam8"]["metrics"])
        self.assertIn("BETWEEN 0 AND 300", checks[2]["definition"]["check"]["arguments"]["expression"])
        self.assertIn("COUNT(*)", result["settings"]["inputs"]["summary"]["sql"])

    def test_quality_ddl_is_nullable_and_literals_preserve_sql(self):
        ddl = eval(
            quality_ddl([{"name": "Identity", "delta_type": "BIGINT"}], "core", "Example")["quarantine_sql"],
            {"__builtins__": {}},
        )
        for constraint in ["NOT NULL", "IDENTITY", "PRIMARY KEY"]:
            self.assertNotIn(constraint, ddl)
        text = 'SELECT """quoted""", \\path\nFROM `a``b`'
        self.assertEqual(eval(sql_python_literal(text), {"__builtins__": {}}), text)
