import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generate/databricks-lake/__modules"))
from quality_payloads import native_check, quality_files  # noqa: E402


class QualityGenerationTests(unittest.TestCase):
    def test_native_rules_and_stable_manifest(self):
        checks = [
            {"id": "required", "type": "not_null", "attribute": "A b", "execution": "enforcement", "severity": "error"},
            {
                "id": "range",
                "type": "range",
                "attribute": "Amount",
                "execution": "enforcement",
                "severity": "warning",
                "parameters": {"max": 100},
            },
            {
                "id": "sql",
                "type": "sql_expression",
                "execution": "monitoring",
                "severity": "error",
                "parameters": {"expression": "Amount >= 0"},
            },
            {
                "id": "complete",
                "type": "completeness",
                "attribute": "Email",
                "execution": "monitoring",
                "severity": "warning",
                "parameters": {"minCompleteness": 0.95},
            },
            {
                "id": "fresh",
                "type": "freshness",
                "attribute": "Updated",
                "execution": "monitoring",
                "severity": "error",
                "parameters": {"maxAgeSeconds": 60},
            },
            {
                "id": "count",
                "type": "row_count",
                "execution": "monitoring",
                "severity": "error",
                "parameters": {"minCount": 0, "maxCount": 50},
            },
        ]
        entity = SimpleNamespace(
            id=77, quality=SimpleNamespace(checks=checks, model_dump=lambda **_: {"checks": checks})
        )
        files = quality_files(entity)
        self.assertEqual(files, quality_files(entity))
        self.assertEqual(len(files), 4)
        manifest = json.loads(files[Path("quality/77/manifest.json")])
        self.assertEqual(len(manifest["ruleSetHash"]), 64)
        enforcement = yaml.safe_load(files[Path("quality/77/enforcement.yaml")])
        self.assertEqual(enforcement[0]["check"]["arguments"]["column"], "`A b`")
        self.assertEqual(enforcement[1]["criticality"], "warn")
        summary = yaml.safe_load(files[Path("quality/77/monitoring_summary.yaml")])
        self.assertEqual(len(summary), 3)
        self.assertIn("COALESCE", native_check(checks[2])["check"]["arguments"]["expression"])
        entity.quality = None
        self.assertEqual(quality_files(entity), {})
