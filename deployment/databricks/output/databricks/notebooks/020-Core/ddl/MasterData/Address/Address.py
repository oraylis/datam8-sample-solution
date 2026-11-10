# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for core.MasterData_Address_Address

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
zone = "core"
data_product = "MasterData"
data_module = "Address"
table_name = "Address"
full_table_name = "MasterData_Address_Address"

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
    StructField("__BusinessFunction", DataType.fromDDL("STRING"), False, metadata={'comment': 'Business function marker'}),
    StructField("_AddressBK", DataType.fromDDL("INT"), False, metadata={'business_key': True}),
    StructField("_AddressSID", DataType.fromDDL("BIGINT"), False, metadata={'surrogate_key': True}),
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

# DBTITLE 1,Generated CREATE TABLE statement
create_sql = """CREATE TABLE IF NOT EXISTS `{catalog_name}`.`core`.`MasterData_Address_Address` (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__BusinessFunction` STRING NOT NULL COMMENT 'Business function marker',
  `_AddressBK` INT NOT NULL,
  `_AddressSID` BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
  `AddressID` INT NOT NULL,
  `AddressLine1` STRING NOT NULL,
  `AddressLine2` STRING,
  `CityName` STRING NOT NULL,
  `CountryRegionName` STRING NOT NULL,
  `PostalCode` STRING NOT NULL,
  `StateProvinceName` STRING NOT NULL,
  CONSTRAINT `pk_{catalog_name}_core_MasterData_Address_Address_17e2989c5e` PRIMARY KEY (`_AddressSID`) RELY
)
USING DELTA
COMMENT 'Core address dimension with location data'
CLUSTER BY (`_AddressBK`);""".replace("{catalog_name}", catalog_name)
print(create_sql)

# Execute SQL statement
table_existed = spark.catalog.tableExists(table_name)
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
table_instance.set_table_tags({'jobs': 'sales_daily', 'write_mode': 'merge'})

# column attributes
table_instance.set_column_tags("_AddressSID", {'attribute_type': 'SK'})