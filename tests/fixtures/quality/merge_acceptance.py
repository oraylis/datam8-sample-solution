# Databricks notebook source
"""Opt-in append/SCD acceptance for variants of the synthetic QualityProbe.

Generate QualityAppendProbe (9002, append), QualityMergeProbe (9003, merge),
and QualityHistoryProbe (9004, merge, Amount.history=SCD2) by copying the base
fixture on a disposable solution. Keep the shared QualityProbe.py function.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

for key in ("catalog_name", "owner", "workspace_root"):
    dbutils.widgets.text(key, "")
catalog = dbutils.widgets.get("catalog_name")
assert catalog.startswith("dm8_quality_test_")
root = Path(dbutils.widgets.get("workspace_root"))
input_table = catalog + ".acceptance.input"
params = {"catalog_name": catalog, "owner": dbutils.widgets.get("owner"), "quality_input_table": input_table}
results = []
for name, entity_id, expected in [
    ("QualityAppendProbe", 9002, 2),
    ("QualityMergeProbe", 9003, 1),
    ("QualityHistoryProbe", 9004, 2),
]:
    spec = json.loads((root / f"output/databricks/quality/{entity_id}/manifest.json").read_text())
    target = catalog + "." + spec["target"]
    for table in (target, target + "_quarantine"):
        spark.sql(f"DROP TABLE IF EXISTS {table}")
    notebooks = root / "output/databricks/notebooks/020-Core"
    dbutils.notebook.run(str(notebooks / f"ddl/MasterData/Customer/{name}"), 180, params)
    quarantine_schema = spark.table(target + "_quarantine").schema
    assert all(field.nullable for field in quarantine_schema)
    assert all(not any(key.startswith("delta.identity") for key in field.metadata) for field in quarantine_schema)
    for step, amount in enumerate((10.0, 20.0)):
        spark.createDataFrame(
            [(1, amount, "a@example.test", datetime.now(timezone.utc))],
            "Id INT, Amount DOUBLE, Email STRING, Updated TIMESTAMP",
        ).write.mode("overwrite").saveAsTable(input_table)
        dbutils.notebook.run(
            str(notebooks / f"dml/MasterData/Customer/{name}"),
            180,
            dict(params, job_run_id=f"{name}-{step}"),
        )
    rows = spark.table(target)
    assert rows.count() == expected, name
    if name == "QualityMergeProbe":
        assert rows.first().Amount == 20.0
    elif name == "QualityHistoryProbe":
        current = rows.where("__IsCurrent = true")
        assert current.count() == 1
        assert current.first().Amount == 20.0
        assert rows.where("__IsCurrent = false").first().Amount == 10.0
    assert spark.table(target + "_quarantine").count() == 0
    results.append({"entity": name, "rows": expected, "status": "PASSED"})
dbutils.notebook.exit(json.dumps({"status": "PASSED", "results": results}))
