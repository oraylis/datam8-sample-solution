# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for curated.MasterData_Customer_DimCustomer

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
zone = "curated"
data_product = "MasterData"
data_module = "Customer"
table_name = "DimCustomer"
full_table_name = "MasterData_Customer_DimCustomer"

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
    StructField("CustomerSID", DataType.fromDDL("BIGINT"), False, metadata={'comment': 'Customer surrogate key', 'surrogate_key': True}),
    StructField("CustomerID", DataType.fromDDL("INT"), True, metadata={'comment': 'Original customer identifier', 'business_key': True}),
    StructField("DisplayName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer display name'}),
    StructField("FirstName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer first name'}),
    StructField("LastName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer last name'}),
    StructField("AddressType", DataType.fromDDL("STRING"), True, metadata={'comment': 'Type of customer address (Home, Business, etc.)'}),
    StructField("Address", DataType.fromDDL("STRING"), True, metadata={'comment': 'Full address line'}),
    StructField("PostalCode", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address postal code'}),
    StructField("CityName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address city name'}),
    StructField("CountryName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address country name'}),
    StructField("SourceSystem", DataType.fromDDL("STRING"), False, metadata={'comment': 'Source-system portion of the customer business key.', 'business_key': True}),
    StructField("__ValidFrom", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 start date'}),
    StructField("__ValidTo", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 end date'}),
    StructField("__IsCurrent", DataType.fromDDL("BOOLEAN"), False, metadata={'comment': 'SCD2 current flag'}),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "CustomerID",
    "SourceSystem",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Generated CREATE TABLE statement
create_sql = """CREATE TABLE IF NOT EXISTS `{catalog_name}`.`curated`.`MasterData_Customer_DimCustomer` (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__BusinessFunction` STRING NOT NULL COMMENT 'Business function marker',
  `CustomerSID` BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL COMMENT 'Customer surrogate key',
  `CustomerID` INT COMMENT 'Original customer identifier',
  `DisplayName` STRING COMMENT 'Customer display name',
  `FirstName` STRING COMMENT 'Customer first name',
  `LastName` STRING COMMENT 'Customer last name',
  `AddressType` STRING COMMENT 'Type of customer address (Home, Business, etc.)',
  `Address` STRING COMMENT 'Full address line',
  `PostalCode` STRING COMMENT 'Address postal code',
  `CityName` STRING COMMENT 'Address city name',
  `CountryName` STRING COMMENT 'Address country name',
  `SourceSystem` STRING NOT NULL COMMENT 'Source-system portion of the customer business key.',
  `__ValidFrom` TIMESTAMP NOT NULL COMMENT 'SCD2 start date',
  `__ValidTo` TIMESTAMP NOT NULL COMMENT 'SCD2 end date',
  `__IsCurrent` BOOLEAN NOT NULL COMMENT 'SCD2 current flag',
  CONSTRAINT `pk_{catalog_name}_curated_MasterData_Customer_DimCustomer_ebfce53e22` PRIMARY KEY (`CustomerSID`) RELY
)
USING DELTA
COMMENT 'Customer dimension with personal and address information'
CLUSTER BY (`CustomerID`, `SourceSystem`);""".replace("{catalog_name}", catalog_name)
print(create_sql)

# Execute SQL statement
table_existed = spark.catalog.tableExists(table_name)
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
    {
        "name": "CustomerSID",
        "refactorNames": [
            "_CustomerSID",
        ]
    },
    {
        "name": "DisplayName",
        "refactorNames": [
            "CustomerName",
        ]
    },
    {
        "name": "CountryName",
        "refactorNames": [
            "CountryRegionName",
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
table_instance.set_column_tags("CustomerSID", {'attribute_type': 'SK'})