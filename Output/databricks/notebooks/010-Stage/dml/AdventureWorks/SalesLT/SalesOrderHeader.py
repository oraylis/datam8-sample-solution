# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.AdventureWorks_SalesLT_SalesOrderHeader
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
# MAGIC %run ../../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("date_start", "2000-01-01", "Calendar start")
dbutils.widgets.text("date_end", "2030-12-31", "Calendar end")
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
sample_date_start = dbutils.widgets.get("date_start")
sample_date_end = dbutils.widgets.get("date_end")
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
if not catalog_name or not owner:
    raise ValueError("Set catalog_name and owner explicitly before running this notebook")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")


# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = "stage"
data_product = "AdventureWorks"
data_module = "SalesLT"
table_name = "SalesOrderHeader"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)
source_zone = "raw"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
# print("Mode: %s" % run_mode)

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

max_raw: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'AdventureWorks_SalesLT_SalesOrderHeader'

# COMMAND ----------

max_raw["Raw_AdventureWorks_SalesLT_SalesOrderHeader"] = spark.sql(f"""
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
# MAGIC #### 'AdventureWorks_SalesLT_SalesOrderHeader'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.raw.AdventureWorks_SalesLT_SalesOrderHeader")
    .filter(F.col("__InsertTimestampUTC") > max_raw["Raw_AdventureWorks_SalesLT_SalesOrderHeader"])
    .selectExpr(
        "TRY_CAST(`SalesOrderID` AS INT) AS `SalesOrderID`",
        "TRY_CAST(`RevisionNumber` AS SMALLINT) AS `RevisionNumber`",
        "TRY_CAST(`OrderDate` AS TIMESTAMP) AS `OrderDate`",
        "TRY_CAST(`DueDate` AS TIMESTAMP) AS `DueDate`",
        "TRY_CAST(`ShipDate` AS TIMESTAMP) AS `ShipDate`",
        "TRY_CAST(`Status` AS SMALLINT) AS `Status`",
        "TRY_CAST(`OnlineOrderFlag` AS BOOLEAN) AS `OnlineOrderFlag`",
        "TRY_CAST(`SalesOrderNumber` AS STRING) AS `SalesOrderNumber`",
        "TRY_CAST(`PurchaseOrderNumber` AS STRING) AS `PurchaseOrderNumber`",
        "TRY_CAST(`AccountNumber` AS STRING) AS `AccountNumber`",
        "TRY_CAST(`CustomerID` AS INT) AS `CustomerID`",
        "TRY_CAST(`ShipToAddressID` AS INT) AS `ShipToAddressID`",
        "TRY_CAST(`BillToAddressID` AS INT) AS `BillToAddressID`",
        "TRY_CAST(`ShipMethod` AS STRING) AS `ShipMethod`",
        "TRY_CAST(`CreditCardApprovalCode` AS STRING) AS `CreditCardApprovalCode`",
        "TRY_CAST(`SubTotal` AS DECIMAL(19,4)) AS `SubTotal`",
        "TRY_CAST(`TaxAmt` AS DECIMAL(19,4)) AS `TaxAmt`",
        "TRY_CAST(`Freight` AS DECIMAL(19,4)) AS `Freight`",
        "TRY_CAST(`TotalDue` AS DECIMAL(19,4)) AS `TotalDue`",
        "TRY_CAST(`Comment` AS STRING) AS `Comment`",
        "TRY_CAST(`rowguid` AS STRING) AS `rowguid`",
        "TRY_CAST(`ModifiedDate` AS TIMESTAMP) AS `ModifiedDate`",
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
# MAGIC ## Write changes to STAGE

# COMMAND ----------

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