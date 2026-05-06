# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for raw.Sales_Customer_Customer_EN

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
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
schema_prefix = dbutils.widgets.get("schema_prefix")
job_run_id = dbutils.widgets.get("job_run_id")

# static values
zone = f"{schema_prefix}raw" if schema_prefix else "raw"
data_source = "AdventureWorks"
data_source_display = "Adventure Works Demo Database"
source_name = "Customer_EN"
full_table_name = "Sales_Customer_Customer_EN"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Data Source: %s" % data_source)
print("Data Source Display: %s" % data_source_display)
print("Source Name: %s" % source_name)

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
    StructField("__Year", DataType.fromDDL("SMALLINT"), False),
    StructField("__Month", DataType.fromDDL("SMALLINT"), False),
    StructField("__Day", DataType.fromDDL("SMALLINT"), False),
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False),
    StructField("KundenID", DataType.fromDDL("INT"), False),
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
    StructField("PasswordHash", DataType.fromDDL("STRING"), False),
    StructField("PasswordSalt", DataType.fromDDL("STRING"), False),
    StructField("rowguid", DataType.fromDDL("STRING"), False),
    StructField("GeaendertAm", DataType.fromDDL("TIMESTAMP"), False),
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
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Customer_Customer_EN (
  `__Year` SMALLINT NOT NULL,
  `__Month` SMALLINT NOT NULL,
  `__Day` SMALLINT NOT NULL,
  `__InsertTimestampUTC` TIMESTAMP NOT NULL,
  `KundenID` INT NOT NULL,
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
  `PasswordHash` STRING NOT NULL,
  `PasswordSalt` STRING NOT NULL,
  `rowguid` STRING NOT NULL,
  `GeaendertAm` TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Core customer information entity'
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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tags

# COMMAND ----------

# DBTITLE 1,Set table & column tags
# table attributes
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'table_properties': ['type_widening', 'column_mapping']})

# column attributes
table_instance.set_column_tags("GeaendertAm", {'extract_mode': 'delta'})