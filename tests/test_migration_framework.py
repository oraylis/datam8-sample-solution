"""Local parser checks complement, but do not replace, the real Spark suite."""

import ast
import hashlib
from functools import lru_cache
from pathlib import Path
import re
import unittest
from typing import Any

from jinja2 import Environment

SOURCE = Path(__file__).resolve().parents[1] / "Output/databricks-lake/utils/MigrationFramework.py"
module = ast.parse(SOURCE.read_text(encoding="utf-8"))
selected = [
    node
    for node in module.body
    if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    and node.name in {"_MigrationDDL", "_MigrationCatalog", "_TableMigration", "_migration_type", "_mi", "_ml"}
]
namespace = {"_migration_re": re, "_migration_cache": lru_cache}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
DDL = namespace["_MigrationDDL"]


class MigrationDdlTests(unittest.TestCase):
    def test_generated_sql_survives_jinja_python_and_spark_escaping(self):
        root = SOURCE.parents[3]
        helper = root / "Generate/databricks-lake/__modules/payload_helpers.py"
        function = next(
            node
            for node in ast.parse(helper.read_text(encoding="utf-8")).body
            if isinstance(node, ast.FunctionDef) and node.name == "build_create_table_sql"
        )
        scope = {"Any": Any, "hashlib": hashlib, "re": re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(helper), "exec"), scope)
        comment = 'Table\'s \\path, äöü, """quoted"""\nnext line'
        sql = scope["build_create_table_sql"](
            zone="stage",
            full_table_name="sample",
            columns=[
                {
                    "name": "Name",
                    "delta_type": "STRING",
                    "delta_nullable": True,
                    "delta_comment": comment,
                }
            ],
            partitions=[],
            table_comment=comment,
            table_properties={"custom": comment},
        )
        for template in ("ddl_notebook.py.jinja2", "ddl_notebook_raw.py.jinja2"):
            text = (root / "Generate/databricks-lake" / template).read_text(encoding="utf-8")
            line = next(line for line in text.splitlines() if line.startswith("create_sql ="))
            rendered = Environment().from_string(line).render(data={"create_sql": sql})
            output = {"catalog_name": "sample_dev"}
            exec(compile(rendered, template, "exec"), output)
            self.assertEqual(output["create_sql"], sql.replace("{catalog_name}", "sample_dev"))
            target = DDL.parse(output["create_sql"])
            self.assertEqual(target["comment"], comment)
            self.assertEqual(target["columns"][0]["comment"], comment)
            self.assertEqual(target["properties"]["custom"], comment)

    def test_cleanup_retains_replaced_candidate(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.created = {"candidate": "observed-registration"}
        migration.state = lambda name: {"id": "replacement-registration"}
        executed = []
        migration.execute_sql = lambda *args: executed.append(args)
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            migration.discard("candidate", "DROP_CANDIDATE")
        self.assertEqual(executed, [])
        self.assertEqual(migration.created, {"candidate": "observed-registration"})

    def test_nested_and_top_level_alias_conflicts_have_same_policy(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.result = {"reasons": []}
        for path in ([], ["payload"]):
            prefix = "payload." if path else ""
            migration.refactors = [{"name": prefix + "b", "refactorNames": [prefix + "a"]}]
            migration.match_columns(["a", "b"], ["b"], path)
            self.assertEqual(migration.result["reasons"][-1]["code"], "AMBIGUOUS_RENAME")
            self.assertEqual(migration.result["reasons"][-1]["column"], prefix + "b")

    def test_constraint_names_are_part_of_the_target(self):
        key = namespace["_TableMigration"].constraint_key
        self.assertNotEqual(
            key({"name": "old", "body": "PRIMARY KEY(id)"}), key({"name": "target", "body": "PRIMARY KEY(id)"})
        )
        self.assertEqual(
            key({"name": "pk", "body": "PRIMARY KEY(id)"}),
            key({"name": "pk", "body": "PRIMARY KEY(id) NOT ENFORCED DEFERRABLE INITIALLY DEFERRED NORELY"}),
        )

    def test_key_dependencies_exclude_sql_keywords(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.incoming = [{"referenced_constraint": "pk"}]
        constraint = {"name": "pk", "body": "PRIMARY KEY (id) RELY"}
        self.assertEqual(
            migration.constraint_steps([constraint], [constraint], "t", ["key", "primary"], protect=True), []
        )
        self.assertIsNone(migration.constraint_steps([constraint], [constraint], "t", ["id"], protect=True))

    def test_parent_and_child_rename_bind_to_the_same_source(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.result = {"reasons": []}
        migration.refactors = [
            {"name": "Parent", "refactorNames": ["old_parent"]},
            {"name": "Parent.b", "refactorNames": ["old_parent.a"]},
        ]
        self.assertEqual(migration.match_columns(["old_parent"], ["Parent"]), {"Parent": "old_parent"})
        self.assertEqual(migration.match_columns(["a"], ["b"], ["Parent"]), {"b": "a"})
        self.assertEqual(migration.result["reasons"], [])

    def test_feature_upgrade_is_identified_before_mutation(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.target = DDL.parse(
            "CREATE TABLE t (a INT DEFAULT 7) USING DELTA "
            "TBLPROPERTIES ('delta.feature.allowColumnDefaults'='supported')"
        )

        class Datatype:
            def typeName(self):
                return "integer"

        namespace["_parse_datatype_string"] = lambda sql: Datatype()
        migration.sources = {}
        current = {"features": [], "properties": {}}
        self.assertEqual(migration.new_features(current), ["allowColumnDefaults"])
        current["features"] = ["allowColumnDefaults"]
        self.assertEqual(migration.new_features(current), [])

    def test_hidden_rows_are_not_an_empty_source_for_rebuild(self):
        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.before = {"spec": DDL.parse("CREATE TABLE t (a INT) USING DELTA WITH ROW FILTER policy ON(a)")}
        migration.target = DDL.parse("CREATE TABLE t (a INT) USING DELTA")
        migration.result = {"reasons": []}
        migration.nonempty, migration.expressions = False, [("a", "a")]
        migration.incoming, migration.feature_changes = [], []
        self.assertEqual(migration.replacement_strategy(), "ARCHIVE_AND_CREATE_EMPTY")
        self.assertEqual(migration.result["reasons"][0]["code"], "PROTECTED_SOURCE")

    def test_managed_registration_survives_delta_reservoir_replacement(self):
        registration = "8a951e23-3840-4119-a468-20f447e0593e"
        detail = {
            "format": "delta",
            "id": "reservoir-before",
            "location": "abfss://lake@account/sample/__unitystorage/catalogs/catalog/tables/" + registration,
            "description": "literal \\path, Table's comment",
            "properties": {"custom": r"literal\path"},
        }

        class Detail(dict):
            def asDict(self, recursive=False):
                return dict(self)

        class Response:
            def __init__(self, value):
                self.value = value

            def first(self):
                return self.value

            def collect(self):
                return self.value

        class Spark:
            def sql(self, sql):
                if sql.startswith("DESCRIBE DETAIL"):
                    return Response(Detail(detail))
                if sql.startswith("SHOW CREATE"):
                    return Response(
                        ("CREATE TABLE c.s.t (id INT) USING DELTA TBLPROPERTIES ('custom'='literal\\path')",)
                    )
                if sql.startswith("DESCRIBE TABLE"):
                    return Response([{"col_name": "id", "comment": r"Column's \path"}])
                return Response({"version": 3})

        migration = namespace["_TableMigration"].__new__(namespace["_TableMigration"])
        migration.spark, migration.qualified = Spark(), "c.s.t"
        migration.parts = ["c", "s", "t"]
        before = migration.state()
        detail["id"] = "reservoir-after"
        after = migration.state()
        self.assertEqual(before["id"], registration)
        self.assertEqual(after["id"], registration)
        self.assertNotEqual(before["delta_id"], after["delta_id"])
        self.assertEqual(before["spec"]["comment"], detail["description"])
        self.assertEqual(before["spec"]["columns"][0]["comment"], r"Column's \path")
        self.assertEqual(before["spec"]["properties"], detail["properties"])

    def test_candidate_check_constraints_are_deferred(self):
        spec = DDL.parse("CREATE TABLE c.s.t (id INT, CONSTRAINT positive CHECK (id > 0)) USING DELTA")
        self.assertNotIn("CHECK", DDL.render(spec, "c.s.candidate", defer_constraints=True))
        self.assertEqual(spec["constraints"][0]["body"], "CHECK ( id > 0 )")

    def test_candidate_self_reference_binds_to_candidate_registration(self):
        spec = DDL.parse(
            "CREATE TABLE c.s.t (id BIGINT NOT NULL, parent BIGINT, CONSTRAINT pk PRIMARY KEY(id), "
            "CONSTRAINT fk FOREIGN KEY(parent) REFERENCES c.s.t(id)) USING DELTA"
        )
        bound = DDL.bind_reference(spec["constraints"][1]["body"], spec, "`c`.`s`.`candidate`")
        self.assertIn("`candidate`", bound)

    def test_framework_does_not_overwrite_callers_datetime_module(self):
        aliases = [
            alias.asname or alias.name
            for node in module.body
            if isinstance(node, ast.ImportFrom) and node.module == "datetime"
            for alias in node.names
        ]
        self.assertNotIn("datetime", aliases)
        self.assertIn("_MigrationDateTime", aliases)

    def test_runtime_notebook_cells_are_importable(self):
        for path in SOURCE.parent.glob("*.py"):
            cells = re.split(r"(?m)^# COMMAND ----------\s*$", path.read_text(encoding="utf-8"))
            for index, cell in enumerate(cells):
                lines = [
                    line
                    for line in cell.splitlines()
                    if line.strip() and line != "# Databricks notebook source" and not line.startswith("# DBTITLE")
                ]
                if any(line.startswith("# MAGIC") for line in lines):
                    self.assertTrue(
                        all(line.startswith("# MAGIC") for line in lines), f"Mixed magic cell: {path}:{index}"
                    )
                else:
                    compile(cell, f"{path}:cell{index}", "exec")

    def test_nested_types_and_decimal_commas_are_not_column_separators(self):
        spec = DDL.parse(
            "CREATE TABLE `c`.`s`.`t` (`Payload` STRUCT<`a`:DECIMAL(12,3), `b`:ARRAY<STRUCT<x:INT,y:STRING>>>, `Value` INT) USING DELTA"  # noqa: E501
        )
        self.assertEqual([c["name"] for c in spec["columns"]], ["Payload", "Value"])

    def test_escaped_identifiers_literals_and_property_commas(self):
        spec = DDL.parse(
            "CREATE TABLE `t``x` (`a``b` STRING COMMENT 'Customer''s, name') USING DELTA COMMENT 'Title''s' TBLPROPERTIES ('custom'='a,b=c')"  # noqa: E501
        )
        self.assertEqual(spec["name"], ["t`x"])
        self.assertEqual(spec["columns"][0]["name"], "a`b")
        self.assertEqual(spec["columns"][0]["comment"], "Customer's, name")
        self.assertEqual(spec["properties"], {"custom": "a,b=c"})

    def test_spark_literals_preserve_quotes_backslashes_and_controls(self):
        literal = namespace["_ml"]
        for value in ("O'Reilly", "slash\\quote'", "line\nnext\ttab", "äöü ☃"):
            self.assertEqual(DDL.value(literal(value)), value)
        self.assertIn("\\'", literal("O'Reilly"))

    def test_identity_default_nullability_and_constraints(self):
        spec = DDL.parse(
            "CREATE TABLE t (id BIGINT GENERATED BY DEFAULT AS IDENTITY (START WITH 3 INCREMENT BY 7) NOT NULL, value INT DEFAULT (1 + 2), CONSTRAINT pk PRIMARY KEY(id) RELY, CONSTRAINT positive CHECK (value < 10), other STRING) USING DELTA"  # noqa: E501
        )
        self.assertEqual(len(spec["columns"]), 3)
        self.assertEqual(len(spec["constraints"]), 2)
        self.assertFalse(spec["columns"][0]["nullable"])
        self.assertIn("BY DEFAULT", spec["columns"][0]["identity"])
        self.assertEqual(spec["columns"][1]["default"], "( 1 + 2 )")

    def test_render_preserves_complete_definition(self):
        spec = DDL.parse(
            "CREATE TABLE t (id INT NOT NULL, value STRING COMMENT 'a,b') USING DELTA CLUSTER BY(id) COMMENT 'sample' TBLPROPERTIES ('delta.columnMapping.mode'='name')"  # noqa: E501
        )
        rendered = DDL.parse(DDL.render(spec, "`t`"))
        self.assertEqual(spec, rendered)

    def test_check_properties_are_constraints(self):
        spec = DDL.parse("CREATE TABLE t (id INT) USING DELTA TBLPROPERTIES ('delta.constraints.valid'='id > 0')")
        self.assertEqual(spec["properties"], {})
        self.assertEqual(spec["constraints"], [{"name": "valid", "body": "CHECK (id > 0)"}])

    def test_sql_operators_remain_single_tokens(self):
        for operator in (">=", "<=", "<>", "!=", "<=>", "==", "||", "->", "=>"):
            self.assertEqual(DDL.tokens("a " + operator + " b"), ["a", operator, "b"])
        sql = "CREATE TABLE t (id INT, CONSTRAINT valid CHECK(id >= 0 AND id <= 10)) USING DELTA"
        self.assertEqual(DDL.parse(DDL.render(DDL.parse(sql), "t")), DDL.parse(sql))

    def test_row_filter_does_not_consume_properties(self):
        spec = DDL.parse(
            "CREATE TABLE t (id INT) USING DELTA WITH ROW FILTER c.s.f ON(id) TBLPROPERTIES ('custom'='x')"
        )
        self.assertEqual(spec["properties"], {"custom": "x"})
        self.assertEqual(DDL.canonical(spec["row_filter"]), "c . s . f on ( id )")

    def test_partitioning_and_clustering_are_distinct(self):
        spec = DDL.parse("CREATE TABLE t (id INT) USING DELTA PARTITIONED BY(id)")
        self.assertEqual(spec["partitions"], ["id"])
        self.assertEqual(spec["clustering"], [])

    def test_collation_precedes_not_null_in_rendered_sql(self):
        spec = DDL.parse("CREATE TABLE t (name STRING COLLATE UTF8_BINARY NOT NULL) USING DELTA")
        statement = DDL.render(spec, "t")
        self.assertLess(statement.index("COLLATE"), statement.index("NOT NULL"))

    def test_generated_expression_can_reference_column_named_identity(self):
        spec = DDL.parse("CREATE TABLE t (identity INT, computed INT GENERATED ALWAYS AS (identity + 1)) USING DELTA")
        self.assertIsNone(spec["columns"][1]["identity"])
        self.assertIsNotNone(spec["columns"][1]["generated"])

    def test_identity_defaults_and_negative_sequences(self):
        key = namespace["_TableMigration"].identity_key
        self.assertEqual(
            key("GENERATED ALWAYS AS IDENTITY"),
            key("GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)"),
        )
        self.assertNotEqual(
            key("GENERATED ALWAYS AS IDENTITY (START WITH -5 INCREMENT BY -2)"),
            key("GENERATED ALWAYS AS IDENTITY (START WITH -6 INCREMENT BY -2)"),
        )

    def test_invalid_input_is_not_silently_accepted(self):
        for sql in (
            "DROP TABLE t",
            "CREATE TABLE t (a INT); DROP TABLE x",
            "CREATE TABLE t (a INT, A STRING)",
            "CREATE TABLE t (a INT) USING PARQUET",
            "CREATE TABLE t (a INT) UNSUPPORTED OPTION",
        ):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                DDL.parse(sql)


if __name__ == "__main__":
    unittest.main()
