# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for raw.Sales_Other_Address

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
zone = f"{schema_prefix}raw" if schema_prefix else "raw"
data_source = "AdventureWorks"
data_source_display = "Adventure Works Demo Database"
source_name = "Address"
full_table_name = "Sales_Other_Address"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
print("Data Source: %s" % data_source)
print("Data Source Display: %s" % data_source_display)
print("Source Name: %s" % source_name)
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
table_comment = "Address information entity"

schema = StructType([
    StructField("__Year", DataType.fromDDL("SMALLINT"), False),
    StructField("__Month", DataType.fromDDL("SMALLINT"), False),
    StructField("__Day", DataType.fromDDL("SMALLINT"), False),
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False),
    StructField("AddressID", DataType.fromDDL("INT"), False),
    StructField("AddressLine1", DataType.fromDDL("STRING"), False),
    StructField("AddressLine2", DataType.fromDDL("STRING"), True),
    StructField("City", DataType.fromDDL("STRING"), False),
    StructField("StateProvince", DataType.fromDDL("STRING"), False),
    StructField("CountryRegion", DataType.fromDDL("STRING"), False),
    StructField("PostalCode", DataType.fromDDL("STRING"), False),
    StructField("rowguid", DataType.fromDDL("STRING"), False),
    StructField("ModifiedDate", DataType.fromDDL("TIMESTAMP"), False),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "__Year",
    "__Month",
    "__Day",
    "__InsertTimestampUTC",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Other_Address (
  `__Year` SMALLINT NOT NULL,
  `__Month` SMALLINT NOT NULL,
  `__Day` SMALLINT NOT NULL,
  `__InsertTimestampUTC` TIMESTAMP NOT NULL,
  `AddressID` INT NOT NULL,
  `AddressLine1` STRING NOT NULL,
  `AddressLine2` STRING,
  `City` STRING NOT NULL,
  `StateProvince` STRING NOT NULL,
  `CountryRegion` STRING NOT NULL,
  `PostalCode` STRING NOT NULL,
  `rowguid` STRING NOT NULL,
  `ModifiedDate` TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Address information entity'
CLUSTER BY (`__Year`, `__Month`, `__Day`, `__InsertTimestampUTC`)
TBLPROPERTIES ('delta.columnMapping.mode'='name', 'delta.enableTypeWidening'='true', 'delta.logRetentionDuration'='interval 7 days', 'delta.deletedFileRetentionDuration'='interval 7 days');"""
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
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
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'table_properties': ['type_widening', 'column_mapping']})

# column attributes
table_instance.set_column_tags("ModifiedDate", {'extract_mode': 'delta'})