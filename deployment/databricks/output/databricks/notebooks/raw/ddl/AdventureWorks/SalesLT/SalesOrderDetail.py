# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for raw.AdventureWorks_SalesLT_SalesOrderDetail

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
zone = "raw"
data_source = "AdventureWorks"
data_source_display = "Adventure Works Demo Database"
source_name = "SalesOrderDetail"
full_table_name = "AdventureWorks_SalesLT_SalesOrderDetail"

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

schema = StructType([
    StructField("__Year", DataType.fromDDL("SMALLINT"), False),
    StructField("__Month", DataType.fromDDL("SMALLINT"), False),
    StructField("__Day", DataType.fromDDL("SMALLINT"), False),
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False),
    StructField("SalesOrderID", DataType.fromDDL("INT"), True),
    StructField("SalesOrderDetailID", DataType.fromDDL("INT"), True),
    StructField("OrderQty", DataType.fromDDL("SMALLINT"), False),
    StructField("ProductID", DataType.fromDDL("INT"), True),
    StructField("UnitPrice", DataType.fromDDL("DECIMAL(19,4)"), False),
    StructField("UnitPriceDiscount", DataType.fromDDL("DECIMAL(19,4)"), False),
    StructField("LineTotal", DataType.fromDDL("DECIMAL(38,6)"), False),
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

# DBTITLE 1,Generated CREATE TABLE statement
create_sql = """CREATE TABLE IF NOT EXISTS `{catalog_name}`.`raw`.`AdventureWorks_SalesLT_SalesOrderDetail` (
  `__Year` SMALLINT NOT NULL,
  `__Month` SMALLINT NOT NULL,
  `__Day` SMALLINT NOT NULL,
  `__InsertTimestampUTC` TIMESTAMP NOT NULL,
  `SalesOrderID` INT,
  `SalesOrderDetailID` INT,
  `OrderQty` SMALLINT NOT NULL,
  `ProductID` INT,
  `UnitPrice` DECIMAL(19,4) NOT NULL,
  `UnitPriceDiscount` DECIMAL(19,4) NOT NULL,
  `LineTotal` DECIMAL(38,6) NOT NULL,
  `rowguid` STRING NOT NULL,
  `ModifiedDate` TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Sales order line item details entity'
CLUSTER BY (`__Year`, `__Month`, `__Day`, `__InsertTimestampUTC`);""".replace("{catalog_name}", catalog_name)
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
table_instance.set_table_tags({'jobs': 'sales_daily', 'extract_mode': 'delta'})

# column attributes
table_instance.set_column_tags("ModifiedDate", {'extract_mode': 'delta'})