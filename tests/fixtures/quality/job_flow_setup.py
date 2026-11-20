# Databricks notebook source
"""Synthetic input preparation for opt-in generated job dependency acceptance."""

from datetime import datetime, timezone
from pathlib import Path

for key in ("catalog_name", "owner", "workspace_root", "scenario"):
    dbutils.widgets.text(key, "")
catalog = dbutils.widgets.get("catalog_name")
assert catalog.startswith("dm8_quality_test_")
scenario = dbutils.widgets.get("scenario")
if scenario == "reference_failure":
    raise RuntimeError("Intentional technical reference-load failure for dependency acceptance")
if scenario == "repair_technical":
    # A new attempt fails before quality evaluation; an earlier gate signal must not authorize monitoring.
    spark.createDataFrame([(2,)], "Id INT").write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        catalog + ".acceptance.job_flow_input"
    )
    dbutils.notebook.exit("PREPARED_REPAIR_TECHNICAL_FAILURE")
now = datetime.now(timezone.utc)
schema = "Id INT, Amount DOUBLE, Email STRING, Updated TIMESTAMP"
rows = {
    "gate": [(1, 10.0, "a", now), (1, 20.0, "b", now), (2, 5.0, "c", now)],
    "technical": [],
    "empty": [],
    "all_invalid": [(1, 10.0, "a", now), (1, 20.0, "b", now)],
    "reference": [(2, 5.0, "c", now)],
}[scenario]
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.acceptance")
spark.createDataFrame(rows, schema).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    catalog + ".acceptance.job_flow_input"
)
assert spark.table(catalog + ".acceptance.job_flow_input").columns == ["Id", "Amount", "Email", "Updated"]
if scenario == "gate":
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.core")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.quality")
    root = Path(dbutils.widgets.get("workspace_root"))
    for phase in ("ddl", "dml"):
        dbutils.notebook.run(
            str(root / f"output/databricks/notebooks/020-Core/{phase}/MasterData/Customer/QualityReferenceProbe"),
            180,
            {"catalog_name": catalog, "owner": dbutils.widgets.get("owner")},
        )
    dbutils.notebook.run(
        str(root / "output/databricks/notebooks/020-Core/ddl/MasterData/Customer/QualityNativeProbe"),
        180,
        {"catalog_name": catalog, "owner": dbutils.widgets.get("owner")},
    )
dbutils.notebook.exit("PREPARED_" + scenario)
