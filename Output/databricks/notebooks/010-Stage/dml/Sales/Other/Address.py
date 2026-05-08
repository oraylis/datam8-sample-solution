# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Other_Address
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['AddressID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['AddressID', 'AddressLine1', 'AddressLine2', 'City', 'StateProvince', 'CountryRegion', 'PostalCode', 'rowguid', 'ModifiedDate']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401
from datetime import datetime, timezone

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ../../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("schema_prefix", "", "Schema Prefix")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
schema_prefix = dbutils.widgets.get("schema_prefix")
job_run_id = dbutils.widgets.get("job_run_id")

# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = f"{schema_prefix}stage" if schema_prefix else "stage"
data_product = "Sales"
data_module = "Other"
table_name = "Address"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# Reference to the fully-qualified target table (with backticks for catalog/schema/table).
table_name_ref = "`%(catalog)s`.`%(schema)s`.`%(table)s`" % {
    "catalog": catalog.name,
    "schema": zone,
    "table": full_table_name,
}
load_timestamp_utc = datetime.now(timezone.utc).replace(tzinfo=None)
load_timestamp_utc_sql = load_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S.%f")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Process source snapshots

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp in target table

# COMMAND ----------

max_source: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Other_Address'

# COMMAND ----------

max_source["raw_Sales_Other_Address"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampSourceUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxSource
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Other_Address'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.{schema_prefix}raw.Sales_Other_Address")
    .filter(F.col("__InsertTimestampUTC") > F.lit(max_source["raw_Sales_Other_Address"]))
    .selectExpr(
        "try_cast(`AddressID` as int) AS `AddressID`",
        "try_cast(`AddressLine1` as string) AS `AddressLine1`",
        "try_cast(`AddressLine2` as string) AS `AddressLine2`",
        "try_cast(`City` as string) AS `City`",
        "try_cast(`StateProvince` as string) AS `StateProvince`",
        "try_cast(`CountryRegion` as string) AS `CountryRegion`",
        "try_cast(`PostalCode` as string) AS `PostalCode`",
        "try_cast(`rowguid` as string) AS `rowguid`",
        "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
        "'Address' AS __SourceTable",
        f"CAST('{load_timestamp_utc_sql}' AS TIMESTAMP) AS __InsertTimestampUTC",
        f"CAST('{load_timestamp_utc_sql}' AS TIMESTAMP) AS __UpdateTimestampUTC",
        "__UpdateTimestampUTC AS __InsertTimestampSourceUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)
latest_snapshot_key_cols = ["AddressID"]
if latest_snapshot_key_cols:
    # Keep only the latest snapshot per business key to avoid duplicate records from source feeds.
    latest_snapshot_window = Window.partitionBy(*latest_snapshot_key_cols).orderBy(
        F.col("__InsertTimestampSourceUTC").desc(),
    )
    union_df = (
        union_df
        .withColumn("__dm8_latest_snapshot_rank", F.row_number().over(latest_snapshot_window))
        .where(F.col("__dm8_latest_snapshot_rank") == 1)
        .drop("__dm8_latest_snapshot_rank")
    )

if union_df.isEmpty():
    print("No new source rows found. Skip write to target table.")
    dbutils.notebook.exit("SKIPPED_EMPTY_SOURCE_DELTA")

union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to STAGE

# COMMAND ----------
(
    union_df
    .write.saveAsTable(
        f"{catalog.name}.{zone}.{full_table_name}",
        mode="overwrite",
    )
)

# COMMAND ----------

# COMMAND ----------

# DBTITLE 1,Update load status
record_count = spark.table(table_name_ref).filter(
    F.col("__UpdateTimestampUTC") == F.lit(load_timestamp_utc)
).count()
print(f"Loaded {record_count} records into target table")