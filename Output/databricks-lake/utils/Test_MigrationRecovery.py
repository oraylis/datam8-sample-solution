# Databricks notebook source
# MAGIC %md
# MAGIC # Restore a verified migration-test baseline in Dev
# MAGIC Uses clone provenance and the original managed registration, without log tables.

# COMMAND ----------
# MAGIC %run ./MigrationFramework

# COMMAND ----------
# ruff: noqa: F821
import json

dbutils.widgets.text("recovery_input", "{}")
payload = json.loads(dbutils.widgets.get("recovery_input"))
payload["original_metadata"]["grants"].sort(
    key=lambda grant: tuple((key, str(value)) for key, value in sorted(grant.items()))
)
assert "7405619058873076" in spark.conf.get("spark.databricks.workspaceUrl")
assert spark.sql("SELECT current_user()").first()[0] == "e2d1a9de-1e86-45bf-91c7-675f7e493425"
name = payload["table"]
parts = name.split(".")
assert parts[:2] == ["dm8_sample_dev_lake", "stage"] and len(parts) == 3
backup = payload["backup"]
assert backup.replace("`", "").startswith(name + "__test_backup_")
q = ".".join(_mi(p) for p in parts)
catalog = Catalog(parts[0])
catalog.schema = parts[1]
helper = _TableMigration.__new__(_TableMigration)
helper.spark, helper.parts, helper.name, helper.qualified = spark, parts, name, q
state = helper.state()
history = spark.sql("DESCRIBE HISTORY " + backup).collect()
clone = next(row for row in history if row["operation"] == "CLONE")
parameters = clone["operationParameters"]
print(
    "RECOVERY_INSPECT "
    + json.dumps(
        {
            "current": {k: state[k] for k in ("id", "delta_id", "identity_location", "version")},
            "clone_parameters": parameters,
            "backup": backup,
        },
        default=str,
    )
)
source = parameters.get("source") or parameters.get("sourcePath")
assert source and (source.replace("`", "") == name or source.strip('"').rstrip("/") == state["identity_location"]), (
    "Clone source does not match original table"
)
version = int(parameters["sourceVersion"])
assert payload["expected_catalog_id"] == state["id"], "Unexpected original registration"
_TableMigration.assert_data(spark.sql(f"SELECT * FROM {q} VERSION AS OF {version}"), spark.table(backup))
if payload.get("mode", "inspect") != "restore":
    dbutils.notebook.exit(
        json.dumps({"recovery_inspected": True, "registration": state["id"], "source_version": version})
    )
spark.sql(f"RESTORE TABLE {q} TO VERSION AS OF {version}").collect()
helper.target = payload["original_spec"]
helper.metadata = payload["original_metadata"]
helper.sources = {c["name"]: c["name"] for c in helper.target["columns"]}
helper.refactors, helper.steps, helper.run_id = [], [], "baseline_recovery"
helper.result, helper.changed = {"changes": []}, False
assert helper.metadata_steps(helper.state()["spec"]), "Original metadata needs manual recovery"
for step in helper.steps:
    spark.sql(step["sql"]).collect()
helper.restore_catalog(helper.metadata)
helper.validate()
_TableMigration.assert_data(spark.table(q), spark.table(backup))
assert helper.validated_state["id"] == state["id"], "Original registration changed"
assert set(helper.validated_state["spec"]["features"]) == set(payload["original_spec"]["features"]), (
    "Original features differ"
)
if payload.get("original_protocol"):
    assert all(helper.validated_state["detail"][key] == value for key, value in payload["original_protocol"].items()), (
        "Original protocol differs"
    )
assert helper.validated_catalog == payload["original_metadata"], "Original catalog metadata differs"
dbutils.notebook.exit(
    json.dumps(
        {
            "recovery_verified": True,
            "table": name,
            "registration": state["id"],
            "source_version": version,
            "delta_id": helper.validated_state["delta_id"],
            "backup_retained": backup,
        }
    )
)
