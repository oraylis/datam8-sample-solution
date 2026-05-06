# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for bronze.Sales_Order_SalesOrderDetail

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
zone = f"{schema_prefix}bronze" if schema_prefix else "bronze"
data_product = "Sales"
data_module = "Order"
table_name = "SalesOrderDetail"
full_table_name = "Sales_Order_SalesOrderDetail"

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
table_comment = "Sales order line item details entity"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__InsertTimestampSourceUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Source load timestamp (UTC)'}),
    StructField("__SourceTable", DataType.fromDDL("STRING"), False, metadata={'comment': 'Origin reference for the record'}),
    StructField("SalesOrderID", DataType.fromDDL("INT"), False, metadata={'business_key': True}),
    StructField("SalesOrderDetailID", DataType.fromDDL("INT"), False, metadata={'business_key': True}),
    StructField("OrderQty", DataType.fromDDL("SMALLINT"), False),
    StructField("ProductID", DataType.fromDDL("INT"), False),
    StructField("UnitPrice", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("UnitPriceDiscount", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("LineTotal", DataType.fromDDL("DECIMAL(38, 6)"), False),
    StructField("rowguid", DataType.fromDDL("STRING"), False),
    StructField("ModifiedDate", DataType.fromDDL("TIMESTAMP"), False),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "SalesOrderID",
    "SalesOrderDetailID",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Order_SalesOrderDetail (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__InsertTimestampSourceUTC` TIMESTAMP NOT NULL COMMENT 'Source load timestamp (UTC)',
  `__SourceTable` STRING NOT NULL COMMENT 'Origin reference for the record',
  `SalesOrderID` INT NOT NULL,
  `SalesOrderDetailID` INT NOT NULL,
  `OrderQty` SMALLINT NOT NULL,
  `ProductID` INT NOT NULL,
  `UnitPrice` DECIMAL(19, 4) NOT NULL,
  `UnitPriceDiscount` DECIMAL(19, 4) NOT NULL,
  `LineTotal` DECIMAL(38, 6) NOT NULL,
  `rowguid` STRING NOT NULL,
  `ModifiedDate` TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Sales order line item details entity'
CLUSTER BY (`SalesOrderID`, `SalesOrderDetailID`)
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
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'daily', 'table_properties': ['type_widening', 'column_mapping'], 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes
table_instance.set_column_tags("ModifiedDate", {'extract_mode': 'delta'})