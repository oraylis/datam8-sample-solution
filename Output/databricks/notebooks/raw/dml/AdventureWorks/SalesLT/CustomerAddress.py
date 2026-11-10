# Databricks notebook source
# MAGIC %md
# MAGIC # DML for raw.AdventureWorks_SalesLT_CustomerAddress

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize base settings

# COMMAND ----------

# MAGIC %run ../../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("connection_prefix", "sample_", "UC Connection Prefix")
dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("owner", "", "Owner")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# dbutils.widgets.dropdown(
#     "run_mode",
#     "INFO",
#     ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
#     "Run Mode",
# )
#dbutils.widgets.text("sandbox", "_", "Sandbox")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
if not catalog_name or not owner:
    raise ValueError("Set catalog_name and owner explicitly before running this notebook")
job_run_id = dbutils.widgets.get("job_run_id")
# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")

# static values
zone = "raw"
data_source = "AdventureWorks"
data_source_display = "Adventure Works Demo Database"
source_name = "CustomerAddress"
full_table_name = "AdventureWorks_SalesLT_CustomerAddress"
write_mode = "overwrite"

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

# DBTITLE 1,Prepare source extraction
source_location = "SELECT * FROM [SalesLT].[CustomerAddress] WHERE CustomerID \u003e 1"
extract_mode = ("full").lower()
connection_name = "sqlserver"

connection_name = dbutils.widgets.get("connection_prefix") + connection_name

remote_query_database = "adventureworks"
column_renames = []
target_columns = ["CustomerID", "AddressID", "AddressType"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract source data

# COMMAND ----------

# DBTITLE 1,Initialize framework & execute function
if not source_location:
    source_location = source_name

from pathlib import Path
import sys
notebook_folder = Path(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()).parent
# DML notebooks are output/databricks/notebooks/<zone>/dml/<product>/<module>/<entity>.
sys.path.insert(0, str(Path("/Workspace") / notebook_folder.relative_to("/").parents[4] / "runtime"))
from uc_sources import read_database, read_http

table_df = read_database(spark, connection_name, source_location, remote_query_database, "builtin:SQLServer")

if extract_mode == "delta":
    delta_column = ""
    if not delta_column:
        raise ValueError("Delta extraction is missing its cursor column")
    cursor_type = table_df.schema[delta_column].dataType
    table_df = table_df.filter(F.col(delta_column) > F.lit(max_raw).cast(cursor_type))
    # Inspect the scan's pushed predicates before any source action executes.
    table_df.explain(mode="formatted")
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
    target_types = {"AddressID": "INT", "AddressType": "STRING", "CustomerID": "INT"}
    table_df = table_df.select("__Year", "__Month", "__Day", "__InsertTimestampUTC", *[F.col(name).cast(target_types[name]).alias(name) for name in target_columns])
# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to RAW zone

# COMMAND ----------

table_df = table_df.persist()
try:
    # Materialize the external read once for both metrics and the write.
    record_count = table_df.count()
    table_df.write.mode(write_mode).saveAsTable(f"{catalog_name}.{zone}.{full_table_name}")
finally:
    table_df.unpersist()

# COMMAND ----------

# DBTITLE 1,Update extraction status
print(f"Extracted {record_count} records in extraction")