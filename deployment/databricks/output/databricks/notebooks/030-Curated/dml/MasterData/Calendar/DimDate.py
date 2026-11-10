# Databricks notebook source
# MAGIC %md
# MAGIC # DML for curated.MasterData_Calendar_DimDate
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['DateID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['DateSID', 'DateID', 'Date', 'CalendarYear', 'MonthName']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ../../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("date_start", "2000-01-01", "Calendar start")
dbutils.widgets.text("date_end", "2030-12-31", "Calendar end")
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
sample_date_start = dbutils.widgets.get("date_start")
sample_date_end = dbutils.widgets.get("date_end")
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
if not catalog_name or not owner:
    raise ValueError("Set catalog_name and owner explicitly before running this notebook")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")


# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = "curated"
data_product = "MasterData"
data_module = "Calendar"
table_name = "DimDate"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
# print("Mode: %s" % run_mode)

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
# MAGIC ### Execute transformation functions

# COMMAND ----------

functions = {}

# COMMAND ----------
# MAGIC %md
# MAGIC #### GenerateDates

# COMMAND ----------

functions["GenerateDates"] = {
  "name": "transform_dimdate",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
  ],
}

# COMMAND ----------

# MAGIC %run ./DimDate_functions/GenerateDates

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
    "__BusinessFunction": F.lit("GenerateDates"),
    "__InsertTimestampUTC": F.current_timestamp(),
})
functions["GenerateDates"]["df"] = business_function  # noqa: F821

# COMMAND ----------
final_df = functions["GenerateDates"]["df"]

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply calculated columns

# COMMAND ----------

final_df = final_df.withColumns({
    "DateSID": F.expr('CAST(DateID AS BIGINT)')
})

# COMMAND ----------

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.current_timestamp(),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write into target table

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
final_write_df = final_df.select(
    "__InsertTimestampUTC", 
    "__UpdateTimestampUTC", 
    "__BusinessFunction", 
    "DateSID", 
    "DateID", 
    "Date", 
    "CalendarYear", 
    "MonthName"
)
if final_write_df.limit(1).count() > 0:
    final_write_df.write.saveAsTable(table_name_ref, mode="overwrite")
else:
    print("No transformed rows to write; keeping the existing target table unchanged.")

# COMMAND ----------