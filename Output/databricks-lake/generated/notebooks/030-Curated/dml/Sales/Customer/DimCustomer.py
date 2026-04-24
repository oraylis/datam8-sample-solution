# Databricks notebook source
# MAGIC %md
# MAGIC # DML for gold.Sales_Customer_DimCustomer
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['CustomerID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['CustomerSID', 'CustomerID', 'AddressType', 'Address', 'PostalCode', 'CityName', 'CountryName']
# MAGIC - __SCD2 columns__: ['DisplayName', 'FirstName', 'LastName']

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
dbutils.widgets.text("catalog_name", "datam8_campus_dev_fka", "Catalog Name")
dbutils.widgets.text("schema_prefix", "", "Schema Prefix")
dbutils.widgets.text("owner", "datam8_sample_dev_owner", "Owner")
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
schema_prefix = dbutils.widgets.get("schema_prefix")
owner = dbutils.widgets.get("owner")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")


# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = f"{schema_prefix}gold" if schema_prefix else "gold"
data_product = "Sales"
data_module = "Customer"
table_name = "DimCustomer"
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
# MAGIC #### DimCustomer

# COMMAND ----------

functions["DimCustomer"] = {
  "name": "transform_customer_dimension",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
    {"dm8l": "/Core/Sales/Customer/Customer"},
    {"dm8l": "/Core/Sales/Customer/CustomerAddress"},
    {"dm8l": "/Core/Sales/Other/Address"}
  ],
}

# COMMAND ----------

# MAGIC %run ./DimCustomer_functions/DimCustomer

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
    "__BusinessFunction": F.lit("DimCustomer"),
    "__InsertTimestampUTC": F.current_timestamp(),
})
functions["DimCustomer"]["df"] = business_function  # noqa: F821

# COMMAND ----------
final_df = functions["DimCustomer"]["df"]

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
current_snapshot_df = (
    spark.table(table_name_ref)
    .where(F.col("__IsCurrent").eqNullSafe(True))
)

staged_base = (
    final_df.alias("src")
    .join(
        current_snapshot_df.alias("tgt"),
        [
            (F.col("src.`CustomerID`") == F.col("tgt.`CustomerID`"))
        ],
        "left",
    )
    .withColumns({
        "__target_exists": F.col("tgt.__IsCurrent").isNotNull(),
        "scd2_changed":
        (
            (~F.col("tgt.`DisplayName`").eqNullSafe(F.col("src.`DisplayName`"))) |
            
            (~F.col("tgt.`FirstName`").eqNullSafe(F.col("src.`FirstName`"))) |
            
            (~F.col("tgt.`LastName`").eqNullSafe(F.col("src.`LastName`")))
        )
        ,
        "__ValidFrom": F.col("src.__InsertTimestampUTC"),
        "__ValidTo": F.to_timestamp(F.lit(MAX_VALID_TO_DATE)),
        "__IsCurrent": F.lit(True),
    })
    .select("src.*", "__target_exists", "scd2_changed", "__ValidFrom", "__ValidTo", "__IsCurrent")
)

staged_updates = staged_base.filter(F.col("__target_exists")).withColumn("__merge_action", F.lit("update"))
staged_inserts = (
    staged_base
    .filter(
        (~F.col("__target_exists")) | F.col("scd2_changed")
    )
    .withColumn("__merge_action", F.lit("insert"))
)
staged_union = staged_updates.unionByName(staged_inserts)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
merge_builder = (
    target_table.alias("tgt")
    .merge(
        staged_union.alias("src"),
        "(tgt.`CustomerID` <=> src.`CustomerID`) AND src.__merge_action = 'update'",
    )
    .whenMatchedUpdate(
        condition="src.scd2_changed",
        set={
            "__ValidTo": "src.__InsertTimestampUTC",
            "__IsCurrent": "False",
            "__UpdateTimestampUTC": "src.__UpdateTimestampUTC",
        },
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="(NOT src.scd2_changed) AND (NOT (tgt.`AddressType` <=> src.`AddressType`) OR NOT (tgt.`Address` <=> src.`Address`) OR NOT (tgt.`PostalCode` <=> src.`PostalCode`) OR NOT (tgt.`CityName` <=> src.`CityName`) OR NOT (tgt.`CountryName` <=> src.`CountryName`))",
    set={
        "AddressType": 'src.`AddressType`', 
        "Address": 'src.`Address`', 
        "PostalCode": 'src.`PostalCode`', 
        "CityName": 'src.`CityName`', 
        "CountryName": 'src.`CountryName`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__ValidFrom": "src.__ValidFrom",
        "__ValidTo": "src.__ValidTo",
        "__IsCurrent": "src.__IsCurrent",
        "__InsertTimestampUTC":'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC":'src.__UpdateTimestampUTC', 
        "__BusinessFunction":'src.__BusinessFunction', 
        "CustomerID":'src.`CustomerID`', 
        "DisplayName":'src.`DisplayName`', 
        "FirstName":'src.`FirstName`', 
        "LastName":'src.`LastName`', 
        "AddressType":'src.`AddressType`', 
        "Address":'src.`Address`', 
        "PostalCode":'src.`PostalCode`', 
        "CityName":'src.`CityName`', 
        "CountryName":'src.`CountryName`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------