# Databricks notebook source
# MAGIC %md
# MAGIC # DML for raw.Sales_Product_ProductModel

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize base settings

# COMMAND ----------

# MAGIC %run ../../../../../../utils/MigrationFramework

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize Extraction Framework

# COMMAND ----------

# MAGIC %run ../../../../../../utils/ExtractionFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "datam8_campus_dev_fka", "Catalog Name")
dbutils.widgets.text("owner", "datam8_sample_dev_owner", "Owner")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# dbutils.widgets.dropdown(
#     "run_mode",
#     "INFO",
#     ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
#     "Run Mode",
# )
#dbutils.widgets.text("sandbox", "_", "Sandbox")

dbutils.widgets.text("keyvault_name", "aut0kvt0dev0campus", "Key Vault Name")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
job_run_id = dbutils.widgets.get("job_run_id")
# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")

keyvault_name = dbutils.widgets.get("keyvault_name")

# static values
zone = "raw"
data_source = "AdventureWorks"
data_source_display = "Adventure Works Demo Database"
source_name = "ProductModel"
full_table_name = "Sales_Product_ProductModel"
write_mode = "append"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
print("Data Source: %s" % data_source)
print("Data Source Display: %s" % data_source_display)
# print("Mode: %s" % run_mode)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read data from source system

# COMMAND ----------

# DBTITLE 1,Get connection values
database_connectionstring = dbutils.secrets.get(scope=keyvault_name, key="datasource-AdventureWorks-connectionstring")
source_location = "[SalesLT].[ProductModel]"
extract_mode = ("delta").lower()
data_source_type = "SqlDataSource"
column_renames = []
delta_column_details = [{"canonicalDataType": "datetime", "sourceName": "ModifiedDate"}]
target_columns = ["ProductModelID", "Name", "CatalogDescription", "rowguid", "ModifiedDate"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract source data

# COMMAND ----------

# DBTITLE 1,Determine delta value
delta_column = "ModifiedDate"
max_raw = spark.sql(f"""
SELECT
  CAST(COALESCE(MAX(`{delta_column}`), '1970-01-01') AS STRING) AS MaxDelta
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

print(f"Using delta value: {max_raw}")

# COMMAND ----------

# DBTITLE 1,Initialize framework & execute function
if not source_location:
    source_location = source_name

SourceTable = ExtractionFramework(source_location, extract_mode, delta_column_details)
extractSourceTable = SourceTable

if not data_source_type:
    raise ValueError(f"Data source type is missing for '{data_source}'.")

extract_function = getattr(extractSourceTable, data_source_type, None)

if extract_function is None:
    raise AttributeError(
        f"ExtractionFramework does not implement '{data_source_type}' for '{data_source}'."
    )

table_df = extract_function(
    database_connectionstring
    , max_raw
)
# COMMAND ----------

# MAGIC %md
# MAGIC ## Finish extraction

# COMMAND ----------
# DBTITLE 1,Add technical columns
load_timestamp = F.current_timestamp()
table_df = (
    table_df
    .withColumn("__Year", F.year(load_timestamp).cast("smallint"))
    .withColumn("__Month", F.month(load_timestamp).cast("smallint"))
    .withColumn("__Day", F.dayofmonth(load_timestamp).cast("smallint"))
    .withColumn("__InsertTimestampUTC", load_timestamp)
)
# COMMAND ----------
# DBTITLE 1,Rename & select columns
for rename in column_renames:
    source_column = rename.get("source")
    target_column = rename.get("target")
    if not source_column or not target_column or source_column == target_column:
        continue
    table_df = table_df.withColumnRenamed(source_column, target_column)

if target_columns:
    table_df = table_df.select(*(["__Year","__Month","__Day","__InsertTimestampUTC"] + target_columns))
# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to RAW zone

# COMMAND ----------

(
    table_df.write
    .mode(write_mode)
    .saveAsTable(f"{catalog_name}.{zone}.{full_table_name}")
)

# COMMAND ----------

# DBTITLE 1,Update extraction status
record_count = table_df.count()
print(f"Extracted {record_count} records in extraction")