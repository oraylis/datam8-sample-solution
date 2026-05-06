# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for gold.Sales_Customer_DimCustomer

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
zone = f"{schema_prefix}gold" if schema_prefix else "gold"
data_product = "Sales"
data_module = "Customer"
table_name = "DimCustomer"
full_table_name = "Sales_Customer_DimCustomer"

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
table_comment = "Customer dimension with personal and address information"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__BusinessFunction", DataType.fromDDL("STRING"), False, metadata={'comment': 'Business function identifier'}),
    StructField("CustomerSID", DataType.fromDDL("BIGINT"), False, metadata={'comment': 'Customer surrogate key'}),
    StructField("CustomerID", DataType.fromDDL("INT"), True, metadata={'comment': 'Original customer identifier', 'business_key': True}),
    StructField("DisplayName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer display name'}),
    StructField("FirstName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer first name'}),
    StructField("LastName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Customer last name'}),
    StructField("AddressType", DataType.fromDDL("STRING"), True, metadata={'comment': 'Type of customer address (Home, Business, etc.)'}),
    StructField("Address", DataType.fromDDL("STRING"), True, metadata={'comment': 'Full address line'}),
    StructField("PostalCode", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address postal code'}),
    StructField("CityName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address city name'}),
    StructField("CountryName", DataType.fromDDL("STRING"), True, metadata={'comment': 'Address country name'}),
    StructField("__ValidFrom", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 start date'}),
    StructField("__ValidTo", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 end date'}),
    StructField("__IsCurrent", DataType.fromDDL("BOOLEAN"), False, metadata={'comment': 'SCD2 current flag'}),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "CustomerID",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Customer_DimCustomer (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__BusinessFunction` STRING NOT NULL COMMENT 'Business function identifier',
  `CustomerSID` BIGINT NOT NULL COMMENT 'Customer surrogate key',
  `CustomerID` INT COMMENT 'Original customer identifier',
  `DisplayName` STRING COMMENT 'Customer display name',
  `FirstName` STRING COMMENT 'Customer first name',
  `LastName` STRING COMMENT 'Customer last name',
  `AddressType` STRING COMMENT 'Type of customer address (Home, Business, etc.)',
  `Address` STRING COMMENT 'Full address line',
  `PostalCode` STRING COMMENT 'Address postal code',
  `CityName` STRING COMMENT 'Address city name',
  `CountryName` STRING COMMENT 'Address country name',
  `__ValidFrom` TIMESTAMP NOT NULL COMMENT 'SCD2 start date',
  `__ValidTo` TIMESTAMP NOT NULL COMMENT 'SCD2 end date',
  `__IsCurrent` BOOLEAN NOT NULL COMMENT 'SCD2 current flag'
)
USING DELTA
COMMENT 'Customer dimension with personal and address information'
CLUSTER BY (`CustomerID`)
TBLPROPERTIES ('delta.logRetentionDuration'='interval 7 days', 'delta.deletedFileRetentionDuration'='interval 7 days');"""
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
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'weekly', 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes
table_instance.set_column_tags("CustomerSID", {'attribute_type': 'SK'})