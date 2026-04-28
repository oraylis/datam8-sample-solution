# Databricks notebook source
# MAGIC %md
# MAGIC # DML for bronze.Sales_Order_SalesOrderHeader
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['SalesOrderID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['SalesOrderID', 'RevisionNumber', 'OrderDate', 'DueDate', 'ShipDate', 'Status', 'OnlineOrderFlag', 'SalesOrderNumber', 'PurchaseOrderNumber', 'AccountNumber', 'CustomerID', 'ShipToAddressID', 'BillToAddressID', 'ShipMethod', 'CreditCardApprovalCode', 'SubTotal', 'TaxAmt', 'Freight', 'TotalDue', 'Comment', 'rowguid', 'ModifiedDate']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
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
MAX_VALID_TO_DATE = "9999-12-31"
zone = f"{schema_prefix}bronze" if schema_prefix else "bronze"
data_product = "Sales"
data_module = "Order"
table_name = "SalesOrderHeader"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)
source_zone = "raw"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# Reference to the fully-qualified target table (with backticks for catalog/schema/table).
table_name_ref = "`%(catalog)s`.`%(schema)s`.`%(table)s`" % {
    "catalog": catalog.name,
    "schema": zone,
    "table": full_table_name,
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Process captured snapshots

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp in target table

# COMMAND ----------

max_external: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Order_SalesOrderHeader'

# COMMAND ----------

max_external["raw_Sales_Order_SalesOrderHeader"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampRawUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxRaw
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Order_SalesOrderHeader'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.{schema_prefix}raw.Sales_Order_SalesOrderHeader")
    .filter(F.col("__InsertTimestampUTC") > max_external["raw_Sales_Order_SalesOrderHeader"])
    .selectExpr(
        "`SalesOrderID`",
        "`RevisionNumber`",
        "`OrderDate`",
        "`DueDate`",
        "`ShipDate`",
        "`Status`",
        "`OnlineOrderFlag`",
        "`SalesOrderNumber`",
        "`PurchaseOrderNumber`",
        "`AccountNumber`",
        "`CustomerID`",
        "`ShipToAddressID`",
        "`BillToAddressID`",
        "`ShipMethod`",
        "`CreditCardApprovalCode`",
        "`SubTotal`",
        "`TaxAmt`",
        "`Freight`",
        "`TotalDue`",
        "`Comment`",
        "`rowguid`",
        "`ModifiedDate`",
        "'SalesOrderHeader' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__InsertTimestampUTC AS __InsertTimestampRawUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

if not source_delta_df_list:
    raise ValueError("No delta sources configured for this entity.")

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)

latest_snapshot_key_cols = ["SalesOrderID"]
if latest_snapshot_key_cols:
    # Keep only the latest snapshot per business key to avoid duplicate records from external feeds.
    latest_snapshot_window = Window.partitionBy(*latest_snapshot_key_cols).orderBy(
        F.col("__InsertTimestampRawUTC").desc(),
    )
    union_df = (
        union_df
        .withColumn("__dm8_latest_snapshot_rank", F.row_number().over(latest_snapshot_window))
        .where(F.col("__dm8_latest_snapshot_rank") == 1)
        .drop("__dm8_latest_snapshot_rank")
    )

union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to BRONZE

# COMMAND ----------# COMMAND ----------

# MAGIC %md
# MAGIC ### Prepare merge statement

# COMMAND ----------

target_table = DeltaTable.forName(spark, table_name_ref)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
merge_builder = (
    target_table.alias("tgt")
    .merge(
        union_df.alias("src"),
        "tgt.`SalesOrderID` <=> src.`SalesOrderID`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`RevisionNumber` <=> src.`RevisionNumber`) OR NOT (tgt.`OrderDate` <=> src.`OrderDate`) OR NOT (tgt.`DueDate` <=> src.`DueDate`) OR NOT (tgt.`ShipDate` <=> src.`ShipDate`) OR NOT (tgt.`Status` <=> src.`Status`) OR NOT (tgt.`OnlineOrderFlag` <=> src.`OnlineOrderFlag`) OR NOT (tgt.`SalesOrderNumber` <=> src.`SalesOrderNumber`) OR NOT (tgt.`PurchaseOrderNumber` <=> src.`PurchaseOrderNumber`) OR NOT (tgt.`AccountNumber` <=> src.`AccountNumber`) OR NOT (tgt.`CustomerID` <=> src.`CustomerID`) OR NOT (tgt.`ShipToAddressID` <=> src.`ShipToAddressID`) OR NOT (tgt.`BillToAddressID` <=> src.`BillToAddressID`) OR NOT (tgt.`ShipMethod` <=> src.`ShipMethod`) OR NOT (tgt.`CreditCardApprovalCode` <=> src.`CreditCardApprovalCode`) OR NOT (tgt.`SubTotal` <=> src.`SubTotal`) OR NOT (tgt.`TaxAmt` <=> src.`TaxAmt`) OR NOT (tgt.`Freight` <=> src.`Freight`) OR NOT (tgt.`TotalDue` <=> src.`TotalDue`) OR NOT (tgt.`Comment` <=> src.`Comment`) OR NOT (tgt.`rowguid` <=> src.`rowguid`) OR NOT (tgt.`ModifiedDate` <=> src.`ModifiedDate`)
    """,
    set={
        "RevisionNumber": 'src.`RevisionNumber`', 
        "OrderDate": 'src.`OrderDate`', 
        "DueDate": 'src.`DueDate`', 
        "ShipDate": 'src.`ShipDate`', 
        "Status": 'src.`Status`', 
        "OnlineOrderFlag": 'src.`OnlineOrderFlag`', 
        "SalesOrderNumber": 'src.`SalesOrderNumber`', 
        "PurchaseOrderNumber": 'src.`PurchaseOrderNumber`', 
        "AccountNumber": 'src.`AccountNumber`', 
        "CustomerID": 'src.`CustomerID`', 
        "ShipToAddressID": 'src.`ShipToAddressID`', 
        "BillToAddressID": 'src.`BillToAddressID`', 
        "ShipMethod": 'src.`ShipMethod`', 
        "CreditCardApprovalCode": 'src.`CreditCardApprovalCode`', 
        "SubTotal": 'src.`SubTotal`', 
        "TaxAmt": 'src.`TaxAmt`', 
        "Freight": 'src.`Freight`', 
        "TotalDue": 'src.`TotalDue`', 
        "Comment": 'src.`Comment`', 
        "rowguid": 'src.`rowguid`', 
        "ModifiedDate": 'src.`ModifiedDate`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__SourceTable": 'src.__SourceTable', 
        "__InsertTimestampRawUTC": 'src.__InsertTimestampRawUTC', 
        "SalesOrderID": 'src.`SalesOrderID`', 
        "RevisionNumber": 'src.`RevisionNumber`', 
        "OrderDate": 'src.`OrderDate`', 
        "DueDate": 'src.`DueDate`', 
        "ShipDate": 'src.`ShipDate`', 
        "Status": 'src.`Status`', 
        "OnlineOrderFlag": 'src.`OnlineOrderFlag`', 
        "SalesOrderNumber": 'src.`SalesOrderNumber`', 
        "PurchaseOrderNumber": 'src.`PurchaseOrderNumber`', 
        "AccountNumber": 'src.`AccountNumber`', 
        "CustomerID": 'src.`CustomerID`', 
        "ShipToAddressID": 'src.`ShipToAddressID`', 
        "BillToAddressID": 'src.`BillToAddressID`', 
        "ShipMethod": 'src.`ShipMethod`', 
        "CreditCardApprovalCode": 'src.`CreditCardApprovalCode`', 
        "SubTotal": 'src.`SubTotal`', 
        "TaxAmt": 'src.`TaxAmt`', 
        "Freight": 'src.`Freight`', 
        "TotalDue": 'src.`TotalDue`', 
        "Comment": 'src.`Comment`', 
        "rowguid": 'src.`rowguid`', 
        "ModifiedDate": 'src.`ModifiedDate`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------