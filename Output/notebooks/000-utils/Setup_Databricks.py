# Databricks notebook source
# MAGIC %md
# MAGIC # Initial setup

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------


# DBTITLE 1,Initialize Migration Framework
# MAGIC %run ./MigrationFramework

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
zone = logging_zone

# static values
MAX_VALID_TO_DATE = "2999-12-31"


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

base_location = "abfss://%(container)s@%(storage)s.dfs.core.windows.net/" % {
    "container": container_name,
    "storage": data_lake_name,
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create databases & volumes

# COMMAND ----------

zones = [
    "raw",
    "stage",
    "core",
    "curated",
]

for zone in zones:
    location = "%(base)s/%(database)s" % {
        "base": base_location,
        "database": zone,
    }
    # catalog.create_schema_if_not_exists(zone, location=location)
    # TODO: define managed or unmanaged?
    catalog.create_schema_if_not_exists(zone)
    catalog.set_schema_owner(zone, owner=owner)

catalog.create_volume_if_not_exists(
    volume_name="__files",
    schema_name="raw",
    # location=base_location + "raw/__files",  # TODO: define managed or unmanaged?
    owner=owner
)
