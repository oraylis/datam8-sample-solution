# Databricks notebook source
# MAGIC %md
# MAGIC # DML for raw.Sales_Customer_DIMTIME

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
data_module = "Customer"
table_name = "DIMTIME"
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
        "module": "Customer",
        "table": "DIMTIME",
    }
else:
    TARGET_TABLE_PATH = "abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/%(product)s/%(module)s/%(table)s" % {  # noqa: E501
        "container": container_name,
        "lake": data_lake_name,
        "zone": raw_zone,
        "product": "Sales",
        "module": "Customer",
        "table": "DIMTIME",
    }


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
