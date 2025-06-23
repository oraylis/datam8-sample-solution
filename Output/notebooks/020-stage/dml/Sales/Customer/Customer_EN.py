# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Customer_Customer_EN

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
table_name = "Customer_EN"
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
        "table": "Customer_EN",
    }
else:
    raw_path = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Customer",
        "table": "Customer_EN",
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
    -- NameStyle
    TRY_CAST(`NameStyle` AS BOOLEAN) AS `NameStyle`,
    CASE
        WHEN `NameStyle` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`NameStyle` AS BOOLEAN) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `NameStyle_hasCastError`,
    -- Title
    TRY_CAST(`Title` AS STRING) AS `Title`,
    CASE
        WHEN `Title` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Title` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Title_hasCastError`,
    -- FirstName
    TRY_CAST(`FirstName` AS STRING) AS `FirstName`,
    CASE
        WHEN `FirstName` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`FirstName` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `FirstName_hasCastError`,
    -- MiddleName
    TRY_CAST(`MiddleName` AS STRING) AS `MiddleName`,
    CASE
        WHEN `MiddleName` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`MiddleName` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `MiddleName_hasCastError`,
    -- LastName
    TRY_CAST(`LastName` AS STRING) AS `LastName`,
    CASE
        WHEN `LastName` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`LastName` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `LastName_hasCastError`,
    -- Suffix
    TRY_CAST(`Suffix` AS STRING) AS `Suffix`,
    CASE
        WHEN `Suffix` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Suffix` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Suffix_hasCastError`,
    -- CompanyName
    TRY_CAST(`CompanyName` AS STRING) AS `CompanyName`,
    CASE
        WHEN `CompanyName` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`CompanyName` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `CompanyName_hasCastError`,
    -- SalesPerson
    TRY_CAST(`SalesPerson` AS STRING) AS `SalesPerson`,
    CASE
        WHEN `SalesPerson` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`SalesPerson` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `SalesPerson_hasCastError`,
    -- EmailAddress
    TRY_CAST(`EmailAddress` AS STRING) AS `EmailAddress`,
    CASE
        WHEN `EmailAddress` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`EmailAddress` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `EmailAddress_hasCastError`,
    -- Phone
    TRY_CAST(`Phone` AS STRING) AS `Phone`,
    CASE
        WHEN `Phone` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Phone` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Phone_hasCastError`,
    -- PasswordHash
    TRY_CAST(`PasswordHash` AS STRING) AS `PasswordHash`,
    CASE
        WHEN `PasswordHash` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`PasswordHash` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `PasswordHash_hasCastError`,
    -- PasswordSalt
    TRY_CAST(`PasswordSalt` AS STRING) AS `PasswordSalt`,
    CASE
        WHEN `PasswordSalt` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`PasswordSalt` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `PasswordSalt_hasCastError`,
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
    NameStyle,
    Title,
    FirstName,
    MiddleName,
    LastName,
    Suffix,
    CompanyName,
    SalesPerson,
    EmailAddress,
    Phone,
    PasswordHash,
    PasswordSalt,
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
    OR NameStyle_hasCastError > 0
    OR Title_hasCastError > 0
    OR FirstName_hasCastError > 0
    OR MiddleName_hasCastError > 0
    OR LastName_hasCastError > 0
    OR Suffix_hasCastError > 0
    OR CompanyName_hasCastError > 0
    OR SalesPerson_hasCastError > 0
    OR EmailAddress_hasCastError > 0
    OR Phone_hasCastError > 0
    OR PasswordHash_hasCastError > 0
    OR PasswordSalt_hasCastError > 0
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
        .parquet(f"abfss://{container_name}@{data_lake_name}.dfs.core.windows.net/{stage_zone}/Sales/Customer/Customer_EN_poison")
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
    NameStyle,
    Title,
    FirstName,
    MiddleName,
    LastName,
    Suffix,
    CompanyName,
    SalesPerson,
    EmailAddress,
    Phone,
    PasswordHash,
    PasswordSalt,
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
    AND NameStyle_hasCastError == 0
    AND Title_hasCastError == 0
    AND FirstName_hasCastError == 0
    AND MiddleName_hasCastError == 0
    AND LastName_hasCastError == 0
    AND Suffix_hasCastError == 0
    AND CompanyName_hasCastError == 0
    AND SalesPerson_hasCastError == 0
    AND EmailAddress_hasCastError == 0
    AND Phone_hasCastError == 0
    AND PasswordHash_hasCastError == 0
    AND PasswordSalt_hasCastError == 0
    AND rowguid_hasCastError == 0
    AND ModifiedDate_hasCastError == 0
""")
clean_df.createOrReplaceTempView("clean_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Insert into 'stage'

# COMMAND ----------

spark.sql("""
INSERT INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer_EN`
TABLE clean_df
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
})
