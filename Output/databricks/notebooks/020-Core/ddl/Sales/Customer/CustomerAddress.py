# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for silver.Sales_Customer_CustomerAddress

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

# MAGIC %run ../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("schema_prefix", "", "Schema Prefix")
dbutils.widgets.text("owner", "datam8_sample_dev_owner", "Owner")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
schema_prefix = dbutils.widgets.get("schema_prefix")
owner = dbutils.widgets.get("owner")
job_run_id = dbutils.widgets.get("job_run_id")

# static values
zone = f"{schema_prefix}silver" if schema_prefix else "silver"
data_product = "Sales"
data_module = "Customer"
table_name = "CustomerAddress"
full_table_name = "Sales_Customer_CustomerAddress"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
print("Data Product: %s" % data_product)
print("Data Module: %s" % data_module)
# print("Mode: %s" % run_mode)

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
table_comment = "Core customer address relationship entity"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__BusinessFunction", DataType.fromDDL("STRING"), False, metadata={'comment': 'Business function identifier'}),
    StructField("_CustomerAddressBK", DataType.fromDDL("STRING"), False, metadata={'business_key': True}),
    StructField("_CustomerAddressSID", DataType.fromDDL("BIGINT"), False),
    StructField("AddressID", DataType.fromDDL("INT"), False),
    StructField("CustomerID", DataType.fromDDL("INT"), False),
    StructField("AddressType", DataType.fromDDL("STRING"), False),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "_CustomerAddressBK",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Customer_CustomerAddress (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__BusinessFunction` STRING NOT NULL COMMENT 'Business function identifier',
  `_CustomerAddressBK` STRING NOT NULL,
  `_CustomerAddressSID` BIGINT NOT NULL,
  `AddressID` INT NOT NULL,
  `CustomerID` INT NOT NULL,
  `AddressType` STRING NOT NULL
)
USING DELTA
COMMENT 'Core customer address relationship entity'
CLUSTER BY (`_CustomerAddressBK`)
TBLPROPERTIES ('delta.logRetentionDuration'='interval 7 days', 'delta.deletedFileRetentionDuration'='interval 7 days');"""
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
    {
        "name": "_CustomerAddressBK",
        "refactorNames": [
            "_CustomerBK",
        ]
    },
    {
        "name": "CustomerID",
        "refactorNames": [
            "CustomerBK",
        ]
    },
    {
        "name": "AddressType",
        "refactorNames": [
            "AddressType",
            "AddressTypeName",
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

table_instance.owner = owner

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tags

# COMMAND ----------

# DBTITLE 1,Set table & column tags
# table attributes
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes
table_instance.set_column_tags("_CustomerAddressSID", {'attribute_type': 'SK'})