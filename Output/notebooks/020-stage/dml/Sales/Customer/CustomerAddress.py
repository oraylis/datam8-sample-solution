# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Customer_CustomerAddress

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
data_module = "Customer"
table_name = "CustomerAddress"
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
        "module": "Customer",
        "table": "CustomerAddress",
    }
else:
    raw_path = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Customer",
        "table": "CustomerAddress",
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
    -- CustomerID
    TRY_CAST(`CustomerID` AS INT) AS `CustomerID`,
    CASE
        WHEN `CustomerID` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`CustomerID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `CustomerID_hasCastError`,
    -- AddressID
    TRY_CAST(`AddressID` AS INT) AS `AddressID`,
    CASE
        WHEN `AddressID` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`AddressID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `AddressID_hasCastError`,
    -- AddressType
    TRY_CAST(`AddressType` AS STRING) AS `AddressType`,
    CASE
        WHEN `AddressType` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`AddressType` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `AddressType_hasCastError`,
    -- rowguid
    TRY_CAST(`rowguid` AS STRING) AS `rowguid`,
    CASE
        WHEN `rowguid` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`rowguid` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `rowguid_hasCastError`,
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
    CustomerID,
    AddressID,
    AddressType,
    rowguid,
    ModifiedDate,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    CustomerID_hasCastError > 0
    OR AddressID_hasCastError > 0
    OR AddressType_hasCastError > 0
    OR rowguid_hasCastError > 0
    OR ModifiedDate_hasCastError > 0
""")

# COMMAND ----------

poison_df_count = poison_df.count()
if poison_df_count > 0:
    (
        poison_df.write.partitionBy(
            "__Year", "__Month", "__Day", "__InsertTimestampUTC")
        .mode("append")
        .parquet(f"abfss://{container_name}@{data_lake_name}.dfs.core.windows.net/{stage_zone}/Sales/Customer/CustomerAddress_poison")
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
    CustomerID,
    AddressID,
    AddressType,
    rowguid,
    ModifiedDate,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    CustomerID_hasCastError == 0
    AND AddressID_hasCastError == 0
    AND AddressType_hasCastError == 0
    AND rowguid_hasCastError == 0
    AND ModifiedDate_hasCastError == 0
""")
clean_df.createOrReplaceTempView("clean_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Insert into 'stage'

# COMMAND ----------

spark.sql("""
INSERT INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_CustomerAddress`
TABLE clean_df
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
})
