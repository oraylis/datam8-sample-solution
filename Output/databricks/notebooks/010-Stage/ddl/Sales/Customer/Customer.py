# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for bronze.Sales_Customer_Customer

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
zone = f"{schema_prefix}bronze" if schema_prefix else "bronze"
data_product = "Sales"
data_module = "Customer"
table_name = "Customer"
full_table_name = "Sales_Customer_Customer"

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
table_comment = "Core customer information entity"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__InsertTimestampRawUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'External load timestamp (UTC)'}),
    StructField("__SourceTable", DataType.fromDDL("STRING"), False, metadata={'comment': 'Origin reference for the record'}),
    StructField("KundenID", DataType.fromDDL("INT"), False, metadata={'comment': 'Unique key for the customer', 'business_key': True}),
    StructField("NamensTyp", DataType.fromDDL("BOOLEAN"), False),
    StructField("Titel", DataType.fromDDL("STRING"), True),
    StructField("Vorname", DataType.fromDDL("STRING"), False),
    StructField("Nameszusatz1", DataType.fromDDL("STRING"), True),
    StructField("Nachname", DataType.fromDDL("STRING"), False),
    StructField("Namenszusatz2", DataType.fromDDL("STRING"), True),
    StructField("Firma", DataType.fromDDL("STRING"), True),
    StructField("Verkaeufer", DataType.fromDDL("STRING"), True),
    StructField("Email", DataType.fromDDL("STRING"), True),
    StructField("Telefon", DataType.fromDDL("STRING"), True),
    StructField("GeaendertAm", DataType.fromDDL("TIMESTAMP"), False),
    StructField("KundenName", DataType.fromDDL("STRING"), False),
    StructField("__ValidFrom", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 start date'}),
    StructField("__ValidTo", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'SCD2 end date'}),
    StructField("__IsCurrent", DataType.fromDDL("BOOLEAN"), False, metadata={'comment': 'SCD2 current flag'}),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "KundenID",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Customer_Customer (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__InsertTimestampRawUTC` TIMESTAMP NOT NULL COMMENT 'External load timestamp (UTC)',
  `__SourceTable` STRING NOT NULL COMMENT 'Origin reference for the record',
  `KundenID` INT NOT NULL COMMENT 'Unique key for the customer',
  `NamensTyp` BOOLEAN NOT NULL,
  `Titel` STRING,
  `Vorname` STRING NOT NULL,
  `Nameszusatz1` STRING,
  `Nachname` STRING NOT NULL,
  `Namenszusatz2` STRING,
  `Firma` STRING,
  `Verkaeufer` STRING,
  `Email` STRING,
  `Telefon` STRING,
  `GeaendertAm` TIMESTAMP NOT NULL,
  `KundenName` STRING NOT NULL,
  `__ValidFrom` TIMESTAMP NOT NULL COMMENT 'SCD2 start date',
  `__ValidTo` TIMESTAMP NOT NULL COMMENT 'SCD2 end date',
  `__IsCurrent` BOOLEAN NOT NULL COMMENT 'SCD2 current flag'
)
USING DELTA
COMMENT 'Core customer information entity'
CLUSTER BY (`KundenID`)
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
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'table_properties': ['type_widening', 'column_mapping'], 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes
table_instance.set_column_tags("KundenID", {'data_layout': 'liquid_clustering'})
table_instance.set_column_tags("GeaendertAm", {'extract_mode': 'delta'})