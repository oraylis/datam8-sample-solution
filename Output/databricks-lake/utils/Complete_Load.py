# Databricks notebook source
# MAGIC %md
# MAGIC # Generic notebook to complete a load

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ./MigrationFramework

# COMMAND ----------

# DBTITLE 1,Initialize Logging Framework
# MAGIC %run ./LoggingFramework

# COMMAND ----------

dbutils.widgets.text("catalog", "aut0adl0dev", "Catalog")
dbutils.widgets.text("sandbox", "_", "Sandbox")
dbutils.widgets.dropdown(
    "run_mode",
    "INFO",
    ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "Run Mode",
)

# COMMAND ----------

env = spark.conf.get("datam8.environment")
catalog_name = dbutils.widgets.get("catalog")
owner = spark.conf.get("datam8.catalog.owner")
run_mode = dbutils.widgets.get("run_mode")
sandbox = dbutils.widgets.get("sandbox")

# COMMAND ----------

# DBTITLE 1,Get variable values
# configsif entity else none
data_lake_name = spark.conf.get("datam8.datalake.name", "aut0adl0dev")
container_name = spark.conf.get("datam8.datalake.container.name", "campus")
raw_zone = spark.conf.get("datam8.zone.raw.name", "raw")
stage_zone = spark.conf.get("datam8.zone.stage.name", "stage")
core_zone = spark.conf.get("datam8.zone.core.name", "core")
curated_zone = spark.conf.get("datam8.zone.curated.name", "curated")
logging_zone = spark.conf.get("datam8.zone.logging.name", "logging")
zone = logging_zone
base_location = "abfss://%(container)s@%(storage)s.dfs.core.windows.net/" % {
    "container": container_name,
    "storage": data_lake_name,
}

# static values
MAX_VALID_TO_DATE = "2999-12-31"


# COMMAND ----------

try:
    catalog = Catalog(catalog_name)
    print(f"catalog already exists: {catalog.name}")
except:
    spark.sql(
        f"CREATE CATALOG IF NOT EXISTS {catalog_name} MANAGED LOCATION '{base_location}/catalog_root'")
    spark.sql(f"ALTER CATALOG {catalog_name} OWNER TO `{owner}`")
    print(f"Catalog '{catalog_name}' created and ownership set to '{owner}'.")
    catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

if not catalog.is_unity_enabled:
    spark.conf.set(
        "fs.azure.account.key.%s.dfs.core.windows.net" % data_lake_name,
        dbutils.secrets.get(
            "aut0kvt0dev0campus", "fs-azure-account-key-%s-dfs-core-windows-net" % data_lake_name),
    )

# COMMAND ----------

# DBTITLE 1,Get load uuid, job name and target zone
logging_config: dict = LoggingFramework.get_value_dict()
logging_values: tuple = tuple(logging_config.values())

print("Load UUID: %s" % logging_config["load_uuid"])
print("Target Zone: %s" % logging_config["target_zone"])
print("Load Job Name: %s" % logging_config["load_job_name"])

# COMMAND ----------

# MAGIC %md
# MAGIC # Complete load

# COMMAND ----------

# DBTITLE 1,Complete load
LoggingFramework.complete_load(*logging_values)