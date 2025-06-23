# Databricks notebook source
# MAGIC %md
# MAGIC # DML for raw.Sales_Order_SalesOrderHeader

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tables Tag

# COMMAND ----------

# DBTITLE 1,Get variable values


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
zone = raw_zone

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

if catalog.is_unity_enabled:
    TARGET_TABLE_PATH = "/Volumes/%(catalog)s/%(zone)s/__files/%(product)s/%(module)s/%(table)s" % {
        "catalog": catalog_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Order",
        "table": "SalesOrderHeader",
    }
else:
    TARGET_TABLE_PATH = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Order",
        "table": "SalesOrderHeader",
    }


# COMMAND ----------

# MAGIC %md
# MAGIC # Retrieve max delta criteria from 'raw'

# COMMAND ----------
try:
    dbutils.fs.ls(TARGET_TABLE_PATH)
    spark.read.format("delta").load(
        TARGET_TABLE_PATH).createOrReplaceTempView("raw_table")
    max_delta = spark.sql("SELECT MAX(ModifiedDate) FROM raw_table").first()[0]
    query_filter = f"WHERE ModifiedDate > '{max_delta}'"
except Exception as _:
    query_filter = ""
    # COMMAND ----------

# MAGIC %md
# MAGIC # Read data from MS SQL Server

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get & assign variable values

# COMMAND ----------

# DBTITLE 1,Get variable values
DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
database_connectionstring = spark.conf.get(
    "datam8.datasource.AdventureWorks.connectionstring")

SOURCE_TABLE_NAME = "[SalesLT].[SalesOrderHeader]"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define query

# COMMAND ----------

# DBTITLE 1,Define query with technical columns
pushdown_query = f"""
(
    SELECT
        *,
        -- Add technical columns
        CAST(YEAR(SYSUTCDATETIME()) AS SMALLINT) AS __Year,
        CAST(MONTH(SYSUTCDATETIME()) AS TINYINT) AS __Month,
        CAST(DAY(SYSUTCDATETIME()) AS TINYINT) AS __Day,
        SYSUTCDATETIME() AS __InsertTimestampUTC
    FROM {SOURCE_TABLE_NAME}
    {query_filter}
) AS tbl
"""
print(
    f"""Query:

{pushdown_query}"""
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create dataframe

# COMMAND ----------

# DBTITLE 1,Define dataframe
table_df = (spark.read
            .format("jdbc")
            .option("driver", DRIVER)
            .option("url", database_connectionstring)
            .option("dbtable", pushdown_query)
            # a column that can be used that has a uniformly distributed range of values
            # that can be used for parallelization
            # .option("partitionColumn", "AddressID")
            #
            # lowest value to pull data for with the partitionColumn
            # .option("lowerBound", "0")
            #
            # max value to pull data for with the partitionColumn
            # .option("upperBound", "100")
            #
            # number of partitions to distribute the data into. Do not set this very large (~hundreds)
            # .option("numPartitions", 8)
            .load()
            )
# COMMAND ----------

# MAGIC %md
# MAGIC # Write to 'raw'

# COMMAND ----------

(
    table_df.write.partitionBy(
        "__Year", "__Month", "__Day", "__InsertTimestampUTC")
    .mode("append")
    .format("delta")
    .option("mergeSchema", "true")
    .save(TARGET_TABLE_PATH)
)

# COMMAND ----------

# MAGIC %md
# MAGIC # Update extraction status

# COMMAND ----------

# DBTITLE 1,Update extraction status
count = table_df.count()
print(f"Extracted {count} records in extraction")
