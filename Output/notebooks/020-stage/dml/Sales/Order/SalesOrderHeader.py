# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Order_SalesOrderHeader

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------


# DBTITLE 1,Initialize Migration Framework
# MAGIC %run ../../../../000-utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("sandbox", "_", "Sandbox")
dbutils.widgets.dropdown(
    "run_mode",
    "INFO",
    ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "Run Mode",
)

# COMMAND ----------

env = spark.conf.get("datam8.environment")
catalog_name = spark.conf.get(
    "datam8.catalog.name", spark.catalog.currentCatalog())
owner = spark.conf.get("datam8.catalog.owner")
run_mode = dbutils.widgets.get("run_mode")
sandbox = dbutils.widgets.get("sandbox")

# COMMAND ----------

# DBTITLE 1,Get variable values
# configsif entity else none
data_lake_name = spark.conf.get("datam8.datalake.name", "datam80adl0dev")
container_name = spark.conf.get(
    "datam8.datalake.container.name", "lakehousesample")
raw_zone = spark.conf.get("datam8.zone.raw.name", "raw")
stage_zone = spark.conf.get("datam8.zone.stage.name", "stage")
core_zone = spark.conf.get("datam8.zone.core.name", "core")
curated_zone = spark.conf.get("datam8.zone.curated.name", "curated")
zone = stage_zone

# static values
MAX_VALID_TO_DATE = "2999-12-31"
data_product = "Sales"
data_module = "Order"
table_name = "SalesOrderHeader"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

if not catalog.is_unity_enabled:
    spark.conf.set(
        "fs.azure.account.key.%s.dfs.core.windows.net" % data_lake_name,
        dbutils.secrets.get(
            "akv_standard", "fs-azure-account-key-%s-dfs-core-windows-net" % data_lake_name),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC # Read from RAW
# MAGIC ## Source Table tags

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get latest data from 'stage'

# COMMAND ----------

last_partition_df = spark.sql(
    f"""
    select nvl(max(__InsertTimestampUTC), to_timestamp('1970-01-01', 'yyyy-MM-dd')) as LastPartition
    from {stage_zone}.{full_table_name}
"""
)
last_partition = last_partition_df.first()[0]
print(f"Last partition in '{stage_zone}': {last_partition}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get delta from RAW

# COMMAND ----------

if catalog.is_unity_enabled:
    raw_path = "/Volumes/%(catalog)s/%(zone)s/__files/%(product)s/%(module)s/%(table)s" % {
        "catalog": catalog_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Order",
        "table": "SalesOrderHeader",
    }
else:
    raw_path = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Order",
        "table": "SalesOrderHeader",
    }

raw_df = spark.read.format("delta") \
    .load(raw_path) \
    .filter("__InsertTimestampUTC > '%s'" % last_partition)

# COMMAND ----------

# MAGIC %md
# MAGIC # Write to STAGE

# COMMAND ----------

# MAGIC %md
# MAGIC ## Enforce data types
# MAGIC * Enforce data types
# MAGIC * Identify records with non enforcable data types

# COMMAND ----------

raw_df.createOrReplaceTempView("raw_df")

# COMMAND ----------

typed_table_df = spark.sql(
    f"""
SELECT
    -- Table columns
    -- SalesOrderID
    TRY_CAST(`SalesOrderID` AS INT) AS `SalesOrderID`,
    CASE
        WHEN `SalesOrderID` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`SalesOrderID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `SalesOrderID_hasCastError`,
    -- RevisionNumber
    TRY_CAST(`RevisionNumber` AS TINYINT) AS `RevisionNumber`,
    CASE
        WHEN `RevisionNumber` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`RevisionNumber` AS TINYINT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `RevisionNumber_hasCastError`,
    -- OrderDate
    TRY_CAST(`OrderDate` AS TIMESTAMP) AS `OrderDate`,
    CASE
        WHEN `OrderDate` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`OrderDate` AS TIMESTAMP) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `OrderDate_hasCastError`,
    -- DueDate
    TRY_CAST(`DueDate` AS TIMESTAMP) AS `DueDate`,
    CASE
        WHEN `DueDate` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`DueDate` AS TIMESTAMP) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `DueDate_hasCastError`,
    -- ShipDate
    TRY_CAST(`ShipDate` AS TIMESTAMP) AS `ShipDate`,
    CASE
        WHEN `ShipDate` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`ShipDate` AS TIMESTAMP) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `ShipDate_hasCastError`,
    -- Status
    TRY_CAST(`Status` AS TINYINT) AS `Status`,
    CASE
        WHEN `Status` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`Status` AS TINYINT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Status_hasCastError`,
    -- OnlineOrderFlag
    TRY_CAST(`OnlineOrderFlag` AS BOOLEAN) AS `OnlineOrderFlag`,
    CASE
        WHEN `OnlineOrderFlag` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`OnlineOrderFlag` AS BOOLEAN) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `OnlineOrderFlag_hasCastError`,
    -- SalesOrderNumber
    TRY_CAST(`SalesOrderNumber` AS STRING) AS `SalesOrderNumber`,
    CASE
        WHEN `SalesOrderNumber` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`SalesOrderNumber` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `SalesOrderNumber_hasCastError`,
    -- PurchaseOrderNumber
    TRY_CAST(`PurchaseOrderNumber` AS STRING) AS `PurchaseOrderNumber`,
    CASE
        WHEN `PurchaseOrderNumber` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`PurchaseOrderNumber` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `PurchaseOrderNumber_hasCastError`,
    -- AccountNumber
    TRY_CAST(`AccountNumber` AS STRING) AS `AccountNumber`,
    CASE
        WHEN `AccountNumber` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`AccountNumber` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `AccountNumber_hasCastError`,
    -- CustomerID
    TRY_CAST(`CustomerID` AS INT) AS `CustomerID`,
    CASE
        WHEN `CustomerID` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`CustomerID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `CustomerID_hasCastError`,
    -- ShipToAddressID
    TRY_CAST(`ShipToAddressID` AS INT) AS `ShipToAddressID`,
    CASE
        WHEN `ShipToAddressID` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`ShipToAddressID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `ShipToAddressID_hasCastError`,
    -- BillToAddressID
    TRY_CAST(`BillToAddressID` AS INT) AS `BillToAddressID`,
    CASE
        WHEN `BillToAddressID` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`BillToAddressID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `BillToAddressID_hasCastError`,
    -- ShipMethod
    TRY_CAST(`ShipMethod` AS STRING) AS `ShipMethod`,
    CASE
        WHEN `ShipMethod` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`ShipMethod` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `ShipMethod_hasCastError`,
    -- CreditCardApprovalCode
    TRY_CAST(`CreditCardApprovalCode` AS STRING) AS `CreditCardApprovalCode`,
    CASE
        WHEN `CreditCardApprovalCode` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`CreditCardApprovalCode` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `CreditCardApprovalCode_hasCastError`,
    -- SubTotal
    TRY_CAST(`SubTotal` AS DECIMAL(19,4)) AS `SubTotal`,
    CASE
        WHEN `SubTotal` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`SubTotal` AS DECIMAL(19,4)) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `SubTotal_hasCastError`,
    -- TaxAmt
    TRY_CAST(`TaxAmt` AS DECIMAL(19,4)) AS `TaxAmt`,
    CASE
        WHEN `TaxAmt` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`TaxAmt` AS DECIMAL(19,4)) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `TaxAmt_hasCastError`,
    -- Freight
    TRY_CAST(`Freight` AS DECIMAL(19,4)) AS `Freight`,
    CASE
        WHEN `Freight` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`Freight` AS DECIMAL(19,4)) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Freight_hasCastError`,
    -- TotalDue
    TRY_CAST(`TotalDue` AS DECIMAL(19,4)) AS `TotalDue`,
    CASE
        WHEN `TotalDue` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`TotalDue` AS DECIMAL(19,4)) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `TotalDue_hasCastError`,
    -- Comment
    TRY_CAST(`Comment` AS STRING) AS `Comment`,
    CASE
        WHEN `Comment` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Comment` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Comment_hasCastError`,
    -- ModifiedDate
    TRY_CAST(`ModifiedDate` AS TIMESTAMP) AS `ModifiedDate`,
    CASE
        WHEN `ModifiedDate` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`ModifiedDate` AS TIMESTAMP) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `ModifiedDate_hasCastError`,
    -- Technical columns
    CAST(__YEAR AS SMALLINT) AS __Year,
    CAST(__MONTH AS TINYINT) AS __Month,
    CAST(__DAY AS TINYINT) AS __Day,
    CAST(__InsertTimestampUTC AS TIMESTAMP) AS __InsertTimestampUTC
FROM raw_df
"""
)
typed_table_df.createOrReplaceTempView("typed_table_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extract poison records
# MAGIC * Extract poison records
# MAGIC * Write to poison table

# COMMAND ----------

poison_df = spark.sql("""
SELECT
    -- Table columns
    SalesOrderID,
    RevisionNumber,
    OrderDate,
    DueDate,
    ShipDate,
    Status,
    OnlineOrderFlag,
    SalesOrderNumber,
    PurchaseOrderNumber,
    AccountNumber,
    CustomerID,
    ShipToAddressID,
    BillToAddressID,
    ShipMethod,
    CreditCardApprovalCode,
    SubTotal,
    TaxAmt,
    Freight,
    TotalDue,
    Comment,
    ModifiedDate,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    SalesOrderID_hasCastError > 0
    OR RevisionNumber_hasCastError > 0
    OR OrderDate_hasCastError > 0
    OR DueDate_hasCastError > 0
    OR ShipDate_hasCastError > 0
    OR Status_hasCastError > 0
    OR OnlineOrderFlag_hasCastError > 0
    OR SalesOrderNumber_hasCastError > 0
    OR PurchaseOrderNumber_hasCastError > 0
    OR AccountNumber_hasCastError > 0
    OR CustomerID_hasCastError > 0
    OR ShipToAddressID_hasCastError > 0
    OR BillToAddressID_hasCastError > 0
    OR ShipMethod_hasCastError > 0
    OR CreditCardApprovalCode_hasCastError > 0
    OR SubTotal_hasCastError > 0
    OR TaxAmt_hasCastError > 0
    OR Freight_hasCastError > 0
    OR TotalDue_hasCastError > 0
    OR Comment_hasCastError > 0
    OR ModifiedDate_hasCastError > 0
""")

# COMMAND ----------

poison_df_count = poison_df.count()
if poison_df_count > 0:
    (
        poison_df.write.partitionBy(
            "__Year", "__Month", "__Day", "__InsertTimestampUTC")
        .mode("append")
        .parquet(f"abfss://{container_name}@{data_lake_name}.dfs.core.windows.net/{stage_zone}/Sales/Order/SalesOrderHeader_poison")
    )
    print(
        "Extracted %s poison records in extraction" % (poison_df_count)
    )
else:
    print("No poison records present")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extract valid records
# MAGIC * Extract valid records
# MAGIC * Write to target table

# COMMAND ----------

clean_df = spark.sql("""
SELECT
    -- Table columns
    SalesOrderID,
    RevisionNumber,
    OrderDate,
    DueDate,
    ShipDate,
    Status,
    OnlineOrderFlag,
    SalesOrderNumber,
    PurchaseOrderNumber,
    AccountNumber,
    CustomerID,
    ShipToAddressID,
    BillToAddressID,
    ShipMethod,
    CreditCardApprovalCode,
    SubTotal,
    TaxAmt,
    Freight,
    TotalDue,
    Comment,
    ModifiedDate,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    SalesOrderID_hasCastError == 0
    AND RevisionNumber_hasCastError == 0
    AND OrderDate_hasCastError == 0
    AND DueDate_hasCastError == 0
    AND ShipDate_hasCastError == 0
    AND Status_hasCastError == 0
    AND OnlineOrderFlag_hasCastError == 0
    AND SalesOrderNumber_hasCastError == 0
    AND PurchaseOrderNumber_hasCastError == 0
    AND AccountNumber_hasCastError == 0
    AND CustomerID_hasCastError == 0
    AND ShipToAddressID_hasCastError == 0
    AND BillToAddressID_hasCastError == 0
    AND ShipMethod_hasCastError == 0
    AND CreditCardApprovalCode_hasCastError == 0
    AND SubTotal_hasCastError == 0
    AND TaxAmt_hasCastError == 0
    AND Freight_hasCastError == 0
    AND TotalDue_hasCastError == 0
    AND Comment_hasCastError == 0
    AND ModifiedDate_hasCastError == 0
""")
clean_df.createOrReplaceTempView("clean_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Insert into 'stage'

# COMMAND ----------

spark.sql("""
INSERT INTO `%(catalog)s`.`%(database)s`.`Sales_Order_SalesOrderHeader`
TABLE clean_df
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
})
