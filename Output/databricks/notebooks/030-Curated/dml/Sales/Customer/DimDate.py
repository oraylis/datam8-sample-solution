# Databricks notebook source
# MAGIC %md
# MAGIC # DML for gold.Sales_Customer_DimDate
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
zone = f"{schema_prefix}gold" if schema_prefix else "gold"
data_product = "Sales"
data_module = "Customer"
table_name = "DimDate"
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

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.current_timestamp(),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write into target table

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ### Prepare merge statement

# COMMAND ----------

target_table = DeltaTable.forName(spark, table_name_ref)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
merge_builder = (
    target_table.alias("tgt")
    .merge(
        final_df.alias("src"),
        "tgt.`DateID` <=> src.`DateID`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`Date` <=> src.`Date`) OR NOT (tgt.`CalendarYear` <=> src.`CalendarYear`) OR NOT (tgt.`MonthName` <=> src.`MonthName`)
    """,
    set={
        "Date": 'src.`Date`', 
        "CalendarYear": 'src.`CalendarYear`', 
        "MonthName": 'src.`MonthName`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__BusinessFunction": 'src.__BusinessFunction', 
        "DateID": 'src.`DateID`', 
        "Date": 'src.`Date`', 
        "CalendarYear": 'src.`CalendarYear`', 
        "MonthName": 'src.`MonthName`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------