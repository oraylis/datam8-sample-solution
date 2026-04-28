# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for bronze.Sales_Order_SalesOrderHeader

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
data_module = "Order"
table_name = "SalesOrderHeader"
full_table_name = "Sales_Order_SalesOrderHeader"

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
table_comment = "Sales order header information entity"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__InsertTimestampRawUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'External load timestamp (UTC)'}),
    StructField("__SourceTable", DataType.fromDDL("STRING"), False, metadata={'comment': 'Origin reference for the record'}),
    StructField("SalesOrderID", DataType.fromDDL("INT"), False, metadata={'business_key': True}),
    StructField("RevisionNumber", DataType.fromDDL("INT"), False),
    StructField("OrderDate", DataType.fromDDL("TIMESTAMP"), False),
    StructField("DueDate", DataType.fromDDL("TIMESTAMP"), False),
    StructField("ShipDate", DataType.fromDDL("TIMESTAMP"), True),
    StructField("Status", DataType.fromDDL("INT"), False),
    StructField("OnlineOrderFlag", DataType.fromDDL("BOOLEAN"), False),
    StructField("SalesOrderNumber", DataType.fromDDL("STRING"), False),
    StructField("PurchaseOrderNumber", DataType.fromDDL("STRING"), True),
    StructField("AccountNumber", DataType.fromDDL("STRING"), True),
    StructField("CustomerID", DataType.fromDDL("INT"), False),
    StructField("ShipToAddressID", DataType.fromDDL("INT"), True),
    StructField("BillToAddressID", DataType.fromDDL("INT"), True),
    StructField("ShipMethod", DataType.fromDDL("STRING"), False),
    StructField("CreditCardApprovalCode", DataType.fromDDL("STRING(15)"), True),
    StructField("SubTotal", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("TaxAmt", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("Freight", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("TotalDue", DataType.fromDDL("DECIMAL(19, 4)"), False),
    StructField("Comment", DataType.fromDDL("STRING"), True),
    StructField("rowguid", DataType.fromDDL("STRING"), False),
    StructField("ModifiedDate", DataType.fromDDL("TIMESTAMP"), False),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = [
    "SalesOrderID",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Execute SQL Statement
create_sql = f"""CREATE TABLE IF NOT EXISTS {catalog_name}.{zone}.Sales_Order_SalesOrderHeader (
  `__InsertTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Load timestamp (UTC)',
  `__UpdateTimestampUTC` TIMESTAMP NOT NULL COMMENT 'Last update timestamp (UTC)',
  `__InsertTimestampRawUTC` TIMESTAMP NOT NULL COMMENT 'External load timestamp (UTC)',
  `__SourceTable` STRING NOT NULL COMMENT 'Origin reference for the record',
  `SalesOrderID` INT NOT NULL,
  `RevisionNumber` INT NOT NULL,
  `OrderDate` TIMESTAMP NOT NULL,
  `DueDate` TIMESTAMP NOT NULL,
  `ShipDate` TIMESTAMP,
  `Status` INT NOT NULL,
  `OnlineOrderFlag` BOOLEAN NOT NULL,
  `SalesOrderNumber` STRING NOT NULL,
  `PurchaseOrderNumber` STRING,
  `AccountNumber` STRING,
  `CustomerID` INT NOT NULL,
  `ShipToAddressID` INT,
  `BillToAddressID` INT,
  `ShipMethod` STRING NOT NULL,
  `CreditCardApprovalCode` STRING(15),
  `SubTotal` DECIMAL(19, 4) NOT NULL,
  `TaxAmt` DECIMAL(19, 4) NOT NULL,
  `Freight` DECIMAL(19, 4) NOT NULL,
  `TotalDue` DECIMAL(19, 4) NOT NULL,
  `Comment` STRING,
  `rowguid` STRING NOT NULL,
  `ModifiedDate` TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Sales order header information entity'
CLUSTER BY (`SalesOrderID`)
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
table_instance.set_column_tags("ModifiedDate", {'extract_mode': 'delta'})