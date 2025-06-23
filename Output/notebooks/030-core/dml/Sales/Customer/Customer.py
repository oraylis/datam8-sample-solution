# Databricks notebook source
# MAGIC %md
# MAGIC # DML for core.Sales_Customer_Customer
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['_CustomerBK'] # noqa: E501
# MAGIC - __SCD0 columns__: ['CustomerID'] # noqa: E501
# MAGIC - __SCD1 columns__: ['CompanyName', 'CustomerEMail', 'DisplayName', 'FirstName', 'LastName'] # noqa: E501
# MAGIC - __SCD2 columns__: ['CompanyHistName', 'CustomerHistEMail'] # noqa: E501

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
zone = core_zone

# static values
MAX_VALID_TO_DATE = "2999-12-31"
data_product = "Sales"
data_module = "Customer"
table_name = "Customer"
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
# MAGIC # Read from STAGE

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get latest data from CORE

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp for source table '/Stage/Sales/Customer/Customer_DE'

# COMMAND ----------

max_stage: dict = {}
max_stage["Stage_Sales_Customer_Customer_DE"] = spark.sql("""
SELECT
  NVL(MAX(__InsertTimestampStageUTC), CAST("1970-01-01" AS TIMESTAMP)) AS MaxStage
FROM `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer`
WHERE __SourceTable_BK = "%(source_locator)s"
""" % {
    "catalog": catalog.name,
    "database": core_zone,
    "source_locator": "/Stage/Sales/Customer/Customer_DE",
}).first()[0]

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp for source table '/Stage/Sales/Customer/Customer_EN'

# COMMAND ----------

max_stage: dict = {}
max_stage["Stage_Sales_Customer_Customer_EN"] = spark.sql("""
SELECT
  NVL(MAX(__InsertTimestampStageUTC), CAST("1970-01-01" AS TIMESTAMP)) AS MaxStage
FROM `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer`
WHERE __SourceTable_BK = "%(source_locator)s"
""" % {
    "catalog": catalog.name,
    "database": core_zone,
    "source_locator": "/Stage/Sales/Customer/Customer_EN",
}).first()[0]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get delta from STAGE

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Delta from source table '/Stage/Sales/Customer/Customer_DE'

# COMMAND ----------

source_delta_1_df = spark.sql("""
SELECT
    -- business columns
    `KundenID` AS `CustomerID`,
    `Vorname` AS `FirstName`,
    `Nachname` AS `LastName`,
    `Firma` AS `CompanyName`,
    `Email` AS `CustomerEMail`,
    -- technical columns
    "%(source_locator)s" AS __SourceTable_BK,
    __InsertTimestampUTC AS __ValidFrom,
    to_timestamp('%(max_valid_to_date)s') AS __ValidTo,
    current_timestamp() AS __InserTimestampUTC,
    current_timestamp() AS __UpdateTimestampUTC,
    __InsertTimestampUTC AS __InsertTimestampStageUTC
FROM `%(catalog)s`.`%(database)s`.`%(table)s`
WHERE __InsertTimestampUTC > '%(max_stage_timestamp)s'
  AND __InsertTimestampUTC = (
    SELECT max(__InsertTimestampUTC)
    FROM `%(catalog)s`.`%(database)s`.`%(table)s`
  )
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
    "table": "Sales_Customer_Customer_DE",
    "max_valid_to_date": MAX_VALID_TO_DATE,
    "max_stage_timestamp": max_stage["Stage_Sales_Customer_Customer_DE"],
    "source_locator": "/Stage/Sales/Customer/Customer_DE",
})

source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Delta from source table '/Stage/Sales/Customer/Customer_EN'

# COMMAND ----------

source_delta_2_df = spark.sql("""
SELECT
    -- business columns
    `CustomerID` AS `CustomerID`,
    `FirstName` AS `FirstName`,
    `LastName` AS `LastName`,
    `CompanyName` AS `CompanyName`,
    `EmailAddress` AS `CustomerEMail`,
    -- technical columns
    "%(source_locator)s" AS __SourceTable_BK,
    __InsertTimestampUTC AS __ValidFrom,
    to_timestamp('%(max_valid_to_date)s') AS __ValidTo,
    current_timestamp() AS __InserTimestampUTC,
    current_timestamp() AS __UpdateTimestampUTC,
    __InsertTimestampUTC AS __InsertTimestampStageUTC
FROM `%(catalog)s`.`%(database)s`.`%(table)s`
WHERE __InsertTimestampUTC > '%(max_stage_timestamp)s'
  AND __InsertTimestampUTC = (
    SELECT max(__InsertTimestampUTC)
    FROM `%(catalog)s`.`%(database)s`.`%(table)s`
  )
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
    "table": "Sales_Customer_Customer_EN",
    "max_valid_to_date": MAX_VALID_TO_DATE,
    "max_stage_timestamp": max_stage["Stage_Sales_Customer_Customer_EN"],
    "source_locator": "/Stage/Sales/Customer/Customer_EN",
})

source_delta_df_list.append(source_delta_2_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Union deltas from sources

# COMMAND ----------

for idx, df in enumerate(source_delta_df_list):
    if idx == 0:
        union_df = df
    else:
        union_df = union_df.union(df)

union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC # Apply computed columns

# COMMAND ----------

enriched_df = spark.sql("""
SELECT *
  , CustomerID AS _CustomerBK
  , Concat(LastName, ', ', FirstName) AS DisplayName
  , CompanyName AS CompanyHistName
  , CustomerEMail AS CustomerHistEMail
FROM union_df
""")
enriched_df.createOrReplaceTempView("enriched_df")

# COMMAND ----------

# MAGIC %md
# MAGIC # Merge into core

# COMMAND ----------
# MAGIC %md
# MAGIC ## Update old SCD 2 records

# COMMAND ----------

spark.sql("""
MERGE INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer` AS tgt
USING enriched_df AS src
ON
  tgt.`_CustomerBK` <=> src.`_CustomerBK`
  AND tgt.__SourceTable_BK <=> src.__SourceTable_BK
WHEN MATCHED
  AND tgt.__ValidTo = to_timestamp("%(max_valid_to_date)s")
  -- SCD 2 columns
  AND (
       NOT tgt.`CompanyHistName` <=> src.`CompanyHistName`
    OR NOT tgt.`CustomerHistEMail` <=> src.`CustomerHistEMail`
  )
THEN UPDATE SET
  tgt.__ValidTo = src.__ValidFrom,
  tgt.__UpdateTimestampUTC = src.__UpdateTimestampUTC
""" % {
    "catalog": catalog.name,
    "database": core_zone,
    "max_valid_to_date": MAX_VALID_TO_DATE,
}).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Insert new records

# COMMAND ----------

spark.sql("""
MERGE INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer` AS tgt
USING enriched_df AS src
ON
  tgt.`_CustomerBK` <=> src.`_CustomerBK`
  AND tgt.__SourceTable_BK <=> src.__SourceTable_BK
  AND tgt.__ValidTo = to_timestamp('%(max_valid_to_date)s')
WHEN NOT MATCHED
THEN INSERT (
  `_CustomerBK`,
  `CustomerID`,
  `CompanyHistName`,
  `CompanyName`,
  `CustomerEMail`,
  `CustomerHistEMail`,
  `DisplayName`,
  `FirstName`,
  `LastName`,
  -- technical columns
  __SourceTable_BK,
  __ValidFrom,
  __ValidTo,
  __InsertTimestampUTC,
  __UpdateTimestampUTC,
  __InsertTimestampStageUTC,
) VALUES (
  src.`_CustomerBK`,
  src.`CustomerID`,
  src.`CompanyHistName`,
  src.`CompanyName`,
  src.`CustomerEMail`,
  src.`CustomerHistEMail`,
  src.`DisplayName`,
  src.`FirstName`,
  src.`LastName`,
  -- technical columns
  src.__SourceTable_BK,
  src.__ValidFrom,
  src.__ValidTo,
  src.__InserTimestampUTC,
  src.__UpdateTimestampUTC,
  src.__InsertTimestampStageUTC
)
""" % {
    "catalog": catalog.name,
    "database": core_zone,
    "max_valid_to_date": MAX_VALID_TO_DATE,
}).display()

# COMMAND ----------
# MAGIC %md
# MAGIC ## Update SCD 1 records

# COMMAND ----------

spark.sql("""
MERGE INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer` AS tgt
USING enriched_df AS src
ON
  tgt.`_CustomerBK` <=> src.`_CustomerBK`
  AND tgt.__SourceTable_BK <=> src.__SourceTable_BK
WHEN MATCHED
  -- SCD 1 columns
  AND (
       NOT tgt.`CompanyName` <=> src.`CompanyName`
    OR NOT tgt.`CustomerEMail` <=> src.`CustomerEMail`
    OR NOT tgt.`DisplayName` <=> src.`DisplayName`
    OR NOT tgt.`FirstName` <=> src.`FirstName`
    OR NOT tgt.`LastName` <=> src.`LastName`
  )
THEN UPDATE SET
  tgt.`CompanyName` = src.`CompanyName`,
  tgt.`CustomerEMail` = src.`CustomerEMail`,
  tgt.`DisplayName` = src.`DisplayName`,
  tgt.`FirstName` = src.`FirstName`,
  tgt.`LastName` = src.`LastName`,
  tgt.__UpdateTimestampUTC = src.__UpdateTimestampUTC
""" % {
    "catalog": catalog.name,
    "database": core_zone,
}).display()

# COMMAND ----------
