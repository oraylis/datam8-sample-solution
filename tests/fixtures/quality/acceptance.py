# Databricks notebook source
"""Opt-in classic-compute acceptance against a disposable generated solution.

The caller supplies an isolated catalog and uploaded workspace root. Only
synthetic Delta tables are read or written. No live source connection is used.
"""

import json
import os
import yaml
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
# Exact threshold: one row violates two rules, but counts as one error row (25%).
spark.createDataFrame(
    [
        (10, 1.0, "a@example.test", now),
        (11, 2.0, "b@example.test", now),
        (12, 3.0, "c@example.test", now),
        (None, -1.0, "d@example.test", now),
    ],
    schema,
).write.mode("overwrite").saveAsTable(input_table)
dbutils.notebook.run(dml, 180, dict(params, job_run_id="threshold-boundary"))
assert spark.table(target).count() == 3
assert spark.table(target + "_quarantine").count() == 4
# Run the actual generated DML for empty input, rather than calling a runtime orchestrator.
spark.createDataFrame([], schema).write.mode("overwrite").saveAsTable(input_table)
dbutils.notebook.run(dml, 180, dict(params, job_run_id="empty-input"))
empty_metrics = spark.table(f"{catalog}.quality.dqx_metrics").where("run_id = 'empty-input'").collect()
assert len(empty_metrics) == 3 and all(m.status == "NO_DATA" for m in empty_metrics)
assert spark.table(target).count() == 3
assert spark.table(target + "_quarantine").count() == 4
spark.sql(f"TRUNCATE TABLE {target}")
dbutils.notebook.run(monitor, 180, dict(params, job_run_id="empty-target"))
empty_metrics = spark.table(f"{catalog}.quality.dqx_metrics").where("run_id = 'empty-target'").collect()
assert {m.check_id: m.status for m in empty_metrics} == {
    "email_completeness": "NO_DATA",
    "updated_fresh": "FAILED",
    "row_count": "FAILED",
}
# Invalid definitions are injected only into the disposable uploaded native YAML.
# Always restore the artifact, and execute generated notebooks to exercise real preflight.
metric_count = spark.table(f"{catalog}.quality.dqx_metrics").count()
version = spark.sql(f"DESCRIBE HISTORY {target}").first().version
for expression in ("NOT VALID SQL (", "missing_quality_column > 0", "1"):
    for group, notebook in [("monitoring_summary", monitor), ("enforcement", dml)]:
        rules_path = manifest.parent / spec["files"][group]
        original = rules_path.read_text()
        try:
            checks = yaml.safe_load(original)
            checks[0]["check"] = {"function": "sql_expression", "arguments": {"expression": expression}}
            rules_path.write_text(yaml.safe_dump(checks, sort_keys=False))
            try:
                dbutils.notebook.run(notebook, 180, dict(params, job_run_id="technical-error"))
                raise AssertionError("Technical SQL failure was hidden")
            except AssertionError:
                raise
            except Exception:
                pass
        finally:
            rules_path.write_text(original)
assert spark.table(f"{catalog}.quality.dqx_metrics").count() == metric_count
assert spark.sql(f"DESCRIBE HISTORY {target}").first().version == version
# Monitoring-only variants cover row checks, aggregates and both groups together.
monitoring_results = []
for name, entity_id in [("QualityMonitorProbe", 9005), ("QualityRowsProbe", 9006), ("QualitySummaryProbe", 9007)]:
    other = quality.load_checks(root / f"output/databricks/quality/{entity_id}/manifest.json")
    other_target = catalog + "." + other["target"]
    for table in (other_target, other_target + "_quarantine"):
        spark.sql(f"DROP TABLE IF EXISTS {table}")
    now = datetime.now(timezone.utc)
    spark.createDataFrame(
        [
            (1, 10.0, "a@example.test", now),
            (2, -1.0, None, now),
            (None, 25.0, "b@example.test", now),
            (4, 5.0, None, now),
        ],
        schema,
    ).write.mode("overwrite").saveAsTable(input_table)
    other_params = dict(params, job_run_id=name)
    dbutils.notebook.run(str(notebooks / f"ddl/MasterData/Customer/{name}"), 180, other_params)
    dbutils.notebook.run(str(notebooks / f"dml/MasterData/Customer/{name}"), 180, other_params)
    assert spark.table(other_target).count() == 4
    assert spark.table(other_target + "_quarantine").count() == 0
    before = spark.sql(f"DESCRIBE HISTORY {other_target}").first().version
    mon = str(notebooks / f"quality/MasterData/Customer/{name}")
    dbutils.notebook.run(mon, 180, other_params)
    metrics = (
        spark.table(f"{catalog}.quality.dqx_metrics").where(f"entity_id = {entity_id} AND run_id = '{name}'").collect()
    )
    expected_status = {
        "id_required": "FAILED",
        "amount_range": "FAILED",
        "email_present": "FAILED",
        "email_completeness": "FAILED",
        "updated_fresh": "PASSED",
        "row_count": "PASSED",
    }
    assert len(metrics) == len(other["quality"]["checks"])
    assert all(m.status == expected_status[m.check_id] for m in metrics)
    metric_count = spark.table(f"{catalog}.quality.dqx_metrics").count()
    dbutils.notebook.run(mon, 180, other_params)
    assert spark.table(f"{catalog}.quality.dqx_metrics").count() == metric_count
    assert spark.sql(f"DESCRIBE HISTORY {other_target}").first().version == before
    # Future timestamps fail freshness, while monitoring continues successfully.
    if entity_id == 9007:
        from datetime import timedelta

        spark.createDataFrame([(9, 1.0, "future@example.test", now + timedelta(days=1))], schema).write.mode(
            "overwrite"
        ).saveAsTable(input_table)
        future_params = dict(params, job_run_id="future-timestamp")
        dbutils.notebook.run(str(notebooks / f"dml/MasterData/Customer/{name}"), 180, future_params)
        dbutils.notebook.run(mon, 180, future_params)
        assert (
            spark.table(f"{catalog}.quality.dqx_metrics")
            .where(f"entity_id = {entity_id} AND run_id = 'future-timestamp' AND check_id = 'updated_fresh'")
            .first()
            .status
            == "FAILED"
        )
    monitoring_results.append(name)
print("QUALITY_ACCEPTANCE_PASSED")
dbutils.notebook.exit(
    json.dumps(
        {
            "status": "PASSED",
            "catalog": catalog,
            "runtime": os.environ.get("DATABRICKS_RUNTIME_VERSION"),
            "target": target,
            "monitoring_variants": monitoring_results,
            "checks": [
                "generated-ddl",
                "generated-dml",
                "threshold-after-write",
                "threshold-boundary-distinct-error-rows",
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
