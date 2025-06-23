# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Customer_Customer_DE

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
table_name = "Customer_DE"
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
        "table": "Customer_DE",
    }
else:
    raw_path = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Customer",
        "table": "Customer_DE",
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
    -- KundenID
    TRY_CAST(`KundenID` AS INT) AS `KundenID`,
    CASE
        WHEN `KundenID` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`KundenID` AS INT) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `KundenID_hasCastError`,
    -- NamensTyp
    TRY_CAST(`NamensTyp` AS BOOLEAN) AS `NamensTyp`,
    CASE
        WHEN `NamensTyp` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`NamensTyp` AS BOOLEAN) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `NamensTyp_hasCastError`,
    -- Titel
    TRY_CAST(`Titel` AS STRING) AS `Titel`,
    CASE
        WHEN `Titel` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Titel` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Titel_hasCastError`,
    -- Vorname
    TRY_CAST(`Vorname` AS STRING) AS `Vorname`,
    CASE
        WHEN `Vorname` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`Vorname` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Vorname_hasCastError`,
    -- Nameszusatz1
    TRY_CAST(`Nameszusatz1` AS STRING) AS `Nameszusatz1`,
    CASE
        WHEN `Nameszusatz1` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Nameszusatz1` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Nameszusatz1_hasCastError`,
    -- Nachname
    TRY_CAST(`Nachname` AS STRING) AS `Nachname`,
    CASE
        WHEN `Nachname` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`Nachname` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Nachname_hasCastError`,
    -- Namenszusatz2
    TRY_CAST(`Namenszusatz2` AS STRING) AS `Namenszusatz2`,
    CASE
        WHEN `Namenszusatz2` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Namenszusatz2` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Namenszusatz2_hasCastError`,
    -- Firma
    TRY_CAST(`Firma` AS STRING) AS `Firma`,
    CASE
        WHEN `Firma` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Firma` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Firma_hasCastError`,
    -- Verkaeufer
    TRY_CAST(`Verkaeufer` AS STRING) AS `Verkaeufer`,
    CASE
        WHEN `Verkaeufer` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Verkaeufer` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Verkaeufer_hasCastError`,
    -- Email
    TRY_CAST(`Email` AS STRING) AS `Email`,
    CASE
        WHEN `Email` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Email` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Email_hasCastError`,
    -- Telefon
    TRY_CAST(`Telefon` AS STRING) AS `Telefon`,
    CASE
        WHEN `Telefon` IS NULL THEN 0 -- NULLable COLUMN
        
        WHEN TRY_CAST(`Telefon` AS STRING) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `Telefon_hasCastError`,
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
    -- GeaendertAm
    TRY_CAST(`GeaendertAm` AS TIMESTAMP) AS `GeaendertAm`,
    CASE
        WHEN `GeaendertAm` IS NULL THEN  1 -- NOT NULL COLUMN
        WHEN TRY_CAST(`GeaendertAm` AS TIMESTAMP) IS NULL THEN 1 -- NOT ABLE TO CAST
        ELSE 0 -- ALL GOOD
    END AS `GeaendertAm_hasCastError`,
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
    KundenID,
    NamensTyp,
    Titel,
    Vorname,
    Nameszusatz1,
    Nachname,
    Namenszusatz2,
    Firma,
    Verkaeufer,
    Email,
    Telefon,
    PasswordHash,
    PasswordSalt,
    rowguid,
    GeaendertAm,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    KundenID_hasCastError > 0
    OR NamensTyp_hasCastError > 0
    OR Titel_hasCastError > 0
    OR Vorname_hasCastError > 0
    OR Nameszusatz1_hasCastError > 0
    OR Nachname_hasCastError > 0
    OR Namenszusatz2_hasCastError > 0
    OR Firma_hasCastError > 0
    OR Verkaeufer_hasCastError > 0
    OR Email_hasCastError > 0
    OR Telefon_hasCastError > 0
    OR PasswordHash_hasCastError > 0
    OR PasswordSalt_hasCastError > 0
    OR rowguid_hasCastError > 0
    OR GeaendertAm_hasCastError > 0
""")

# COMMAND ----------

poison_df_count = poison_df.count()
if poison_df_count > 0:
    (
        poison_df.write.partitionBy(
            "__Year", "__Month", "__Day", "__InsertTimestampUTC")
        .mode("append")
        .parquet(f"abfss://{container_name}@{data_lake_name}.dfs.core.windows.net/{stage_zone}/Sales/Customer/Customer_DE_poison")
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
    KundenID,
    NamensTyp,
    Titel,
    Vorname,
    Nameszusatz1,
    Nachname,
    Namenszusatz2,
    Firma,
    Verkaeufer,
    Email,
    Telefon,
    PasswordHash,
    PasswordSalt,
    rowguid,
    GeaendertAm,
    -- Technical columns
    __Year,
    __Month,
    __Day,
    __InsertTimestampUTC
FROM typed_table_df
WHERE
    KundenID_hasCastError == 0
    AND NamensTyp_hasCastError == 0
    AND Titel_hasCastError == 0
    AND Vorname_hasCastError == 0
    AND Nameszusatz1_hasCastError == 0
    AND Nachname_hasCastError == 0
    AND Namenszusatz2_hasCastError == 0
    AND Firma_hasCastError == 0
    AND Verkaeufer_hasCastError == 0
    AND Email_hasCastError == 0
    AND Telefon_hasCastError == 0
    AND PasswordHash_hasCastError == 0
    AND PasswordSalt_hasCastError == 0
    AND rowguid_hasCastError == 0
    AND GeaendertAm_hasCastError == 0
""")
clean_df.createOrReplaceTempView("clean_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Insert into 'stage'

# COMMAND ----------

spark.sql("""
INSERT INTO `%(catalog)s`.`%(database)s`.`Sales_Customer_Customer_DE`
TABLE clean_df
""" % {
    "catalog": catalog.name,
    "database": stage_zone,
})
