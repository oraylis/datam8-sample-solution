# Databricks notebook source
# MAGIC %md
# MAGIC # DML for silver.Sales_Other_Address
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['_AddressBK']
# MAGIC - __SCD0 columns__: ['AddressLine2']
# MAGIC - __SCD1 columns__: ['_AddressBK', '_AddressSID', 'AddressID', 'AddressLine1', 'CityName', 'CountryRegionName', 'PostalCode', 'StateProvinceName']
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
zone = f"{schema_prefix}silver" if schema_prefix else "silver"
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
# MAGIC ### Execute transformation functions

# COMMAND ----------

functions = {}

# COMMAND ----------
# MAGIC %md
# MAGIC #### Address

# COMMAND ----------

functions["Address"] = {
  "name": "transform_first_step",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
  ],
}

# COMMAND ----------

# MAGIC %run ./Address_functions/Address

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
    "__BusinessFunction": F.lit("Address"),
    "__InsertTimestampUTC": F.lit(load_timestamp_utc),
})
functions["Address"]["df"] = business_function  # noqa: F821

# COMMAND ----------
final_df = functions["Address"]["df"]

# COMMAND ----------

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.lit(load_timestamp_utc),
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
        "tgt.`_AddressBK` <=> src.`_AddressBK`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`AddressID` <=> src.`AddressID`) OR NOT (tgt.`AddressLine1` <=> src.`AddressLine1`) OR NOT (tgt.`CityName` <=> src.`CityName`) OR NOT (tgt.`CountryRegionName` <=> src.`CountryRegionName`) OR NOT (tgt.`PostalCode` <=> src.`PostalCode`) OR NOT (tgt.`StateProvinceName` <=> src.`StateProvinceName`)
    """,
    set={
        "AddressID": 'src.`AddressID`', 
        "AddressLine1": 'src.`AddressLine1`', 
        "CityName": 'src.`CityName`', 
        "CountryRegionName": 'src.`CountryRegionName`', 
        "PostalCode": 'src.`PostalCode`', 
        "StateProvinceName": 'src.`StateProvinceName`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__BusinessFunction": 'src.__BusinessFunction', 
        "_AddressBK": 'src.`_AddressBK`', 
        "AddressID": 'src.`AddressID`', 
        "AddressLine1": 'src.`AddressLine1`', 
        "AddressLine2": 'src.`AddressLine2`', 
        "CityName": 'src.`CityName`', 
        "CountryRegionName": 'src.`CountryRegionName`', 
        "PostalCode": 'src.`PostalCode`', 
        "StateProvinceName": 'src.`StateProvinceName`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------

# COMMAND ----------

# DBTITLE 1,Update load status
record_count = spark.table(table_name_ref).filter(
    F.col("__UpdateTimestampUTC") == F.lit(load_timestamp_utc)
).count()
print(f"Loaded {record_count} records into target table")