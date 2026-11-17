# Databricks notebook source
"""Opt-in classic-compute acceptance against a disposable generated solution.

The caller supplies an isolated catalog and uploaded workspace root. Only
synthetic Delta tables are read or written. No live source connection is used.
"""

import json
import os
from copy import deepcopy
import sys
from datetime import datetime, timezone
from pathlib import Path

for key in ("catalog_name", "owner", "workspace_root"):
    dbutils.widgets.text(key, "")
catalog = dbutils.widgets.get("catalog_name")
root = Path(dbutils.widgets.get("workspace_root"))
assert catalog.startswith("dm8_quality_test_"), "Use an isolated quality test catalog"
sys.path.insert(0, str(root / "utils"))
import QualityFramework as quality  # noqa: E402

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.core")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.acceptance")
input_table = f"{catalog}.acceptance.input"
schema = "Id INT, Amount DOUBLE, Email STRING, Updated TIMESTAMP"
now = datetime.now(timezone.utc)
spark.createDataFrame(
    [(1, 10.0, "a@example.test", now), (2, -1.0, None, now), (None, 25.0, "b@example.test", now), (4, 5.0, None, now)],
    schema,
).write.mode("overwrite").saveAsTable(input_table)
params = {
    "catalog_name": catalog,
    "owner": dbutils.widgets.get("owner"),
    "job_run_id": "acceptance-main",
    "quality_input_table": input_table,
}
notebooks = root / "output/databricks/notebooks/020-Core"
ddl = str(notebooks / "ddl/MasterData/Customer/QualityProbe")
dml = str(notebooks / "dml/MasterData/Customer/QualityProbe")
monitor = str(notebooks / "quality/MasterData/Customer/QualityProbe")
manifest = root / "output/databricks/quality/9001/manifest.json"
spec = quality.load_checks(manifest)
target = catalog + "." + spec["target"]
for table in (target, target + "_quarantine", catalog + ".quality.dqx_metrics"):
    spark.sql(f"DROP TABLE IF EXISTS {table}")
print("Running generated DDL:", ddl)
dbutils.notebook.run(ddl, 180, params)
try:
    dbutils.notebook.run(dml, 180, params)
    raise AssertionError("Expected threshold failure after the valid target write")
except AssertionError:
    raise
except Exception:
    # dbutils.run returns a generic WorkflowException for child failures.
    # Assert the committed target, quarantine and metrics below instead.
    pass
assert spark.table(target).count() == 2
assert spark.table(target + "_quarantine").count() == 2
assert {r.Id for r in spark.table(target).select("Id").collect()} == {1, 4}
assert spark.table(f"{catalog}.quality.dqx_metrics").count() == 3
version = spark.sql(f"DESCRIBE HISTORY {target}").first().version
dbutils.notebook.run(monitor, 180, params)
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version
metrics = {r.check_id: r.asDict() for r in spark.table(f"{catalog}.quality.dqx_metrics").collect()}
assert metrics["email_completeness"]["status"] == "FAILED"
assert metrics["email_completeness"]["measured_value"] == 0.5
assert metrics["updated_fresh"]["status"] == "PASSED"
assert metrics["row_count"]["measured_value"] == 2
# Replaying monitoring uses the same audit identity and must not duplicate metrics.
dbutils.notebook.run(monitor, 180, params)
assert spark.table(f"{catalog}.quality.dqx_metrics").count() == 6
# All-invalid overwrite must preserve the existing target.
spark.createDataFrame([(None, -10.0, None, now)], schema).write.mode("overwrite").saveAsTable(input_table)
try:
    dbutils.notebook.run(dml, 180, dict(params, job_run_id="all-invalid"))
    raise AssertionError("Expected all-invalid threshold failure")
except AssertionError:
    raise
except Exception:
    # dbutils.run returns a generic WorkflowException for child failures.
    # Assert the committed target, quarantine and metrics below instead.
    pass
assert spark.table(target).count() == 2
# Warning-only rows remain valid and do not enter quarantine.
spark.createDataFrame([(7, 5.0, None, now)], schema).write.mode("overwrite").saveAsTable(input_table)
dbutils.notebook.run(dml, 180, dict(params, job_run_id="warning-only"))
assert spark.table(target).count() == 1
assert spark.table(target).first().Id == 7
assert spark.table(target + "_quarantine").count() == 3
# Empty-input rule metrics and empty-table aggregate semantics.
ctx = quality.context(spark, target, spec, "empty-input")
result = quality.enforce(spark.createDataFrame([], schema), spec, ctx)
assert result["total"] == 0
quality.finish_enforcement(result, ctx)
assert all(m["status"] == "NO_DATA" for m in result["metrics"])
spark.sql(f"TRUNCATE TABLE {target}")
empty_metrics = quality.monitor(spec, quality.context(spark, target, spec, "empty-target"))
assert {m["check_id"]: m["status"] for m in empty_metrics} == {
    "email_completeness": "NO_DATA",
    "updated_fresh": "FAILED",
    "row_count": "FAILED",
}
# Invalid SQL is a technical error, including on empty targets/inputs. DQX may
# otherwise report these checks as skipped instead of raising on some runtimes.
metric_count = spark.table(f"{catalog}.quality.dqx_metrics").count()
version = spark.sql(f"DESCRIBE HISTORY {target}").first().version
for expression in ("NOT VALID SQL (", "missing_quality_column > 0", "1"):
    bad = deepcopy(spec)
    bad["checks"]["monitoring_summary"][0]["check"]["arguments"]["expression"] = expression
    try:
        quality.monitor(bad, quality.context(spark, target, bad, "technical-error"))
        raise AssertionError("Technical SQL failure was hidden")
    except AssertionError:
        raise
    except Exception:
        pass
    bad = deepcopy(spec)
    bad["checks"]["enforcement"][0]["check"] = {
        "function": "sql_expression", "arguments": {"expression": expression}}
    try:
        quality.enforce(spark.createDataFrame([], schema), bad, quality.context(spark, target, bad, "invalid-input"))
        raise AssertionError("Technical enforcement failure was hidden on empty input")
    except AssertionError:
        raise
    except Exception:
        pass
assert spark.table(f"{catalog}.quality.dqx_metrics").count() == metric_count
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version
print("QUALITY_ACCEPTANCE_PASSED")
dbutils.notebook.exit(
    json.dumps(
        {
            "status": "PASSED",
            "catalog": catalog,
            "runtime": os.environ.get("DATABRICKS_RUNTIME_VERSION"),
            "target": target,
            "checks": [
                "generated-ddl",
                "generated-dml",
                "threshold-after-write",
                "error-quarantine",
                "warning-preserved",
                "monitoring-read-only",
                "audit-idempotence",
                "all-invalid-overwrite",
                "empty-input",
                "empty-aggregate",
                "technical-failure",
            ],
        }
    )
)
