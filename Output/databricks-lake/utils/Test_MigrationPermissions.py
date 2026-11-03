# Databricks notebook source
# MAGIC %md
# MAGIC # Negative preflight under the local operator identity
# MAGIC Run only in the configured Dev workspace; this test must not mutate a table.

# COMMAND ----------
# MAGIC %run ./MigrationFramework

# COMMAND ----------
# ruff: noqa: F821
import json
from pyspark.sql.types import StructType, StructField, IntegerType

assert "7405619058873076" in spark.conf.get("spark.databricks.workspaceUrl")
catalog = Catalog("dm8_sample_dev_lake")
catalog.schema = "stage"
# Construct a handle without performing the constructor's eager read, so the
# permission rejection is exercised by the actual migrate_schema preflight.
table_instance = Table.__new__(Table)
table_instance.catalog = catalog
table_instance.schema_name = "stage"
table_instance.table_name = "postgresqlwarehouse_aw_warehouse_warehouse"
table_instance.spark = spark
try:
    table_instance.migrate_schema(
        "CREATE TABLE dm8_sample_dev_lake.stage.postgresqlwarehouse_aw_warehouse_warehouse (value INT) USING DELTA",
        StructType([StructField("value", IntegerType())]),
        [],
        [],
    )
except MigrationFailed as error:
    cause = error.__cause__ or error
    condition = getattr(cause, "getCondition", None) or getattr(cause, "getErrorClass", None)
    code = (condition() if condition else "") or ""
    sqlstate = getattr(cause, "getSqlState", lambda: "")() or ""
    assert sqlstate == "42501" or code.startswith(("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS")), (
        "Expected an actual catalog permission rejection"
    )
    assert not error.result["changes"], "Permission rejection must precede mutations"
    dbutils.notebook.exit(
        json.dumps(
            {
                "permission_rejection_verified": True,
                "condition": code,
                "sqlstate": sqlstate,
                "caller": spark.sql("SELECT current_user()").first()[0],
                "result": error.result,
            }
        )
    )
raise AssertionError("The selected operator unexpectedly has migration privileges")
