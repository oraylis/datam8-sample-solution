"""Rules are literal model expressions; only monitoring table placeholders bind."""

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from datam8.errors import Datam8ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generate/databricks-lake/__modules"))
from quality_payloads import bind_monitoring_sql, native_check, notebook_quality, quality_ddl, sql_python_literal  # noqa: E402


def entity(quality):
    return SimpleNamespace(id=77, quality=SimpleNamespace(checks=quality["checks"], model_dump=lambda **_: quality))


class QualityGenerationTests(unittest.TestCase):
    def test_expressions_are_byte_for_byte_unchanged(self):
        for expression in [
            "Amount >= 0",
            "COALESCE(Amount >= 0, FALSE)",
            "  Amount >= 0\n-- keep this comment\n",
            "TIMESTAMPDIFF(MICROSECOND, Updated, CURRENT_TIMESTAMP) <= 1",
            '"Customer Key" IS NOT NULL',
            "Id IS NULL OR COUNT(*) OVER (PARTITION BY Id, Tenant) = 1",
            "custom_rule(Id, ARRAY(1, 2)) AND EXISTS(SELECT 1 FROM some_table)",
            "NOT VALID SQL (",
            "1",
            "",  # Core validates nonblank fields, not native_check.
        ]:
            with self.subTest(expression=expression):
                native = native_check({"id": "check", "execution": "enforcement", "expression": expression})
                self.assertEqual(
                    native,
                    {
                        "name": "check",
                        "criticality": "error",
                        "check": {"function": "sql_expression", "arguments": {"expression": expression}},
                    },
                )

    def test_description_and_severity_are_the_only_optional_native_settings(self):
        rule = {
            "id": "warn",
            "execution": "monitoring",
            "severity": "warning",
            "expression": "1 = 1",
            "description": "Explain failure",
        }
        native = native_check(rule)
        self.assertEqual(native["criticality"], "warn")
        self.assertEqual(native["check"]["arguments"]["msg"], rule["description"])
        self.assertNotIn("user_metadata", native)

    def test_notebook_metadata_has_native_rules_and_no_intermediate_assets(self):
        value = json.loads((ROOT / "tests/fixtures/quality/QualityProbe.json").read_text())["quality"]
        before = copy.deepcopy(value)
        spec = notebook_quality(entity(value), "core.Example")
        self.assertEqual(spec, notebook_quality(entity(value), "core.Example"))
        self.assertEqual(len(spec["monitoring_aggregates"]), 3)
        native = eval(spec["enforcement_checks_literal"], {"__builtins__": {}})
        self.assertEqual(
            [r["expression"] for r in value["checks"][:3]], [r["check"]["arguments"]["expression"] for r in native]
        )
        self.assertEqual(value, before)
        for removed in ["compiled", "files", "expression_groups", "monitoring_groups"]:
            self.assertNotIn(removed, spec)
        self.assertIsNone(notebook_quality(SimpleNamespace(quality=None), "core.X"))
        self.assertIsNone(notebook_quality(entity({"checks": []}), "core.X"))

    def test_query_binding_preserves_all_other_sql(self):
        sql = (
            "WITH x AS (SELECT * FROM {references.allowed})\n"
            'SELECT TIMESTAMPDIFF(MICROSECOND, MAX("Updated"), CURRENT_TIMESTAMP) '
            "FROM {target} t LEFT JOIN x ON t.Id=x.Id"
        )
        bound, refs = bind_monitoring_sql(sql, {"allowed": {"entityId": 1}})
        self.assertEqual(
            bound,
            sql.replace("{references.allowed}", "IDENTIFIER(:dm8_ref_allowed)").replace(
                "{target}", "IDENTIFIER(:dm8_target)"
            ),
        )
        self.assertEqual(refs, ["allowed"])
        self.assertEqual(bind_monitoring_sql("NOT VALID SQL (", {}), ("NOT VALID SQL (", []))
        self.assertEqual(
            bind_monitoring_sql("SELECT * FROM physical.table; nonsense", {})[0],
            "SELECT * FROM physical.table; nonsense",
        )

    def test_literals_identifiers_escapes_and_comments_are_not_bindings(self):
        for literal in [
            "'{target}'",
            "'it''s {references.unknown}'",
            r"'it\'s {target}'",
            '"{target}"',
            "`{target}`",
            "'''{references.unknown}'''",
            '"""{target}"""',
            "-- {references.unknown}\n",
            "-- {target}\r",
            "/* {target} /* {references.unknown} */ still {target} */",
        ]:
            with self.subTest(literal=literal):
                sql = literal + " FROM {target} -- {references.unknown}"
                self.assertEqual(
                    bind_monitoring_sql(sql, {}),
                    (literal + " FROM IDENTIFIER(:dm8_target) -- {references.unknown}", []),
                )

    def test_raw_strings_and_backtick_identifiers_do_not_escape_closing_quotes(self):
        for token in ["r'{references.unknown}\\'", 'R"{target}\\"', "`literal{target}\\`"]:
            sql = "SELECT " + token + " FROM {target}"
            self.assertEqual(bind_monitoring_sql(sql, {}), ("SELECT " + token + " FROM IDENTIFIER(:dm8_target)", []))

    def test_reference_usage_and_errors_come_only_from_actual_placeholders(self):
        sql = "SELECT * FROM {references.z} JOIN {references.a} ON TRUE JOIN {references.z} ON TRUE"
        self.assertEqual(bind_monitoring_sql(sql, {"a": {}, "z": {}, "unused": {}})[1], ["a", "z"])
        with self.assertRaisesRegex(ValueError, "Unknown quality reference alias: unknown"):
            bind_monitoring_sql("SELECT * FROM {references.unknown}", {})
        with self.assertRaises(Datam8ValidationError) as caught:
            notebook_quality(
                entity(
                    {
                        "checks": [
                            {
                                "id": "bad",
                                "execution": "monitoring",
                                "expression": "TRUE",
                                "sql": "SELECT * FROM {references.unknown}",
                            }
                        ]
                    }
                ),
                "core.X",
            )
        self.assertEqual(
            caught.exception.details, {"entityId": 77, "checkId": "bad", "field": "quality.checks.bad.sql"}
        )

    def test_fixture_null_semantics_are_explicit_in_the_model(self):
        checks = json.loads((ROOT / "tests/fixtures/quality/QualityProbe.json").read_text())["quality"]["checks"]
        for check in checks:
            if check["id"] in ["amount_range", "updated_fresh", "row_count", "email_completeness"]:
                self.assertTrue(check["expression"].startswith("COALESCE("))
                self.assertEqual(native_check(check)["check"]["arguments"]["expression"], check["expression"])

    def test_ddl_is_nullable_and_monitoring_has_only_metrics(self):
        ddl = eval(
            quality_ddl([{"name": "Identity", "delta_type": "BIGINT"}], "core", "Example")["quarantine_sql"],
            {"__builtins__": {}},
        )
        for constraint in ["NOT NULL", "IDENTITY", "PRIMARY KEY"]:
            self.assertNotIn(constraint, ddl)
        self.assertNotIn("quarantine_sql", quality_ddl([], "core", "X", enforcement=False))
        text = 'SELECT """quoted""", \\path\nFROM `a``b`'
        self.assertEqual(eval(sql_python_literal(text), {"__builtins__": {}}), text)
