# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for stage.AdventureWorks_SalesLT_Address

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
zone = "stage"
data_product = "AdventureWorks"
data_module = "SalesLT"
table_name = "Address"
full_table_name = "AdventureWorks_SalesLT_Address"

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

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__InsertTimestampRawUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Raw load timestamp (UTC)'}),
    StructField("__SourceTable", DataType.fromDDL("STRING"), False, metadata={'comment': 'Origin reference for the record'}),
    StructField("AddressID", DataType.fromDDL("INT"), True, metadata={'business_key': True}),
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
    "AddressID",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Generated CREATE TABLE statement
create_sql = """CREATE TABLE IF NOT EXISTS `{catalog_name}`.`stage`.`AdventureWorks_SalesLT_Address` (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__InsertTimestampRawUTC` TIMESTAMP NOT NULL COMMENT 'Raw load timestamp (UTC)',
  `__SourceTable` STRING NOT NULL COMMENT 'Origin reference for the record',
  `AddressID` INT,
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
CLUSTER BY (`AddressID`);""".replace("{catalog_name}", catalog_name)
print(create_sql)

# Execute SQL statement
table_existed = spark.catalog.tableExists(table_name)
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
]

# COMMAND ----------

# DBTITLE 1,Call migrate_schema method
table_instance = Table(f"{zone}.{full_table_name}", catalog)

try:
    if table_existed:
        result = table_instance.migrate_schema(
            ddl=create_sql,
            schema=schema,
            refactored_columns=refactored_columns,
            new_partitions=partitions,
        )
    else:
        result = 2  # A newly created table already has the target schema.

    print("Result: %s" % str(result))
except Exception as e:
    raise RuntimeError(f"Migration failed: {e}") from e

table_instance.owner = owner

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tags

# COMMAND ----------

# DBTITLE 1,Set table & column tags
# table attributes
table_instance.set_table_tags({'jobs': 'sales_daily', 'write_mode': 'overwrite'})

# column attributes
table_instance.set_column_tags("ModifiedDate", {'extract_mode': 'delta'})