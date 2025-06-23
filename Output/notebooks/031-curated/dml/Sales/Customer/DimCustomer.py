# Databricks notebook source
# MAGIC %md
# MAGIC # DML for curated.Sales_Customer_DimCustomer
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['CustomerSID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['DisplayName', 'AddressType', 'Address', 'PostalCode', 'CityName', 'CountryName']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F
from delta import DeltaTable  # noqa: F401

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
catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())
owner = spark.conf.get("datam8.catalog.owner")
run_mode = dbutils.widgets.get("run_mode")
sandbox = dbutils.widgets.get("sandbox")

# COMMAND ----------

# DBTITLE 1,Get variable values
# configsif entity else none 
data_lake_name = spark.conf.get("datam8.datalake.name", "datam80adl0dev")
container_name = spark.conf.get("datam8.datalake.container.name", "lakehousesample")
raw_zone = spark.conf.get("datam8.zone.raw.name", "raw")
stage_zone = spark.conf.get("datam8.zone.stage.name", "stage")
core_zone = spark.conf.get("datam8.zone.core.name", "core")
curated_zone = spark.conf.get("datam8.zone.curated.name", "curated")
zone = curated_zone

# static values
MAX_VALID_TO_DATE = "2999-12-31"
data_product = "Sales"
data_module = "Customer"
table_name = "DimCustomer"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

if not catalog.is_unity_enabled:
  spark.conf.set(
    "fs.azure.account.key.%s.dfs.core.windows.net" % data_lake_name,
    dbutils.secrets.get("akv_standard", "fs-azure-account-key-%s-dfs-core-windows-net" % data_lake_name),
  )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Execute functions

# COMMAND ----------

table_name = "`%(catalog)s`.`%(schema)s`.`%(table)s`" % {
  "catalog": catalog.name,
  "schema": curated_zone,
  "table": full_table_name,
}

functions = {}

# COMMAND ----------

# MAGIC %md
# MAGIC ### Customer_Compute

# COMMAND ----------

functions["Customer_Compute"] = {
  "name": "Customer_Compute",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
    {
      "dm8l": "/Core/Sales/Customer/Customer"
    },
    {
      "dm8l": "/Core/Sales/Customer/CustomerAddress"
    },
    {
      "dm8l": "/Core/Sales/Other/Address"
    }
  ]
}

# COMMAND ----------

# MAGIC %run ./DimCustomer_functions/Customer_Compute

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
  "__BusinessFunction": F.lit("Customer_Compute"),
  "__InsertTimestampUTC": F.current_timestamp(),
})
functions["Customer_Compute"]["df"] = business_function  # noqa: F501

# COMMAND ----------

(
    functions["Customer_Compute"]["df"]
    .withColumns({
        "__UpdateTimestampUTC": F.current_timestamp(),
    })
    .write.saveAsTable(table_name, mode="overwrite")
)

