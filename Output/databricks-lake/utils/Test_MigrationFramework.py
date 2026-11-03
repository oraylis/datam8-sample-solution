# Databricks notebook source
# MAGIC %md
# MAGIC # Migration acceptance: real Dev table, restoration after every scenario
# MAGIC No log tables. Run through the Dev bundle's Migration Framework Tests job.

# COMMAND ----------
import datetime

# COMMAND ----------
# MAGIC %run ./MigrationFramework

# COMMAND ----------
# ruff: noqa: F821
# Framework symbols are loaded by the %run cell.
import fnmatch
import json
import uuid
import re
from copy import deepcopy
from pyspark.sql.types import StructField, StructType, _parse_datatype_string
from pyspark.sql import functions as F
import traceback
import math
from collections import Counter

assert hasattr(datetime, "datetime"), "Framework must preserve the datetime module used by Complete_Load"

dbutils.widgets.text("scenarios", "*")
dbutils.widgets.text("cleanup_backups", "[]")
selection = dbutils.widgets.get("scenarios").split(",")
cleanup_backups = json.loads(dbutils.widgets.get("cleanup_backups"))
assert spark.sql("SELECT current_user()").first()[0] == "e2d1a9de-1e86-45bf-91c7-675f7e493425", (
    "Use the configured Dev run principal"
)
assert "7405619058873076" in spark.conf.get("spark.databricks.workspaceUrl"), "Dev workspace only"
test_catalog = "dm8_sample_dev_lake"
catalog = Catalog(test_catalog)
catalog.schema = "stage"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def assert_rows(expected, actual):
    """Independent test oracle; selected sample and fixtures are deliberately small."""

    def freeze(value):
        if isinstance(value, dict):
            return tuple(sorted(((freeze(k), freeze(v)) for k, v in value.items()), key=repr))
        if isinstance(value, (tuple, list)):
            return tuple(freeze(v) for v in value)
        if isinstance(value, float) and math.isnan(value):
            return ("float", "NaN")
        return value

    require(
        Counter(freeze(row) for row in expected.collect()) == Counter(freeze(row) for row in actual.collect()),
        "Full row multiset differs",
    )


def function_fingerprint(function):
    leaf = function.rsplit(".", 1)[-1].replace("`", "")
    rows = spark.sql(
        "SELECT specific_name,created,created_by,routine_definition FROM "
        + _mi(test_catalog)
        + ".information_schema.routines "
        + "WHERE routine_schema='stage' AND routine_name="
        + _ml(leaf)
    ).collect()
    require(len(rows) == 1, "Function identity is not unambiguous")
    return rows[0].asDict()


def context(table_name):
    table = Table(table_name, catalog)
    migration = _TableMigration.__new__(_TableMigration)
    migration.table, migration.spark = table, spark
    migration.parts = [test_catalog, *table_name.split(".")]
    migration.name = ".".join(migration.parts)
    migration.qualified = ".".join(_mi(p) for p in migration.parts)
    return migration


# Select only existing sample tables, never a pipeline object or prior archive.
candidates = []
for leaf in (
    "postgresqlwarehouse_aw_warehouse_warehouse",
    "adventureworks_saleslt_productcategory",
    "oracleprocurement_aw_procurement_supplier",
):
    name = "stage." + leaf
    if not spark.catalog.tableExists(test_catalog + "." + name):
        continue
    c = context(name)
    state = c.state()
    foreign = spark.sql(f"""SELECT 1 FROM {test_catalog}.information_schema.referential_constraints r
        JOIN {test_catalog}.information_schema.table_constraints t
        ON r.unique_constraint_catalog=t.constraint_catalog AND r.unique_constraint_schema=t.constraint_schema
        AND r.unique_constraint_name=t.constraint_name
        WHERE t.table_schema='stage' AND t.table_name={_ml(leaf)} LIMIT 1""").first()
    if foreign or state["spec"]["row_filter"] or any(col["mask"] for col in state["spec"]["columns"]):
        continue
    if spark.table(c.qualified).limit(1).count():
        candidates.append((state["detail"]["sizeInBytes"], name))
require(candidates, "No suitable existing populated Dev sample table")
_, selected_table = min(candidates)
baseline = context(selected_table)
q = baseline.qualified
original = baseline.state()
original_metadata = baseline.catalog_metadata()
original_schema = spark.table(q).schema.jsonValue()
original_ddl = spark.sql("SHOW CREATE TABLE " + q).first()[0]
test_id = uuid.uuid4().hex[:12]
backup = ".".join(_mi(p) for p in baseline.parts[:-1] + [baseline.parts[-1] + "__test_backup_" + test_id])
parked = ".".join(_mi(p) for p in baseline.parts[:-1] + [baseline.parts[-1] + "__test_original_" + test_id])
spark.sql(f"CREATE TABLE {backup} DEEP CLONE {q}").collect()
assert_rows(spark.table(q), spark.table(backup))
report = {
    "table": baseline.name,
    "original_id": original["id"],
    "expected_catalog_id": original["id"],
    "original_delta_id": original["delta_id"],
    "original_version": original["version"],
    "original_location": original["identity_location"],
    "original_create_ddl": original_ddl,
    "original_spark_schema": original_schema,
    "original_detail": original["detail"],
    "original_protocol": {k: original["detail"][k] for k in ("minReaderVersion", "minWriterVersion")},
    "backup": backup,
    "backup_id": baseline.state(backup)["id"],
    "original_metadata": original_metadata,
    "original_spec": original["spec"],
    "tests": [],
}
print("MIGRATION_TEST_BASELINE " + json.dumps(report, default=str))
restored_version = [original["version"]]
owned_registrations = {original["id"]}


def restore_original():
    """Stop the suite if the original identity, data, or metadata cannot return."""
    current = baseline.state() if spark.catalog.tableExists(q) else None
    source = None
    if current is None or current["id"] != original["id"]:
        names = [parked] + [
            ".".join(_mi(p) for p in baseline.parts[:-1] + [r.tableName])
            for r in spark.sql("SHOW TABLES IN " + _mi(test_catalog) + ".stage").collect()
            if r.tableName.startswith(baseline.parts[-1] + "__archive_")
        ]
        for name in names:
            if spark.catalog.tableExists(name) and baseline.state(name)["id"] == original["id"]:
                source = name
                break
        require(source, "Original identity not found; retain backup and stop")
        if current is not None:
            require(current["id"] in owned_registrations, "Unexpected current registration; retain both tables")
            spark.sql("DROP TABLE " + q).collect()
        spark.sql("ALTER TABLE " + source + " RENAME TO " + q).collect()
    current_spec = baseline.state()["spec"]
    old_keys = {_TableMigration.constraint_key(c) for c in original["spec"]["constraints"]}
    for constraint in sorted(
        current_spec["constraints"], key=lambda c: _MigrationDDL.tokens(c["body"])[0].upper() != "FOREIGN"
    ):
        if _TableMigration.constraint_key(constraint) not in old_keys:
            spark.sql(f"ALTER TABLE {q} DROP CONSTRAINT {_mi(constraint['name'])}").collect()
    if current_spec["row_filter"] and not original["spec"]["row_filter"]:
        spark.sql(f"ALTER TABLE {q} DROP ROW FILTER").collect()
    original_masks = {c["name"]: c["mask"] for c in original["spec"]["columns"]}
    for column in current_spec["columns"]:
        if column["mask"] and not original_masks.get(column["name"]):
            spark.sql(f"ALTER TABLE {q} ALTER COLUMN {_mi(column['name'])} DROP MASK").collect()
    if baseline.state()["version"] != restored_version[0]:
        spark.sql(f"RESTORE TABLE {q} TO VERSION AS OF {original['version']}").collect()
    helper = context(selected_table)
    helper.target = original["spec"]
    helper.sources = {c["name"]: c["name"] for c in helper.target["columns"]}
    helper.run_id, helper.steps, helper.result = test_id, [], {"changes": []}
    helper.changed = False
    require(helper.metadata_steps(helper.state()["spec"]), "Cannot restore original metadata with ALTER")
    for step in helper.steps:
        spark.sql(step["sql"]).collect()
    helper.restore_catalog(original_metadata, grants=False)
    helper.metadata = original_metadata
    helper.validate()
    require(helper.validated_state["id"] == original["id"], "Original table identity differs")
    require(
        sorted(helper.validated_state["spec"]["features"]) == sorted(original["spec"]["features"]),
        "Original Delta features differ",
    )
    require(
        all(
            helper.validated_state["detail"][k] == original["detail"][k]
            for k in ("minReaderVersion", "minWriterVersion")
        ),
        "Original Delta protocol differs",
    )
    before_properties = original["detail"]["properties"]
    after_properties = helper.validated_state["detail"]["properties"]
    counter = "delta.columnMapping.maxColumnId"
    require(
        {k: v for k, v in before_properties.items() if k != counter}
        == {k: v for k, v in after_properties.items() if k != counter},
        "Original raw Delta properties differ",
    )
    if before_properties.get(counter) != after_properties.get(counter):
        require(int(after_properties[counter]) >= int(before_properties[counter]), "Column ID high-watermark decreased")
        report["engine_state_changes"] = {
            counter: {"before": before_properties.get(counter), "after": after_properties.get(counter)}
        }
    assert_rows(spark.table(q), spark.table(backup))
    require(spark.table(q).schema.jsonValue() == original_schema, "Original Spark field metadata differs")
    require(helper.validated_catalog == original_metadata, "Original Unity Catalog metadata differs")
    restored_version[0] = helper.validated_state["version"]


def spec():
    return deepcopy(context(selected_table).state()["spec"])


def expected_projection(frame, target, aliases):
    """Test-only value oracle; independent of the framework's SQL planner."""
    histories = {item["name"].casefold(): item.get("refactorNames", []) for item in aliases}

    def source(fields, name, path):
        available = {field.name.casefold(): field for field in fields}
        if name.casefold() in available:
            return available[name.casefold()]
        full = ".".join([*path, name]).casefold()
        hits = []
        for old in histories.get(full, []):
            matches = [
                field
                for key, field in available.items()
                if old.casefold() == key or path and old.casefold().endswith("." + key)
            ]
            if matches:
                hits.append(max(matches, key=lambda field: len(field.name)))
        return hits[0] if len(hits) == 1 else None

    def project(value, old, new, path):
        if old.typeName() == new.typeName() == "struct":
            children = []
            for field in new.fields:
                previous = source(old.fields, field.name, path)
                child = (
                    project(value.getField(previous.name), previous.dataType, field.dataType, [*path, field.name])
                    if previous
                    else F.lit(None).cast(field.dataType)
                )
                children.append(child.alias(field.name))
            return F.when(value.isNull(), F.lit(None)).otherwise(F.struct(*children))
        if old.typeName() == new.typeName() == "array":
            return F.transform(value, lambda item: project(item, old.elementType, new.elementType, [*path, "element"]))
        if old.typeName() == new.typeName() == "map":
            return F.map_from_entries(
                F.transform(
                    F.map_entries(value),
                    lambda item: F.struct(
                        project(item.getField("key"), old.keyType, new.keyType, [*path, "key"]).alias("key"),
                        project(item.getField("value"), old.valueType, new.valueType, [*path, "value"]).alias("value"),
                    ),
                )
            )
        return value.cast(new)

    values = []
    for column in target["columns"]:
        previous = source(frame.schema.fields, column["name"], [])
        if column["generated"] or column["identity"] and previous is None:
            continue
        datatype = _parse_datatype_string(column["type"])
        value = (
            project(F.col(_mi(previous.name)), previous.dataType, datatype, [column["name"]])
            if previous
            else F.lit(None).cast(datatype)
        )
        values.append(value.alias(column["name"]))
    return frame.select(*values)


def call(target, aliases=None, metadata=None, fail=False):
    target = deepcopy(target)
    schema = StructType(
        [StructField(c["name"], _parse_datatype_string(c["type"]), c["nullable"]) for c in target["columns"]]
    )
    source_frame = spark.table(q)
    frozen = spark.createDataFrame(source_frame.collect(), source_frame.schema)
    expected = expected_projection(frozen, target, aliases or [])
    instance = Table(selected_table, catalog)
    try:
        result = instance.migrate_schema(
            ddl=_MigrationDDL.render(target, q),
            schema=schema,
            refactored_columns=aliases or [],
            new_partitions=target["clustering"] or target["partitions"],
            target_metadata=metadata if metadata is not None else original_metadata,
            fail_on_manual_migration=fail,
        )
    finally:
        value = getattr(instance, "last_migration_result", {})
        if value.get("target_id"):
            owned_registrations.add(value["target_id"])
        if value.get("recovery", {}).get("candidate_id"):
            owned_registrations.add(value["recovery"]["candidate_id"])
        archive = value.get("archive_table")
        if archive and spark.catalog.tableExists(archive):
            identity = baseline.state(archive)["id"]
            if identity != original["id"]:
                fixture_objects.append(("TABLE", archive, identity))
    require(result is instance.last_migration_result, "Returned result differs")
    checker = context(selected_table)
    checker.target = _MigrationDDL.parse(_MigrationDDL.render(target, q))
    checker.metadata = metadata if metadata is not None else original_metadata
    checker.validate()
    require(
        set(
            (
                "status",
                "table",
                "strategy",
                "message",
                "changes",
                "manual_migration_required",
                "archive_table",
                "reasons",
            )
        )
        <= result.keys(),
        "Incomplete result",
    )
    if not result["manual_migration_required"]:
        assert_rows(expected, spark.table(q).select(*[_mi(n) for n in expected.columns]))
    if result["manual_migration_required"]:
        require(spark.table(q).limit(1).count() == 0, "Manual target must be empty")
        require(
            result["archive_table"] and spark.catalog.tableExists(result["archive_table"]), "Missing original archive"
        )
        require(baseline.state(result["archive_table"])["id"] == result["source_id"], "Archive identity differs")
        assert_rows(frozen, spark.table(result["archive_table"]).select(*[_mi(n) for n in frozen.columns]))
    return result


def new_column(name, datatype="STRING", nullable=True, **kw):
    return {
        "name": name,
        "type": datatype,
        "nullable": nullable,
        "comment": "",
        "default": None,
        "identity": None,
        "generated": None,
        "mask": None,
        "collation": None,
        **kw,
    }


tests = []


def test(name):
    def decorate(function):
        tests.append((name, function))
        return function

    return decorate


@test("noop")
def test_noop():
    result = call(spec())
    require(result["status"] == "NOOP" and not result["changes"], "Expected NOOP")
    return result


@test("add_nullable")
def test_add():
    target = spec()
    target["columns"].append(new_column("Migration Note"))
    result = call(target)
    require(result["strategy"] == "METADATA", "Expected metadata add")
    require(call(target)["status"] == "NOOP", "Repeat must be NOOP")
    return result


@test("rename_aliases")
def test_rename():
    target = spec()
    old = target["columns"][-1]["name"]
    target["columns"][-1]["name"] = "Renamed Column"
    metadata = deepcopy(original_metadata)
    if old in metadata["column_tags"]:
        metadata["column_tags"]["Renamed Column"] = metadata["column_tags"].pop(old)
    result = call(target, [{"name": "Renamed Column", "refactorNames": ["not_present", old]}], metadata)
    require(result["strategy"] == "METADATA", "Expected metadata rename")
    expected = spark.table(backup).withColumnRenamed(old, "Renamed Column")
    _TableMigration.assert_data(expected, spark.table(q))
    return result


@test("manual_not_null")
def test_manual():
    target = spec()
    target["columns"].append(new_column("MissingRequired", "STRING", False))
    result = call(target)
    require(result["status"] == "MANUAL_DATA_MIGRATION_REQUIRED", "Expected manual fallback")
    _TableMigration.assert_data(spark.table(backup), spark.table(result["archive_table"]))
    return result


@test("manual_raises")
def test_manual_error():
    target = spec()
    target["columns"].append(new_column("MissingRequired", "STRING", False))
    try:
        call(target, fail=True)
    except ManualDataMigrationRequired as error:
        require(error.result["status"] == "MANUAL_DATA_MIGRATION_REQUIRED", "Exception result has wrong status")
        require(spark.table(q).limit(1).count() == 0, "Target must remain empty")
        checker = context(selected_table)
        checker.target, checker.metadata = target, original_metadata
        checker.validate()
        require(baseline.state(error.result["archive_table"])["id"] == original["id"], "Original archive changed")
        assert_rows(spark.table(backup), spark.table(error.result["archive_table"]))
        return error.result
    raise AssertionError("Expected ManualDataMigrationRequired")


fixture_objects = []


def isolate_fixture():
    """Preserve the original identity for fixtures requiring protocol changes."""
    require(not spark.catalog.tableExists(parked), "Fixture original already exists")
    spark.sql("ALTER TABLE " + q + " RENAME TO " + parked).collect()
    spark.sql("CREATE TABLE " + q + " DEEP CLONE " + parked).collect()
    owned_registrations.add(baseline.state()["id"])
    restore_fixture_catalog()


def restore_fixture_catalog():
    helper = context(selected_table)
    helper.result, helper.changed = {"changes": []}, False
    helper.restore_catalog(original_metadata, grants=True)


def prepare(columns, *, empty=False):
    for name, datatype, expression in columns:
        spark.sql(f"ALTER TABLE {q} ADD COLUMNS ({_mi(name)} {datatype})").collect()
        if expression is not None:
            spark.sql(f"UPDATE {q} SET {_mi(name)} = {expression}").collect()
    if empty:
        spark.sql("DELETE FROM " + q).collect()
    return spec()


def get_column(target, name):
    return next(c for c in target["columns"] if c["name"] == name)


def sample_key():
    return (
        "CAST("
        + _mi(
            next(
                c["name"]
                for c in original["spec"]["columns"]
                if c["name"].lower().endswith("id") and not c["name"].startswith("__")
            )
        )
        + " AS BIGINT)"
    )


def register_change(name, preparation, change, *, manual=False, aliases=None, strategy=None):
    @test(name)
    def scenario():
        target = preparation()
        change(target)
        result = call(target, aliases)
        require(result["manual_migration_required"] == manual, "Unexpected data migration outcome")
        if strategy:
            require(result["strategy"] == strategy, "Unexpected strategy: " + result["strategy"])
        return result


register_change(
    "add_multiple",
    spec,
    lambda s: s["columns"].extend([new_column("NewA", "INT"), new_column("NewB", "DECIMAL(12,3)")]),
    strategy="METADATA",
)
register_change(
    "not_null_empty",
    lambda: prepare([], empty=True),
    lambda s: s["columns"].append(new_column("Required", "INT", False)),
)
register_change(
    "drop_one",
    lambda: prepare([("__test_a", "INT", "1")]),
    lambda s: s.__setitem__("columns", [c for c in s["columns"] if c["name"] != "__test_a"]),
    strategy="METADATA",
)
register_change(
    "drop_multiple",
    lambda: prepare([("__test_a", "INT", "1"), ("__test_b", "STRING", "'b'")]),
    lambda s: s.__setitem__("columns", [c for c in s["columns"] if not c["name"].startswith("__test_")]),
    strategy="METADATA",
)
register_change("reorder", spec, lambda s: s["columns"].reverse(), strategy="METADATA")
register_change(
    "nullable_to_required",
    lambda: prepare([("__test_a", "INT", "1")]),
    lambda s: get_column(s, "__test_a").__setitem__("nullable", False),
    strategy="METADATA",
)
register_change(
    "nullable_violation",
    lambda: prepare([("__test_a", "INT", None)]),
    lambda s: get_column(s, "__test_a").__setitem__("nullable", False),
    manual=True,
)


@test("required_to_nullable")
def test_relax():
    target = prepare([("__test_a", "INT", "1")])
    spark.sql(f"ALTER TABLE {q} ALTER COLUMN __test_a SET NOT NULL").collect()
    get_column(target, "__test_a")["nullable"] = True
    return call(target)


def prepare_widening(datatype, expression):
    if datatype in {"DATE", "VOID"}:
        isolate_fixture()
    if datatype == "DATE":
        spark.sql(f"ALTER TABLE {q} SET TBLPROPERTIES ('delta.feature.timestampNtz'='supported')").collect()
    return prepare([("__test_value", datatype, expression)])


for old_type, new_type, value, label in [
    ("TINYINT", "SMALLINT", "1", "byte_short"),
    ("SMALLINT", "INT", "1", "short_int"),
    ("TINYINT", "INT", "1", "byte_int"),
    ("TINYINT", "BIGINT", "1", "byte_long"),
    ("SMALLINT", "BIGINT", "1", "short_long"),
    ("INT", "BIGINT", "1", "int_long"),
    ("TINYINT", "DOUBLE", "127", "byte_double"),
    ("SMALLINT", "DOUBLE", "32767", "short_double"),
    ("INT", "DOUBLE", "2147483647", "int_double"),
    ("TINYINT", "DECIMAL(12,2)", "127", "byte_decimal"),
    ("SMALLINT", "DECIMAL(12,2)", "32767", "short_decimal"),
    ("INT", "DECIMAL(12,2)", "2147483647", "int_decimal"),
    ("BIGINT", "DECIMAL(22,2)", "9223372036854775807", "long_decimal"),
    ("FLOAT", "DOUBLE", "1.25", "float_double"),
    ("DECIMAL(10,2)", "DECIMAL(14,4)", "1.25", "decimal"),
    ("DATE", "TIMESTAMP_NTZ", "DATE '2020-01-02'", "date_ntz"),
    ("VOID", "STRING", None, "void_string"),
]:
    register_change(
        "widen_" + label,
        lambda t=old_type, v=value: prepare_widening(t, v),
        lambda s, t=new_type: get_column(s, "__test_value").__setitem__("type", t),
        strategy="METADATA",
    )

for old_type, new_type, value, label, manual in [
    ("STRING", "INT", "'123'", "valid_string", False),
    ("BIGINT", "INT", "123", "valid_narrowing", False),
    ("STRING", "INT", "'invalid'", "invalid_string", True),
    ("BIGINT", "TINYINT", "99999", "overflow", True),
    ("DECIMAL(10,3)", "DECIMAL(10,1)", "1.234", "rounding", True),
    ("STRING", "DATE", "'01/02/2020'", "ambiguous_date", True),
    ("STRING", "DATE", "'2020-01-02'", "iso_date", False),
    ("STRING", "TIMESTAMP_NTZ", "'2020-01-02 03:04:05.123456'", "iso_ntz", False),
    ("STRING", "TIMESTAMP", "'2020-01-02 03:04:05'", "ambiguous_timestamp", True),
    ("BIGINT", "DOUBLE", "9007199254740993", "precision_loss", True),
]:
    register_change(
        "cast_" + label,
        lambda t=old_type, v=value: prepare([("__test_value", t, v)]),
        lambda s, t=new_type: get_column(s, "__test_value").__setitem__("type", t),
        manual=manual,
    )


@test("multiple_renames_and_widening")
def test_combined():
    target = prepare([("__test_a", "INT", "7"), ("__test_b", "STRING", "'hello'"), ("__test_drop", "STRING", "'old'")])
    get_column(target, "__test_a").update(name="RenamedA", type="BIGINT")
    get_column(target, "__test_b")["name"] = "RenamedB"
    target["columns"].append(new_column("Additional"))
    target["columns"] = [c for c in target["columns"] if c["name"] != "__test_drop"]
    target["columns"].reverse()
    target["comment"], target["clustering"] = "Combined migration", ["RenamedA"]
    metadata = deepcopy(original_metadata)
    metadata["table_tags"]["migration_test"] = "combined"
    return call(
        target,
        [{"name": "RenamedA", "refactorNames": ["__test_a"]}, {"name": "RenamedB", "refactorNames": ["__test_b"]}],
        metadata=metadata,
    )


for name, old, new in [("case_only", "__test_name", "__TEST_NAME"), ("quoted_name", "__test_name", "select ` from")]:
    register_change(
        name,
        lambda o=old: prepare([(o, "STRING", "'value'")]),
        lambda s, o=old, n=new: get_column(s, o).__setitem__("name", n),
        aliases=[{"name": new, "refactorNames": [old]}],
        strategy="METADATA",
    )


@test("historical_target_already_exists")
def test_existing_name():
    target = spec()
    name = target["columns"][-1]["name"]
    result = call(target, [{"name": name, "refactorNames": ["removed_old_name", "older_name"]}])
    require(result["status"] == "NOOP", "Historical aliases must not cause changes")
    return result


@test("historical_source_absent")
def test_missing_alias():
    target = spec()
    target["columns"].append(new_column("NewTarget"))
    return call(target, [{"name": "NewTarget", "refactorNames": ["missing_name"]}])


@test("ambiguous_many_sources")
def test_ambiguous_sources():
    target = prepare([("__test_a", "INT", "1"), ("__test_b", "INT", "2")])
    target["columns"] = [c for c in target["columns"] if c["name"] not in {"__test_a", "__test_b"}]
    target["columns"].append(new_column("Combined", "INT"))
    result = call(target, [{"name": "Combined", "refactorNames": ["__test_a", "__test_b"]}])
    require(result["manual_migration_required"], "Ambiguous mapping must be manual")
    return result


@test("ambiguous_many_targets")
def test_ambiguous_targets():
    target = prepare([("__test_a", "INT", "1")])
    target["columns"] = [c for c in target["columns"] if c["name"] != "__test_a"]
    target["columns"].extend([new_column("A", "INT"), new_column("B", "INT")])
    result = call(target, [{"name": n, "refactorNames": ["__test_a"]} for n in ("A", "B")])
    require(result["manual_migration_required"], "One-to-many mapping must be manual")
    return result


@test("ambiguous_old_and_new")
def test_both_names():
    target = prepare([("__test_a", "INT", "1"), ("__test_b", "INT", "2")])
    target["columns"] = [c for c in target["columns"] if c["name"] != "__test_a"]
    result = call(target, [{"name": "__test_b", "refactorNames": ["__test_a"]}])
    require(result["manual_migration_required"], "Coexisting old/new values must not be merged")
    return result


@test("comments")
def test_comments():
    target = spec()
    target["comment"] = "Table's `comment`, punctuation, äöü, slash\\path\nnext line"
    target["columns"][-1]["comment"] = "Column's comment, value"
    first = call(target)
    target["comment"], target["columns"][-1]["comment"] = "", ""
    second = call(target)
    return {"set": first, "clear": second}


@test("properties")
def test_properties():
    target = spec()
    target["properties"]["test.custom"] = "a,b=c"
    first = call(target)
    target["properties"]["test.custom"] = "changed"
    second = call(target)
    del target["properties"]["test.custom"]
    third = call(target)
    return {"add": first, "change": second, "remove": third}


@test("tags")
def test_tags():
    target = spec()
    metadata = deepcopy(original_metadata)
    metadata["table_tags"]["migration_test"] = "one"
    name = target["columns"][-1]["name"]
    metadata["column_tags"].setdefault(name, {})["migration_test"] = "column"
    first = call(target, metadata=metadata)
    metadata["table_tags"]["migration_test"] = "two"
    metadata["column_tags"][name]["migration_test"] = "changed_column"
    second = call(target, metadata=metadata)
    third = call(target, metadata={"owner": original_metadata["owner"], "table_tags": {}, "column_tags": {}})
    return {"add": first, "change": second, "clear": third}


@test("legacy_call")
def test_legacy():
    target = spec()
    schema = StructType([StructField(c["name"], _parse_datatype_string(c["type"])) for c in target["columns"]])
    return Table(selected_table, catalog).migrate_schema(
        _MigrationDDL.render(target, q), schema, [], target["clustering"] or target["partitions"]
    )


@test("defaults")
def test_defaults():
    isolate_fixture()
    target = prepare([("__test_default", "INT", "5")])
    target["properties"]["delta.feature.allowColumnDefaults"] = "supported"
    get_column(target, "__test_default")["default"] = "7"
    first = call(target)
    require(
        spark.sql(f"SELECT count(*) FROM {q} WHERE __test_default <> 5").first()[0] == 0, "DEFAULT must not backfill"
    )
    insert_columns = ", ".join(_mi(c["name"]) for c in original["spec"]["columns"])
    spark.sql(f"INSERT INTO {q} ({insert_columns}) SELECT {insert_columns} FROM {backup} LIMIT 1").collect()
    require(spark.sql(f"SELECT 1 FROM {q} WHERE __test_default=7 LIMIT 1").first(), "New inserts must use DEFAULT 7")
    get_column(target, "__test_default")["default"] = "9"
    second = call(target)
    spark.sql(f"INSERT INTO {q} ({insert_columns}) SELECT {insert_columns} FROM {backup} LIMIT 1").collect()
    require(spark.sql(f"SELECT 1 FROM {q} WHERE __test_default=9 LIMIT 1").first(), "Changed DEFAULT must apply")
    get_column(target, "__test_default")["default"] = None
    third = call(target)
    spark.sql(f"INSERT INTO {q} ({insert_columns}) SELECT {insert_columns} FROM {backup} LIMIT 1").collect()
    require(
        spark.sql(f"SELECT 1 FROM {q} WHERE __test_default IS NULL LIMIT 1").first(), "Removed DEFAULT must yield NULL"
    )
    return {"add": first, "change": second, "remove": third}


for label, old_type, new_type, expression in [
    ("struct_add", "STRUCT<a:INT>", "STRUCT<a:INT,b:STRING>", "named_struct('a',1)"),
    ("struct_drop", "STRUCT<a:INT,b:STRING>", "STRUCT<a:INT>", "named_struct('a',1,'b','b')"),
    ("struct_widen", "STRUCT<a:INT>", "STRUCT<a:BIGINT>", "named_struct('a',1)"),
    ("array_widen", "ARRAY<INT>", "ARRAY<BIGINT>", "array(1,2)"),
    ("array_struct_add", "ARRAY<STRUCT<a:INT>>", "ARRAY<STRUCT<a:INT,b:STRING>>", "array(named_struct('a',1))"),
    ("map_widen", "MAP<STRING,INT>", "MAP<STRING,BIGINT>", "map('a',1)"),
]:
    register_change(
        label,
        lambda t=old_type, e=expression: prepare([("__test_nested", t, e)]),
        lambda s, t=new_type: get_column(s, "__test_nested").__setitem__("type", t),
    )


@test("struct_rename")
def test_struct_rename():
    target = prepare([("__test_nested", "STRUCT<a:INT>", "named_struct('a',1)")])
    get_column(target, "__test_nested")["type"] = "STRUCT<b:INT>"
    return call(target, [{"name": "__test_nested.b", "refactorNames": ["__test_nested.a"]}])


@test("map_key_collision")
def test_map_collision():
    target = prepare([("__test_map", "MAP<STRING,INT>", "map('1',1,'01',2)")])
    get_column(target, "__test_map")["type"] = "MAP<INT,INT>"
    result = call(target)
    require(result["manual_migration_required"], "Map conversion must not discard colliding keys")
    return result


def prepare_constraint(kind):
    if kind.startswith("CHECK"):
        isolate_fixture()
    return prepare([("__test_key", "BIGINT", "1")])


for label, kind, valid in [
    ("check_valid", "CHECK (__test_key > 0)", True),
    ("check_invalid", "CHECK (__test_key < 0)", False),
    ("check_null", "CHECK (CAST(NULL AS BOOLEAN))", False),
    ("pk_invalid", "PRIMARY KEY (__test_key) RELY", False),
]:
    register_change(
        label,
        lambda k=kind: prepare_constraint(k),
        lambda s, k=kind: s["constraints"].append({"name": "test_" + test_id, "body": k}),
        manual=not valid,
    )


@test("clustering")
def test_clustering():
    target = prepare([("__test_cluster", "INT", "1")])
    target["clustering"] = ["__test_cluster"]
    first = call(target)
    target["clustering"] = []
    second = call(target)
    target["clustering"] = original["spec"]["clustering"]
    third = call(target)
    return {"set": first, "clear": second, "add": third}


@test("check_change_remove")
def test_check_change_remove():
    isolate_fixture()
    target = prepare([("__test_key", "BIGINT", "1")])
    target["constraints"].append({"name": "test_check_" + test_id, "body": "CHECK (__test_key > 0)"})
    first = call(target)
    target["constraints"][-1]["body"] = "CHECK (__test_key >= 0)"
    second = call(target)
    target["constraints"].pop()
    third = call(target)
    return {"add": first, "change": second, "remove": third}


@test("technical_failure_recovery")
def test_recovery():
    target = spec()
    target["columns"].append(new_column("__test_fail"))
    original_execute = _TableMigration.execute_sql
    injected = [False]

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "ADD_COLUMN" and not injected[0]:
            injected[0] = True
            raise RuntimeError("Injected technical failure after real ADD COLUMN")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require(error.result["status"] == "FAILED", "Expected technical failure")
            require("__test_fail" not in spark.table(q).columns, "Framework recovery did not restore schema")
            return error.result
        raise AssertionError("Failure was not raised")
    finally:
        _TableMigration.execute_sql = original_execute


@test("plan_read_only")
def test_plan():
    target = spec()
    target["columns"].append(new_column("Planned"))
    before = baseline.state()
    schema = StructType([StructField(c["name"], _parse_datatype_string(c["type"])) for c in target["columns"]])
    result = Table(selected_table, catalog).plan_schema_migration(
        _MigrationDDL.render(target, q), schema, [], target["clustering"] or target["partitions"], original_metadata
    )
    require(result["strategy"] == "METADATA" and result["sql"], "Expected executable metadata plan")
    require(baseline.state()["version"] == before["version"], "Planning must not commit")
    require("Planned" not in spark.table(q).columns, "Planning changed schema")
    return result


@test("cycle_current_names")
def test_cycle():
    target = prepare([("__test_a", "INT", "1"), ("__test_b", "INT", "2")])
    result = call(
        target,
        [{"name": "__test_a", "refactorNames": ["__test_b"]}, {"name": "__test_b", "refactorNames": ["__test_a"]}],
    )
    require(result["status"] == "NOOP", "Current names take precedence over historical aliases")
    return result


def identity_fixture(mode="ALWAYS"):
    isolate_fixture()
    target = spec()
    target["columns"].append(
        new_column("__test_identity", "BIGINT", False, identity="GENERATED " + mode + " AS IDENTITY")
    )
    spark.sql(_MigrationDDL.render(target, q, replace=True, constraints=False)).collect()
    names = ", ".join(_mi(c["name"]) for c in original["spec"]["columns"])
    spark.sql(f"INSERT INTO {q} ({names}) SELECT {names} FROM {backup}").collect()
    restore_fixture_catalog()
    return spec()


@test("identity_unchanged")
def test_identity_unchanged():
    result = call(identity_fixture())
    require(result["status"] == "NOOP", "Unchanged identity must not rebuild")
    return result


@test("identity_add")
def test_identity_add():
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    result = call(target)
    require(result["strategy"] == "ARCHIVE_AND_COPY", "Expected automatic identity creation")
    require(
        spark.sql(f"SELECT count(*)=count(DISTINCT __test_identity) FROM {q}").first()[0],
        "Generated keys must be unique",
    )
    return result


@test("identity_always_manual")
def test_identity_always():
    target = identity_fixture()
    target["clustering"] = []
    target["partitions"] = [target["columns"][0]["name"]]
    result = call(target)
    require(result["manual_migration_required"], "Existing ALWAYS keys must not be regenerated")
    return result


@test("identity_by_default_copy")
def test_identity_default():
    target = identity_fixture("BY DEFAULT")
    target["clustering"] = []
    target["partitions"] = [target["columns"][0]["name"]]
    result = call(target)
    require(result["strategy"] == "ARCHIVE_AND_COPY", "Expected identity values to be copied")
    require(any(c["action"] == "SYNC_IDENTITY" for c in result["changes"]), "Identity sequence must be synced")
    return result


@test("identity_remove")
def test_identity_remove():
    target = identity_fixture()
    get_column(target, "__test_identity")["identity"] = None
    return call(target)


@test("partition_rewrite")
def test_partition():
    target = prepare([("__test_partition", "INT", "1")])
    target["clustering"], target["partitions"] = [], ["__test_partition"]
    first = call(target)
    require(first["strategy"] == "ARCHIVE_AND_COPY", "Liquid-to-partitioned transition needs a new table")
    target["partitions"] = []
    second = call(target)
    target["clustering"] = original["spec"]["clustering"]
    third = call(target)
    return {"partition": first, "unpartition": second, "recluster": third}


@test("pk_valid_change_remove")
def test_pk():
    target = prepare(
        [
            (
                "__test_key",
                "BIGINT",
                "CAST("
                + _mi(
                    next(
                        c["name"]
                        for c in original["spec"]["columns"]
                        if c["name"].lower().endswith("id") and not c["name"].startswith("__")
                    )
                )
                + " AS BIGINT)",
            )
        ]
    )
    get_column(target, "__test_key")["nullable"] = False
    target["constraints"].append({"name": "test_pk_" + test_id, "body": "PRIMARY KEY (__test_key) RELY"})
    first = call(target)
    target["constraints"][-1]["body"] = "PRIMARY KEY (__test_key) NORELY"
    second = call(target)
    target["constraints"].pop()
    third = call(target)
    return {"add": first, "change": second, "remove": third}


def foreign_case(valid):
    target = prepare([("__test_fk", "BIGINT", "1" if valid else "999999")])
    reference = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_reference_" + test_id])
    spark.sql(
        f"CREATE TABLE {reference} (id BIGINT NOT NULL, "
        f"CONSTRAINT {_mi('reference_pk_' + test_id)} PRIMARY KEY (id)) USING DELTA"
    ).collect()
    fixture_objects.append(("TABLE", reference, baseline.state(reference)["id"]))
    spark.sql(f"INSERT INTO {reference} VALUES (1)").collect()
    target["constraints"].append(
        {"name": "test_fk_" + test_id, "body": f"FOREIGN KEY (__test_fk) REFERENCES {reference} (id)"}
    )
    result = call(target)
    require(result["manual_migration_required"] == (not valid), "Unexpected FK transfer outcome")
    if valid:
        target["constraints"][-1]["body"] += " RELY"
        changed = call(target)
        target["constraints"].pop()
        removed = call(target)
        return {"add": result, "change": changed, "remove": removed}
    return result


@test("fk_valid")
def test_fk_valid():
    return foreign_case(True)


@test("fk_invalid")
def test_fk_invalid():
    return foreign_case(False)


@test("owner_same_and_invalid")
def test_owner():
    target = spec()
    first = call(target)
    metadata = deepcopy(original_metadata)
    metadata["owner"] = "missing_migration_test_principal_" + test_id
    try:
        call(target, metadata=metadata)
    except MigrationFailed as error:
        require(error.result["status"] == "FAILED", "Owner errors are technical failures")
        return {"same": first, "invalid": error.result}
    raise AssertionError("Invalid owner should fail")


@test("owner_transfer")
def test_owner_transfer():
    isolate_fixture()
    # An explicit fixture-only MANAGE grant remains effective after transfer.
    spark.sql(f"GRANT MANAGE ON TABLE {q} TO {_mi(original_metadata['owner'])}").collect()
    metadata = deepcopy(original_metadata)
    metadata["owner"] = "98f791a9-70d7-4fda-9ac2-a6670d8b26e2"
    return call(spec(), metadata=metadata)


for stage in ("CREATE_CANDIDATE", "COPY_DATA", "ARCHIVE_TABLE", "ACTIVATE_TARGET"):

    def register_failure(action):
        @test("failure_" + action.lower())
        def scenario():
            target = spec()
            target["columns"].append(
                new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY")
            )
            original_execute = _TableMigration.execute_sql
            injected = [False]

            def execute(migration, sql, actual_action, **info):
                original_execute(migration, sql, actual_action, **info)
                if actual_action == action and not injected[0]:
                    injected[0] = True
                    raise RuntimeError("Injected failure after real " + action)

            _TableMigration.execute_sql = execute
            try:
                try:
                    call(target)
                except MigrationFailed as error:
                    require("RECOVERY_REQUIRED" not in error.result["message"], "Recovery must complete")
                    require(baseline.state()["id"] == original["id"], "Original identity not recovered")
                    return error.result
                raise AssertionError("Expected technical failure")
            finally:
                _TableMigration.execute_sql = original_execute

    register_failure(stage)


@test("lost_sql_response")
def test_lost_response():
    target = spec()
    target["columns"].append(new_column("__test_lost"))
    original_execute = _TableMigration.execute_sql
    injected = [False]

    def execute(migration, sql, action, **info):
        if action == "ADD_COLUMN" and not injected[0]:
            injected[0] = True
            migration.spark.sql(sql).collect()
            raise TimeoutError("Simulated response loss after committed ADD COLUMN")
        return original_execute(migration, sql, action, **info)

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require("__test_lost" not in spark.table(q).columns, "Unacknowledged commit was not recovered")
            require("RECOVERY_REQUIRED" not in error.result["message"], "Recovery failed")
            return error.result
        raise AssertionError("Expected a lost-response failure")
    finally:
        _TableMigration.execute_sql = original_execute


@test("interrupted_after_archive")
def test_interruption():
    class ProcessExit(BaseException):
        pass

    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    original_execute = _TableMigration.execute_sql
    artifacts = {}

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "ARCHIVE_TABLE":
            artifacts.update(
                archive=migration.archive, candidate=migration.candidate, candidate_id=migration.candidate_id
            )
            raise ProcessExit("Simulated process interruption; bypass framework exception recovery")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except ProcessExit:
            require(not spark.catalog.tableExists(q), "Interruption should precede target activation")
            fixture_objects.append(("TABLE", artifacts["candidate"], artifacts["candidate_id"]))
            restore_original()
            require(baseline.state()["id"] == original["id"], "External restoration did not recover original identity")
            return {
                "interruption_simulated": True,
                "archive": artifacts["archive"],
                "original_restored_without_migration_context": True,
            }
        raise AssertionError("Interruption was not injected")
    finally:
        _TableMigration.execute_sql = original_execute


@test("metadata_failure_recovery")
def test_tag_failure():
    metadata = deepcopy(original_metadata)
    metadata["table_tags"]["test_failure"] = "temporary"
    original_execute = _TableMigration.execute_sql
    injected = [False]

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "SET_TAG" and not injected[0]:
            injected[0] = True
            raise RuntimeError("Injected failure after real SET TAGS")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(spec(), metadata=metadata)
        except MigrationFailed as error:
            require(baseline.catalog_metadata() == original_metadata, "Catalog metadata not recovered")
            return error.result
        raise AssertionError("Expected metadata failure")
    finally:
        _TableMigration.execute_sql = original_execute


@test("invalid_property")
def test_invalid_property():
    target = spec()
    target["properties"]["delta.columnMapping.mode"] = "not_a_mode"
    try:
        call(target)
    except MigrationFailed as error:
        require("RECOVERY_REQUIRED" not in error.result["message"], "Original must be recoverable")
        return error.result
    raise AssertionError("Invalid Delta property must fail")


@test("generated_ddl_defaults")
def test_model_definition():
    target = spec()
    for key in (
        "delta.checkpointPolicy",
        "delta.enableDeletionVectors",
        "delta.enableRowTracking",
        "delta.parquet.format.version",
    ):
        target["properties"].pop(key, None)
    for column in target["columns"]:
        if column["collation"] == "UTF8_BINARY":
            column["collation"] = None
    result = call(target)
    require(call(target)["status"] == "NOOP", "Implicit engine defaults must not trigger repeated migrations")
    return result


@test("row_filter_preserved")
def test_filter():
    prepare([("__test_policy", "BOOLEAN", "true")])
    function = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_filter_" + test_id])
    spark.sql(f"CREATE FUNCTION {function}(v BOOLEAN) RETURNS BOOLEAN RETURN v").collect()
    fixture_objects.append(("FUNCTION", function, function_fingerprint(function)))
    spark.sql(f"ALTER TABLE {q} SET ROW FILTER {function} ON (__test_policy)").collect()
    target = spec()
    target["comment"] = "Keep the existing row filter"
    result = call(target)
    require(context(selected_table).state()["spec"]["row_filter"], "Row filter disappeared")
    require(call(target)["status"] == "NOOP", "Protected metadata target must be idempotent")
    original_execute = _TableMigration.execute_sql

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "TABLE_COMMENT":
            raise RuntimeError("Injected failure after protected metadata change")

    target["comment"] = "Protected metadata failure"
    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require("original table restored" in error.result["message"], "Protected metadata recovery failed")
            require(
                context(selected_table).state()["spec"]["comment"] == "Keep the existing row filter",
                "Protected comment was not restored",
            )
            return {"success": result, "recovery": error.result}
        raise AssertionError("Expected protected metadata failure")
    finally:
        _TableMigration.execute_sql = original_execute


@test("deleted_rows_and_duplicates")
def test_all_rows():
    spark.sql(f"INSERT INTO {q} SELECT * FROM {backup} LIMIT 1").collect()
    target = prepare([("__IsDeleted", "BOOLEAN", "true")])
    target["columns"].append(new_column("Added"))
    result = call(target)
    expected = spark.table(backup).union(spark.table(backup).limit(1))
    expected = expected.withColumn("__IsDeleted", F.lit(True)).withColumn("Added", F.lit(None).cast("string"))
    _TableMigration.assert_data(expected, spark.table(q))
    return result


@test("column_mask_preserved")
def test_mask():
    prepare([("__test_masked", "STRING", "'private'")])
    function = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_mask_" + test_id])
    spark.sql(f"CREATE FUNCTION {function}(v STRING) RETURNS STRING RETURN v").collect()
    fixture_objects.append(("FUNCTION", function, function_fingerprint(function)))
    spark.sql(f"ALTER TABLE {q} ALTER COLUMN __test_masked SET MASK {function}").collect()
    target = spec()
    target["comment"] = "Keep the existing column mask"
    result = call(target)
    require(get_column(context(selected_table).state()["spec"], "__test_masked")["mask"], "Column mask disappeared")
    return result


@test("incoming_reference")
def test_incoming_reference():
    isolate_fixture()
    key = next(
        c["name"]
        for c in original["spec"]["columns"]
        if c["name"].lower().endswith("id") and not c["name"].startswith("__")
    )
    target = prepare([("__test_key", "BIGINT", "CAST(" + _mi(key) + " AS BIGINT)")])
    get_column(target, "__test_key")["nullable"] = False
    target["constraints"].append({"name": "incoming_pk_" + test_id, "body": "PRIMARY KEY (__test_key) RELY"})
    call(target)
    child = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_child_" + test_id])
    spark.sql(
        f"CREATE TABLE {child} (ref BIGINT, CONSTRAINT {_mi('incoming_fk_' + test_id)} "
        f"FOREIGN KEY (ref) REFERENCES {q} (__test_key)) USING DELTA"
    ).collect()
    fixture_objects.append(("DEPENDENT_TABLE", child, baseline.state(child)["id"]))
    spark.sql(f"INSERT INTO {child} SELECT __test_key FROM {q} LIMIT 1").collect()
    target = spec()
    target["columns"].append(new_column("Additional"))
    added = call(target)
    require(added["strategy"] == "METADATA", "Unrelated additions must not rebuild referenced tables")
    require(not any(c["action"] == "DROP_CONSTRAINT" for c in added["changes"]), "Unrelated additions must retain PK")
    target = spec()
    get_column(target, "__test_key")["name"] = "RenamedKey"
    target["constraints"][-1]["body"] = "PRIMARY KEY (RenamedKey) RELY"
    try:
        call(target, [{"name": "RenamedKey", "refactorNames": ["__test_key"]}])
    except MigrationFailed as error:
        require("ARCHIVE_CONSTRAINT_NAME_CONFLICT" in str(error), "Expected exact namespace conflict")
        require(not error.result["changes"], "Namespace conflict must be detected before mutation")
    else:
        raise AssertionError("Expected a schema-wide constraint-name conflict")
    target["constraints"][-1]["name"] = "renamed_incoming_pk_" + test_id
    renamed = call(target, [{"name": "RenamedKey", "refactorNames": ["__test_key"]}])
    require(renamed["strategy"] == "ARCHIVE_AND_COPY", "Referenced key changes need an archive")
    require(renamed.get("manual_actions"), "Incoming references must be reported")
    return {"addition": added, "key_rename": renamed}


@test("grants_rebuild")
def test_grants_rebuild():
    isolate_fixture()
    principal = "98f791a9-70d7-4fda-9ac2-a6670d8b26e2"
    spark.sql(f"GRANT SELECT ON TABLE {q} TO {_mi(principal)}").collect()
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    result = call(target)
    require(result["strategy"] == "ARCHIVE_AND_COPY", "Grant preservation must exercise a new registration")
    require(
        any(
            row.get("Principal") == principal
            and row.get("ActionType") == "SELECT"
            and row.get("ObjectType", "").upper() == "TABLE"
            for row in context(selected_table).catalog_metadata()["grants"]
        ),
        "Explicit table grant was not retained",
    )
    return result


@test("protected_source_rebuild")
def test_protected_rebuild():
    isolate_fixture()
    prepare([("__test_policy", "BOOLEAN", "true")])
    function = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_protected_" + test_id])
    spark.sql(f"CREATE FUNCTION {function}(v BOOLEAN) RETURNS BOOLEAN RETURN v").collect()
    fixture_objects.append(("FUNCTION", function, function_fingerprint(function)))
    spark.sql(f"ALTER TABLE {q} SET ROW FILTER {function} ON (__test_policy)").collect()
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    result = call(target)
    require(result["manual_migration_required"], "Protected sources require proof of full data visibility")
    require(context(selected_table).state()["spec"]["row_filter"], "Empty target must retain the protection")
    require(any(r["code"] == "PROTECTED_SOURCE" for r in result["reasons"]), "Missing concrete security reason")
    return result


@test("legacy_rename_rewrite")
def test_legacy_rewrite():
    target = spec()
    old = "ModifiedAt"
    get_column(target, old).update(name="LegacyModified", type="STRING", collation=None)
    schema = StructType([StructField(c["name"], _parse_datatype_string(c["type"])) for c in target["columns"]])
    instance = Table(selected_table, catalog)
    result = instance.migrate_schema(
        _MigrationDDL.render(target, q),
        schema,
        [{"name": "LegacyModified", "refactorNames": [old]}],
        target["clustering"],
    )
    require(result["strategy"] == "REWRITE", "Expected a legacy rename plus conversion rewrite")
    actual = context(selected_table).catalog_metadata()
    require(actual["table_tags"] == original_metadata["table_tags"], "Legacy table tags changed")
    require(
        actual["column_tags"].get("LegacyModified", {}) == original_metadata["column_tags"].get(old, {}),
        "Legacy rewritten column lost its tags",
    )
    expected = spark.table(backup).withColumnRenamed(old, "LegacyModified")
    expected = expected.withColumn("LegacyModified", F.col("LegacyModified").cast("string"))
    _TableMigration.assert_data(expected, spark.table(q))
    return result


@test("quoted_rewrite")
def test_quoted_rewrite():
    target = prepare([("value.with ` quote", "STRING", "'123'")])
    get_column(target, "value.with ` quote")["type"] = "INT"
    result = call(target)
    require(result["strategy"] == "REWRITE", "Quoted identifiers must support data rewrites")
    return result


@test("generated_add_change")
def test_generated():
    target = prepare([("__test_value", "BIGINT", "1")])
    target["columns"].append(
        new_column("__test_computed", "BIGINT", generated="GENERATED ALWAYS AS (__test_value + 1)")
    )
    first = call(target)
    require(
        spark.sql(f"SELECT 1 FROM {q} WHERE __test_computed <> 2 LIMIT 1").first() is None,
        "Generated values must be evaluated",
    )
    target = spec()
    get_column(target, "__test_computed")["generated"] = "GENERATED ALWAYS AS (__test_value + 2)"
    second = call(target)
    require(
        spark.sql(f"SELECT 1 FROM {q} WHERE __test_computed <> 3 LIMIT 1").first() is None,
        "Changed generated values must be recalculated",
    )
    return {"add": first, "change": second}


@test("generated_not_null_manual")
def test_generated_null():
    target = prepare([("__test_value", "BIGINT", None)])
    target["columns"].append(
        new_column("__test_computed", "BIGINT", False, generated="GENERATED ALWAYS AS (__test_value + 1)")
    )
    result = call(target)
    require(result["manual_migration_required"], "Invalid generated values must leave an empty target")
    return result


for label, value, valid in [
    ("unique_valid", "sample_key", True),
    ("unique_invalid", "1", False),
    ("unique_nulls", None, True),
]:
    register_change(
        label,
        lambda v=value: prepare([("__test_unique", "BIGINT", sample_key() if v == "sample_key" else v)]),
        lambda s: s["constraints"].append({"name": "test_unique_" + test_id, "body": "UNIQUE (__test_unique) RELY"}),
        manual=not valid,
    )


@test("self_reference")
def test_self_reference():
    isolate_fixture()
    target = prepare([("__test_key", "BIGINT", sample_key()), ("__test_parent", "BIGINT", None)])
    get_column(target, "__test_key")["nullable"] = False
    target["constraints"].append({"name": "self_pk_" + test_id, "body": "PRIMARY KEY (__test_key) RELY"})
    call(target)
    target = spec()
    target["constraints"].append(
        {"name": "self_fk_" + test_id, "body": f"FOREIGN KEY (__test_parent) REFERENCES {q} (__test_key)"}
    )
    first = call(target)
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    for constraint in target["constraints"]:
        constraint["name"] = "rebuild_" + constraint["name"]
    second = call(target)
    require(not second.get("manual_actions"), "Self references must follow the new target automatically")
    return {"add": first, "rebuild": second}


@test("collation_feature")
def test_collation_feature():
    target = prepare([("__test_text", "STRING", "'A'")])
    get_column(target, "__test_text")["collation"] = "UTF8_LCASE"
    result = call(target)
    require(result["strategy"] == "ARCHIVE_AND_COPY", "New collations must not upgrade the original protocol")
    require(call(target)["status"] == "NOOP", "Active collation target must be idempotent")
    actual = spark.table(q)
    changed = actual.withColumn("__test_text", F.lower("__test_text"))
    try:
        _TableMigration.assert_data(actual, changed)
    except RuntimeError as error:
        require(str(error) == "Data verification failed", "Expected case-sensitive value mismatch")
    else:
        raise AssertionError("Collation must not conceal altered values")
    get_column(target, "__test_text")["collation"] = "UTF8_BINARY"
    original_execute = _TableMigration.execute_sql

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "COLUMN_COLLATION":
            raise RuntimeError("Injected failure after native collation ALTER")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require("original table restored" in error.result["message"], "Collation recovery failed")
            require(
                get_column(spec(), "__test_text")["collation"] == "UTF8_LCASE", "Original collation was not restored"
            )
            recovery = error.result
        else:
            raise AssertionError("Expected collation metadata failure")
    finally:
        _TableMigration.execute_sql = original_execute
    cleared = call(target)
    require(cleared["strategy"] == "METADATA", "Active collations must change through native metadata ALTER")
    require(call(target)["status"] == "NOOP", "Collation target must be idempotent")
    return {"set": result, "recovery": recovery, "clear": cleared}


@test("reserved_columns_with_incoming_key")
def test_reserved_key_dependencies():
    isolate_fixture()
    key = next(
        c["name"]
        for c in original["spec"]["columns"]
        if c["name"].lower().endswith("id") and not c["name"].startswith("__")
    )
    target = prepare([("key", "INT", "1"), ("primary", "INT", "2")])
    target["constraints"].append({"name": "keyword_pk_" + test_id, "body": "PRIMARY KEY (" + _mi(key) + ")"})
    call(target)
    child = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_keyword_" + test_id])
    spark.sql(
        f"CREATE TABLE {child} (ref BIGINT, CONSTRAINT {_mi('keyword_fk_' + test_id)} "
        f"FOREIGN KEY(ref) REFERENCES {q} ({_mi(key)})) USING DELTA"
    ).collect()
    fixture_objects.append(("DEPENDENT_TABLE", child, baseline.state(child)["id"]))
    target["columns"] = [c for c in target["columns"] if c["name"] not in {"key", "primary"}]
    target["columns"].append(new_column("Added"))
    result = call(target)
    require(result["strategy"] == "METADATA", "SQL keywords must not count as key-column dependencies")
    require(
        not any(c["action"] == "DROP_CONSTRAINT" for c in result["changes"]),
        "Unrelated reserved columns must retain the key",
    )
    return result


@test("map_key_struct_collision")
def test_map_key_struct_collision():
    target = prepare(
        [
            (
                "__test_map",
                "MAP<STRUCT<a:INT,b:INT>,INT>",
                "map(named_struct('a',1,'b',1),10,named_struct('a',1,'b',2),20)",
            )
        ]
    )
    get_column(target, "__test_map")["type"] = "MAP<STRUCT<a:INT>,INT>"
    previous = spark.conf.get("spark.sql.mapKeyDedupPolicy")
    try:
        spark.conf.set("spark.sql.mapKeyDedupPolicy", "LAST_WIN")
        result = call(target)
        require(
            result["manual_migration_required"], "Map-key collisions must not depend on the Spark deduplication policy"
        )
        return result
    finally:
        spark.conf.set("spark.sql.mapKeyDedupPolicy", previous)


@test("void_without_widening")
def test_void_without_widening():
    isolate_fixture()
    spark.sql(f"ALTER TABLE {q} SET TBLPROPERTIES ('delta.enableTypeWidening'='false')").collect()
    target = prepare([("__test_void", "VOID", None)])
    get_column(target, "__test_void")["type"] = "STRING"
    result = call(target)
    require(result["strategy"] == "METADATA", "VOID widening must not require enableTypeWidening")
    return result


@test("comparison_exact")
def test_comparison_exact():
    target = prepare(
        [
            ("__test_precise", "TIMESTAMP", "TIMESTAMP '2020-01-02 03:04:05.000001'"),
            ("__test_map", "MAP<STRING,INT>", "map('a',1,'b',2)"),
        ]
    )
    target["columns"].append(new_column("Compared"))
    result = call(target)
    actual = spark.table(q)
    reordered = actual.withColumn("__test_map", F.map_from_entries(F.reverse(F.map_entries("__test_map"))))
    _TableMigration.assert_data(actual, reordered)
    changed = actual.withColumn("__test_precise", F.expr("__test_precise + INTERVAL 1 MICROSECOND"))
    try:
        _TableMigration.assert_data(actual, changed)
    except RuntimeError as error:
        require(str(error) == "Data verification failed", "Expected exact timestamp mismatch")
    else:
        raise AssertionError("Microsecond data loss was not detected")
    return result


@test("nested_ambiguous_alias")
def test_nested_conflict():
    target = prepare([("__test_nested", "STRUCT<a:INT,b:INT>", "named_struct('a',1,'b',2)")])
    get_column(target, "__test_nested")["type"] = "STRUCT<b:INT>"
    result = call(target, [{"name": "__test_nested.b", "refactorNames": ["__test_nested.a"]}])
    require(result["manual_migration_required"], "Nested alias conflicts must not discard values")
    return result


@test("parent_struct_rename")
def test_parent_struct_rename():
    target = prepare([("__test_old_parent", "STRUCT<a:INT>", "named_struct('a',1)")])
    get_column(target, "__test_old_parent").update(name="Parent", type="STRUCT<b:INT>")
    return call(
        target,
        [
            {"name": "Parent", "refactorNames": ["__test_old_parent"]},
            {"name": "Parent.b", "refactorNames": ["__test_old_parent.a"]},
        ],
    )


@test("foreign_candidate_retained")
def test_foreign_candidate():
    isolate_fixture()
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    original_execute = _TableMigration.execute_sql
    replaced = {}

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "COPY_DATA" and not replaced:
            spark.sql("DROP TABLE " + migration.candidate).collect()
            spark.sql("CREATE TABLE " + migration.candidate + " (foreign_value INT) USING DELTA").collect()
            replaced.update(name=migration.candidate, identity=baseline.state(migration.candidate)["id"])
            fixture_objects.append(("TABLE", replaced["name"], replaced["identity"]))
            raise RuntimeError("Injected replacement of an already observed candidate")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require("RECOVERY_REQUIRED" in str(error), "Unknown candidate requires explicit recovery")
            require(baseline.state(replaced["name"])["id"] == replaced["identity"], "Foreign candidate was deleted")
            return error.result
        raise AssertionError("Expected candidate replacement failure")
    finally:
        _TableMigration.execute_sql = original_execute


@test("feature_failure_recovery")
def test_feature_failure():
    isolate_fixture()
    before = baseline.state()
    target = spec()
    target["columns"].append(new_column("__test_default", "INT", default="7"))
    original_execute = _TableMigration.execute_sql
    injected = [False]

    def execute(migration, sql, action, **info):
        original_execute(migration, sql, action, **info)
        if action == "ACTIVATE_TARGET" and not injected[0]:
            injected[0] = True
            raise RuntimeError("Injected failure after activating a new protocol feature")

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require(injected[0], "Feature upgrade must use a candidate before modifying the source")
            require("RECOVERY_REQUIRED" not in str(error), "Feature upgrade must recover automatically")
            require(baseline.state()["spec"]["features"] == before["spec"]["features"], "Original protocol changed")
            return error.result
        raise AssertionError("Expected activation failure")
    finally:
        _TableMigration.execute_sql = original_execute


@test("protected_hidden_rows")
def test_protected_hidden_rows():
    isolate_fixture()
    prepare([("__test_policy", "BOOLEAN", "false")])
    function = ".".join(_mi(p) for p in baseline.parts[:-1] + ["migration_test_hidden_" + test_id])
    spark.sql(f"CREATE FUNCTION {function}(v BOOLEAN) RETURNS BOOLEAN RETURN v").collect()
    fixture_objects.append(("FUNCTION", function, function_fingerprint(function)))
    spark.sql(f"ALTER TABLE {q} SET ROW FILTER {function} ON (__test_policy)").collect()
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    result = call(target)
    require(result["manual_migration_required"], "Invisible source rows must not be treated as an empty source")
    require(baseline.state(result["archive_table"])["spec"]["row_filter"], "Archive protection must remain intact")
    archive = ".".join(_mi(part) for part in result["archive_table"].split("."))
    spark.sql("ALTER TABLE " + archive + " DROP ROW FILTER").collect()
    assert_rows(spark.table(backup).withColumn("__test_policy", F.lit(False)), spark.table(archive))
    return result


@test("lost_candidate_response")
def test_lost_candidate_response():
    target = spec()
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    original_execute = _TableMigration.execute_sql
    candidate = {}

    def execute(migration, sql, action, **info):
        if action == "CREATE_CANDIDATE" and not candidate:
            migration.spark.sql(sql).collect()
            candidate.update(name=migration.candidate, identity=baseline.state(migration.candidate)["id"])
            fixture_objects.append(("TABLE", candidate["name"], candidate["identity"]))
            raise TimeoutError("Response lost after candidate creation, before observing its identity")
        return original_execute(migration, sql, action, **info)

    _TableMigration.execute_sql = execute
    try:
        try:
            call(target)
        except MigrationFailed as error:
            require("RECOVERY_REQUIRED" not in str(error), "Original should still be recoverable")
            require(
                error.result.get("recovery", {}).get("unconfirmed_candidate") == candidate["name"],
                "Missing unconfirmed candidate",
            )
            require(
                baseline.state(candidate["name"])["id"] == candidate["identity"], "Unconfirmed object must be retained"
            )
            return error.result
        raise AssertionError("Expected lost candidate response")
    finally:
        _TableMigration.execute_sql = original_execute


@test("constraint_names")
def test_constraint_names():
    isolate_fixture()
    target = prepare([("__test_key", "BIGINT", sample_key())])
    get_column(target, "__test_key")["nullable"] = False
    target["constraints"].append({"name": "original_pk_" + test_id, "body": "PRIMARY KEY (__test_key)"})
    first = call(target)
    target["constraints"][-1]["name"] = "target_pk_" + test_id
    renamed = call(target)
    require(call(target)["status"] == "NOOP", "Constraint-name target must be idempotent")
    target["columns"].append(new_column("__test_identity", "BIGINT", False, identity="GENERATED ALWAYS AS IDENTITY"))
    try:
        call(target)
    except MigrationFailed as error:
        require("ARCHIVE_CONSTRAINT_NAME_CONFLICT" in str(error), "Expected schema-wide name conflict")
        require(not error.result["changes"], "Archive names must be checked before mutations")
    else:
        raise AssertionError("Original constraint names must stay unchanged on the archive")
    target["constraints"][-1]["name"] = "rebuilt_pk_" + test_id
    rebuilt = call(target)
    require(rebuilt["strategy"] == "ARCHIVE_AND_COPY", "Constraint names must survive an archive rebuild")
    return {"add": first, "rename": renamed, "rebuild": rebuilt}


try:
    for name, function in tests:
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in selection):
            continue
        entry = {"name": name}
        baseline_verified = False
        try:
            before_case = baseline.state()
            require(
                before_case["id"] == original["id"] and before_case["version"] == restored_version[0],
                "Original table changed between scenarios",
            )
            require(baseline.catalog_metadata() == original_metadata, "Original metadata changed between scenarios")
            baseline_verified = True
            entry["result"] = function()
            entry["passed"] = True
            entry["status"] = "PASSED"
        except Exception as error:
            entry.update(passed=False, status="FAILED", error=str(error), traceback=traceback.format_exc())
            if hasattr(error, "result"):
                entry["result"] = error.result
        finally:
            try:
                require(
                    baseline_verified,
                    "Baseline changed before scenario; retain backups without overwriting foreign changes",
                )
                for kind, object_name, identity in list(fixture_objects):
                    if kind == "DEPENDENT_TABLE" and spark.catalog.tableExists(object_name):
                        require(baseline.state(object_name)["id"] == identity, "Dependent fixture identity changed")
                        spark.sql("DROP TABLE " + object_name).collect()
                        fixture_objects.remove((kind, object_name, identity))
                restore_original()
                entry["restored"] = True
                for kind, object_name, identity in sorted(fixture_objects, key=lambda item: item[0] == "FUNCTION"):
                    if kind == "FUNCTION":
                        require(function_fingerprint(object_name) == identity, "Function fixture identity changed")
                        spark.sql("DROP FUNCTION " + object_name).collect()
                    elif spark.catalog.tableExists(object_name):
                        require(baseline.state(object_name)["id"] == identity, "Fixture identity changed")
                        spark.sql("DROP TABLE " + object_name).collect()
                    fixture_objects.remove((kind, object_name, identity))
            except Exception as error:
                entry.update(restored=False, recovery_error=str(error))
                report["tests"].append(entry)
                print("MIGRATION_TEST_RECOVERY_REQUIRED " + json.dumps(report, default=str))
                raise
        report["tests"].append(entry)
        print("MIGRATION_TEST_CASE " + json.dumps(entry, default=str))
    require(report["tests"], "No scenarios selected")
    restore_original()
    report["original_restored"] = True
    if all(item["passed"] for item in report["tests"]):
        report["cleaned_prior_backups"] = []
        for previous in cleanup_backups:
            previous_backup = previous["table"]
            prefix = baseline.name + "__test_backup_"
            require(
                previous_backup.startswith(prefix) and re.fullmatch("[0-9a-f]{12}", previous_backup[len(prefix) :]),
                "Cleanup is restricted to explicitly selected backups of this sample table",
            )
            if not spark.catalog.tableExists(previous_backup):
                continue
            require(baseline.state(previous_backup)["id"] == previous["id"], "Backup identity changed; retain object")
            history = spark.sql("DESCRIBE HISTORY " + previous_backup).collect()
            require(
                any(
                    row["operation"] == "CLONE"
                    and row["operationParameters"].get("source", "").replace("`", "") == baseline.name
                    for row in history
                ),
                "Backup must have this table's clone provenance",
            )
            assert_rows(spark.table(q), spark.table(previous_backup))
            spark.sql("DROP TABLE " + previous_backup).collect()
            report["cleaned_prior_backups"].append(previous_backup)
        require(baseline.state(backup)["id"] == report["backup_id"], "Current backup identity changed")
        spark.sql("DROP TABLE " + backup).collect()
        report["backup_removed"] = True
finally:
    print("MIGRATION_TEST_REPORT " + json.dumps(report, default=str))

require(
    all(item["passed"] and item["restored"] for item in report["tests"]),
    "Migration acceptance failed; inspect MIGRATION_TEST_REPORT",
)
dbutils.notebook.exit(json.dumps(report, default=str))
