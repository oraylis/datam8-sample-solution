import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml
from sqlglot.errors import SqlglotError
from datam8.errors import Datam8ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generate/databricks-lake/__modules"))
from quality_payloads import (  # noqa: E402
    compile_sql,
    native_check,
    notebook_quality,
    quality_files,
    quality_ddl,
    quality_spec,
    sql_python_literal,
)


def entity(quality):
    return SimpleNamespace(id=77, quality=SimpleNamespace(checks=quality["checks"], model_dump=lambda **_: quality))


class QualityGenerationTests(unittest.TestCase):
    def test_fixed_sql_rules_generate_native_dqx_and_explicit_queries(self):
        quality = json.loads((ROOT / "tests/fixtures/quality/QualityProbe.json").read_text())["quality"]
        before = copy.deepcopy(quality)
        files = quality_files(entity(quality))
        self.assertEqual(files, quality_files(entity(quality)))
        native = yaml.safe_load(files[Path("quality/77/enforcement.yaml")])
        self.assertTrue(all(c["check"]["function"] == "sql_expression" for c in native))
        self.assertEqual(native[0]["check"]["arguments"]["expression"], "COALESCE((NOT Id IS NULL), FALSE)")
        self.assertEqual(native[0]["user_metadata"]["datam8_check_id"], "id_required")
        self.assertEqual(native[2]["criticality"], "warn")
        spec = notebook_quality(entity(quality))
        self.assertEqual(len(spec["monitoring_groups"]), 3)
        self.assertEqual(quality, before)
        self.assertEqual(quality_files(SimpleNamespace(id=77, quality=None)), {})

    def test_uniqueness_is_a_window_expression_without_new_schema_fields(self):
        expression = "Id IS NULL OR COUNT(*) OVER (PARTITION BY Id, Tenant) = 1"
        check = {"id": "unique", "execution": "enforcement", "expression": expression}
        native = native_check(check)
        self.assertIn(expression, native["check"]["arguments"]["expression"])
        self.assertEqual(native["check"]["function"], "sql_expression")

    def test_placeholders_are_bound_relations_not_text_replacements(self):
        sql = (
            "SELECT COUNT(*) AS checked_rows, "
            "MAX(CASE WHEN Email = '{target}' THEN 1 ELSE 0 END) AS measured_value FROM {target}"
        )
        result = compile_sql(sql, query=True)
        self.assertIn("'{target}'", result["text"])
        self.assertIn("IDENTIFIER(:dm8_target)", result["text"])
        result = compile_sql(
            "WITH refs AS (SELECT DISTINCT Id FROM {references.allowed}) "
            "SELECT COUNT(*) AS checked_rows, COUNT(t.Id) AS measured_value "
            "FROM {target} t LEFT JOIN refs r ON t.Id = r.Id",
            query=True,
            references={"allowed": {"entityId": 1}},
        )
        self.assertEqual(result["references"], ["allowed"])
        self.assertIn("IDENTIFIER(:dm8_ref_allowed)", result["text"])

    def test_clock_and_time_argument_order_are_explicit(self):
        result = compile_sql(
            "SELECT COUNT(*) AS checked_rows, "
            "TIMESTAMPDIFF(MICROSECOND, MAX(Updated), CURRENT_TIMESTAMP) / 1000000.0 "
            "AS measured_value FROM {target}",
            query=True,
        )
        self.assertIn("TIMESTAMPDIFF(MICROSECOND, MAX(Updated), :evaluated_at)", result["text"])
        self.assertIn("__dm8_dq_evaluated_at", compile_sql("Updated <= CURRENT_TIMESTAMP")["text"])
        self.assertTrue(result["uses_clock"])
        self.assertEqual(compile_sql('"Customer Key" IS NOT NULL')["text"], "NOT `Customer Key` IS NULL")

    def test_unsupported_sql_is_rejected_explicitly(self):
        for expression in [
            "RAND() > 0",
            "custom_rule(Id)",
            "COUNT(*) > 0",
            "MAX(Id) OVER (PARTITION BY Id) > 0",
            "COUNT(*) OVER (PARTITION BY Id ORDER BY Updated) = 1",
            "Id > 1; SELECT 1",
            "EXISTS(SELECT 1 FROM physical_table)",
            "__dm8_dq_evaluated_at IS NULL",
        ]:
            with self.subTest(expression=expression), self.assertRaises((ValueError, SqlglotError)):
                compile_sql(expression)
        for sql in [
            "DELETE FROM {target}",
            "SELECT COUNT(*) AS checked_rows, 1 AS measured_value FROM physical_table",
            "SELECT COUNT(*) AS checked_rows, 1 AS measured_value FROM {references.unknown}",
            "SELECT 1 AS checked_rows, 2 AS measured_value, 3 AS extra",
            "WITH RECURSIVE x AS (SELECT 1) SELECT 1 AS checked_rows, 1 AS measured_value FROM x",
        ]:
            with self.subTest(sql=sql), self.assertRaises((ValueError, SqlglotError)):
                compile_sql(sql, query=True)

    def test_target_errors_identify_entity_check_and_field(self):
        with self.assertRaises(Datam8ValidationError) as caught:
            quality_spec(entity({"checks": [{"id": "bad", "execution": "enforcement", "expression": "RAND() > 0"}]}))
        self.assertEqual(caught.exception.details["entityId"], 77)
        self.assertEqual(caught.exception.details["checkId"], "bad")
        self.assertEqual(caught.exception.details["field"], "quality.checks.bad.expression")

    def test_ddl_is_nullable_and_literals_preserve_sql(self):
        ddl = eval(
            quality_ddl([{"name": "Identity", "delta_type": "BIGINT"}], "core", "Example")["quarantine_sql"],
            {"__builtins__": {}},
        )
        for constraint in ["NOT NULL", "IDENTITY", "PRIMARY KEY"]:
            self.assertNotIn(constraint, ddl)
        text = 'SELECT """quoted""", \\path\nFROM `a``b`'
        self.assertEqual(eval(sql_python_literal(text), {"__builtins__": {}}), text)
