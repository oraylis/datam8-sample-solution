# Databricks notebook source
"""Verify metrics from real generated load/monitor tasks, including intentional failures."""

import json

for key in ("catalog_name", "job_run_id"):
    dbutils.widgets.text(key, "")
catalog = dbutils.widgets.get("catalog_name")
assert catalog.startswith("dm8_quality_test_")
run_id = dbutils.widgets.get("job_run_id")
dbutils.widgets.text("expected_target_version", "")
results = {}
for scenario, enforcement, monitoring in [
    ("gate", 4, 2),
    ("technical", 0, 0),
    ("empty", 4, 2),
    ("all_invalid", 4, 0),
    ("reference", 4, 0),
]:
    rows = (
        spark.table(catalog + ".quality.dqx_metrics")
        .where(f"entity_id = 9011 AND run_id = '{run_id}:{scenario}'")
        .collect()
    )
    counts = {mode: sum(r.execution == mode for r in rows) for mode in ("enforcement", "monitoring")}
    assert counts == {"enforcement": enforcement, "monitoring": monitoring}, (scenario, counts)
    if scenario == "empty":
        assert all(r.status == "NO_DATA" for r in rows if r.execution == "enforcement")
    results[scenario] = counts
target = spark.table(catalog + ".core.MasterData_Customer_QualityNativeProbe")
assert target.count() == 1 and target.first().Id == 2
version = spark.sql(f"DESCRIBE HISTORY `{catalog}`.core.MasterData_Customer_QualityNativeProbe").first().version
if dbutils.widgets.get("expected_target_version"):
    assert version == int(dbutils.widgets.get("expected_target_version"))
dbutils.notebook.exit(
    json.dumps({"status": "PASSED", "job_run_id": run_id, "scenarios": results, "target_version": version})
)
