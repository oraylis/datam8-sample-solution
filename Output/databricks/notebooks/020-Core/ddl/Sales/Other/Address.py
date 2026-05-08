# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for core.Sales_Other_Address

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize base settings

# COMMAND ----------

# MAGIC %md
# MAGIC ### Imports

# COMMAND ----------

from pyspark.sql.types import (
    StructType,  # noqa: F401
    StructField,  # noqa: F401
    DataType,  # noqa: F401
)

# COMMAND ----------

from delta.tables import DeltaTable

# COMMAND ----------

# MAGIC %md
# MAGIC ### Get variable values

# COMMAND ----------

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
zone = f"{schema_prefix}core" if schema_prefix else "core"
data_product = "Sales"
data_module = "Other"
table_name = "Address"
full_table_name = "Sales_Other_Address"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Data Product: %s" % data_product)
print("Data Module: %s" % data_module)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define table schema

# COMMAND ----------

# DBTITLE 1,Define schema
table_name = f"{catalog_name}.{zone}.{full_table_name}"
table_comment = "Core address dimension with location data"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__BusinessFunction", DataType.fromDDL("STRING"), False, metadata={'comment': 'Business function identifier'}),
    StructField("_AddressBK", DataType.fromDDL("INT"), False, metadata={'business_key': True}),
    StructField("_AddressSID", DataType.fromDDL("BIGINT"), False),
    StructField("AddressID", DataType.fromDDL("INT"), False),
    StructField("AddressLine1", DataType.fromDDL("STRING"), False),
    StructField("AddressLine2", DataType.fromDDL("STRING"), True),
    StructField("CityName", DataType.fromDDL("STRING"), False),
    StructField("CountryRegionName", DataType.fromDDL("STRING"), False),
    StructField("PostalCode", DataType.fromDDL("STRING"), False),
    StructField("StateProvinceName", DataType.fromDDL("STRING"), False),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "_AddressBK",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Other_Address (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__BusinessFunction` STRING NOT NULL COMMENT 'Business function identifier',
  `_AddressBK` INT NOT NULL,
  `_AddressSID` BIGINT NOT NULL,
  `AddressID` INT NOT NULL,
  `AddressLine1` STRING NOT NULL,
  `AddressLine2` STRING,
  `CityName` STRING NOT NULL,
  `CountryRegionName` STRING NOT NULL,
  `PostalCode` STRING NOT NULL,
  `StateProvinceName` STRING NOT NULL
)
USING DELTA
COMMENT 'Core address dimension with location data'
CLUSTER BY (`_AddressBK`)
TBLPROPERTIES ('delta.logRetentionDuration'='interval 7 days', 'delta.deletedFileRetentionDuration'='interval 7 days');"""
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
    {
        "name": "AddressLine1",
        "refactorNames": [
            "AddressLine1",
            "AddressLine1Name",
        ]
    },
    {
        "name": "CityName",
        "refactorNames": [
            "City",
        ]
    },
    {
        "name": "CountryRegionName",
        "refactorNames": [
            "CountryRegion",
        ]
    },
    {
        "name": "StateProvinceName",
        "refactorNames": [
            "StateProvince",
        ]
    },
]

# COMMAND ----------

# DBTITLE 1,Call migrate_schema method
table_instance = Table(f"{zone}.{full_table_name}", catalog)

try:
    result = table_instance.migrate_schema(
        ddl=create_sql,
        schema=schema,
        refactored_columns=refactored_columns,
        new_partitions=partitions,
    )

    print("Result: %s" % str(result))
except Exception as e:
    print(f"Migration failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tags

# COMMAND ----------

# DBTITLE 1,Set table & column tags
# table attributes
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes
table_instance.set_column_tags("_AddressSID", {'attribute_type': 'SK'})