# Databricks notebook source
"""Opt-in acceptance of generated SQL expressions, windows and entity references."""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

for key in ("catalog_name", "owner", "workspace_root"):
    dbutils.widgets.text(key, "")
catalog = dbutils.widgets.get("catalog_name")
assert catalog.startswith("dm8_quality_test_"), "Use an isolated quality test catalog"
root = Path(dbutils.widgets.get("workspace_root"))
sys.path.insert(0, str(root / "utils"))
import QualityFramework as quality  # noqa: E402

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.acceptance")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.quality")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.core")
reference_params = {"catalog_name": catalog, "owner": dbutils.widgets.get("owner")}
for phase in ("ddl", "dml"):
    dbutils.notebook.run(
        str(root / f"output/databricks/notebooks/020-Core/{phase}/MasterData/Customer/QualityReferenceProbe"),
        180,
        reference_params,
    )
input_table = catalog + ".acceptance.native_input"
schema = "Id INT, Amount DOUBLE, Email STRING, Updated TIMESTAMP"
now = datetime.now(timezone.utc)
run_id = "native-" + uuid.uuid4().hex
params = {
    "catalog_name": catalog,
    "owner": dbutils.widgets.get("owner"),
    "quality_input_table": input_table,
    "job_run_id": run_id,
}
notebooks = root / "output/databricks/notebooks/020-Core"
paths = {
    phase: str(notebooks / f"{phase}/MasterData/Customer/QualityNativeProbe") for phase in ("ddl", "dml", "quality")
}
manifest = root / "output/databricks/quality/9011/manifest.json"
spec = quality.load_checks(manifest)
target = catalog + "." + spec["target"]
for table in (target, target + "_quarantine"):
    spark.sql(f"DROP TABLE IF EXISTS {table}")
dbutils.notebook.run(paths["ddl"], 180, params)
assert all(field.nullable for field in spark.table(target + "_quarantine").schema)

spark.createDataFrame(
    [
        (1, 10.0, "a@example.test", now),
        (2, -1.0, None, now),
        (None, 25.0, "b@example.test", now),
        (4, 5.0, "", now),
    ],
    schema,
).write.mode("overwrite").saveAsTable(input_table)
dbutils.notebook.run(paths["dml"], 180, params)
assert {r.Id for r in spark.table(target).select("Id").collect()} == {1, 2, 4}
assert spark.table(target + "_quarantine").count() == 1
version = spark.sql(f"DESCRIBE HISTORY {target}").first().version
dbutils.notebook.run(paths["quality"], 180, params)


def metrics(audit_run):
    return {
        r.check_id: r.asDict()
        for r in spark.table(catalog + ".quality.dqx_metrics")
        .where(f"entity_id = 9011 AND run_id = '{audit_run}'")
        .collect()
    }


main = metrics(run_id)
assert len(main) == 6, main
assert main["native_required"]["failed_rows"] == 1  # one rule expands across two columns
assert main["native_email"]["failed_rows"] == 2 and main["native_email"]["severity"] == "warning"
assert main["native_unique_target"]["status"] == "PASSED"
assert main["native_reference"]["status"] == "FAILED"
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version
dbutils.notebook.run(paths["quality"], 180, params)
assert len(metrics(run_id)) == 6  # replaying the same audit identity is idempotent

# Dataset-level enforcement uses the same metadata API and routing as row checks.
spark.createDataFrame(
    [
        (1, 10.0, "a@example.test", now),
        (1, 20.0, "b@example.test", now),
        (2, 5.0, "c@example.test", now),
    ],
    schema,
).write.mode("overwrite").saveAsTable(input_table)
try:
    dbutils.notebook.run(paths["dml"], 180, dict(params, job_run_id=run_id + "-duplicates"))
    raise AssertionError("Expected threshold failure after dataset-level enforcement")
except AssertionError:
    raise
except Exception:
    pass
assert spark.table(target).count() == 1 and spark.table(target).first().Id == 2
assert metrics(run_id + "-duplicates")["native_unique_input"]["failed_rows"] == 2
assert spark.table(target + "_quarantine").count() == 3

spark.createDataFrame([], schema).write.mode("overwrite").saveAsTable(input_table)
dbutils.notebook.run(paths["dml"], 180, dict(params, job_run_id=run_id + "-empty"))
assert spark.table(target).count() == 1
assert all(m["status"] == "NO_DATA" for m in metrics(run_id + "-empty").values())

# Native DQX's own parser/resolver must reject technical errors before any write,
# even when the source is empty. The temporary YAML is always restored.
rules_path = manifest.parent / spec["files"]["enforcement"]
original = rules_path.read_text()
count = spark.table(catalog + ".quality.dqx_metrics").count()
version = spark.sql(f"DESCRIBE HISTORY {target}").first().version
invalid = [
    {"check": {"function": "sql_expression", "arguments": {"expression": "missing_column IS NOT NULL"}}},
    {"check": {"function": "sql_expression", "arguments": {"expression": "1"}}},
    {"check": {"function": "sql_expression", "arguments": {"expression": "NOT VALID SQL ("}}},
]
try:
    for definition in invalid:
        rules_path.write_text(yaml.safe_dump([{"name": "invalid_native", **definition}], sort_keys=False))
        try:
            dbutils.notebook.run(paths["dml"], 180, dict(params, job_run_id=run_id + "-invalid"))
            raise AssertionError("Invalid native check was silently ignored")
        except AssertionError:
            raise
        except Exception:
            pass
finally:
    rules_path.write_text(original)
assert spark.table(catalog + ".quality.dqx_metrics").count() == count
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version

# Native column normalization accepts names with spaces on empty and nonempty data.
from databricks.labs.dqx.engine import DQEngineCore  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402

spaced_rule = [
    {
        "name": "spaced",
        "check": {"function": "sql_expression", "arguments": {"expression": "`Customer Name` IS NOT NULL"}},
    }
]
engine = DQEngineCore(WorkspaceClient(), spark)
for data in ([], [("example",)]):
    df = spark.createDataFrame(data, "`Customer Name` STRING")
    quality.validate_check_inputs(df, spaced_rule)
    checked = engine.apply_checks_by_metadata(df, spaced_rule)
    assert checked.where("size(_errors) > 0").count() == 0

# Fixed aggregate result schema and values fail technically before metric persistence.
invalid_results = [
    spark.createDataFrame([], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(1, 1.0), (2, 2.0)], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(1.0, 1.0)], "checked_rows DOUBLE, measured_value DOUBLE"),
    spark.createDataFrame([(None, 1.0)], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(-1, 1.0)], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(1, "value")], "checked_rows LONG, measured_value STRING"),
    spark.createDataFrame([(1, float("nan"))], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(1, float("inf"))], "checked_rows LONG, measured_value DOUBLE"),
    spark.createDataFrame([(1, 1.0, 1)], "checked_rows LONG, measured_value DOUBLE, extra INT"),
    spark.createDataFrame([(1, 1.0)], "wrong LONG, measured_value DOUBLE"),
    spark.sql("SELECT CAST('9223372036854775808' AS DECIMAL(20,0)) AS checked_rows, 1.0 AS measured_value"),
]
for invalid_result in invalid_results:
    try:
        quality.validate_aggregate_result(invalid_result)
        raise AssertionError("Invalid aggregate result was accepted")
    except ValueError:
        pass
assert quality.validate_aggregate_result(
    spark.createDataFrame([(0, None)], "checked_rows LONG, measured_value DOUBLE")
) == {"checked_rows": 0, "measured_value": None}
# The original expression must remain Boolean, including on empty inputs.
for expression in ("1", "COUNT(*) OVER (PARTITION BY Id)"):
    try:
        quality.validate_boolean_expression(spark.createDataFrame([], schema), expression)
        raise AssertionError("A non-Boolean original expression was accepted")
    except ValueError:
        pass
assert spark.table(catalog + ".quality.dqx_metrics").count() == count
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version

dbutils.notebook.exit(
    json.dumps(
        {
            "status": "PASSED",
            "run_id": run_id,
            "checks": list(main),
            "sql_metadata": True,
            "combined_required_expression": True,
            "filtered_list": True,
            "dataset_enforcement": True,
            "reference_monitoring": True,
            "invalid_aggregate_results": len(invalid_results),
            "original_boolean_validation": True,
            "warnings_preserved": True,
            "empty_input": True,
            "technical_failures": len(invalid),
            "monitoring_readonly": True,
            "replay_idempotent": True,
        }
    )
)
