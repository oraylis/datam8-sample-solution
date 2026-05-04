# Databricks notebook source
# MAGIC %md
# MAGIC # DML for bronze.Sales_Other_Address
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['AddressID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['AddressID', 'AddressLine1', 'AddressLine2', 'City', 'StateProvince', 'CountryRegion', 'PostalCode', 'rowguid', 'ModifiedDate']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ../../../../../../utils/MigrationFramework

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
zone = f"{schema_prefix}bronze" if schema_prefix else "bronze"
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
        "`AddressID`",
        "`AddressLine1`",
        "`AddressLine2`",
        "`City`",
        "`StateProvince`",
        "`CountryRegion`",
        "`PostalCode`",
        "`rowguid`",
        "`ModifiedDate`",
        "'Address' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__UpdateTimestampUTC AS __InsertTimestampSourceUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

if not source_delta_df_list:
    raise ValueError("No delta sources configured for this entity.")

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
union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to BRONZE

# COMMAND ----------
(
    union_df
    .write.saveAsTable(
        f"{catalog.name}.{zone}.{full_table_name}",
        mode="overwrite",
    )
)

# COMMAND ----------