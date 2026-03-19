# Databricks notebook source
# MAGIC %md
# MAGIC # DML for core.Sales_Customer_Customer
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['KundenNummer']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['KundenNummer', 'Vorname', 'Nachname', 'AddressType']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "datam8_campus_dev_fka", "Catalog Name")
dbutils.widgets.text("owner", "datam8_sample_dev_owner", "Owner")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# dbutils.widgets.dropdown(
#     "run_mode",
#     "INFO",
#     ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
#     "Run Mode",
# )
#dbutils.widgets.text("sandbox", "_", "Sandbox")


# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")


# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = "core"
data_product = "Sales"
data_module = "Customer"
table_name = "Customer"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
# print("Mode: %s" % run_mode)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# Reference to the fully-qualified target table (with backticks for catalog/schema/table).
table_name_ref = "`%(catalog)s`.`%(schema)s`.`%(table)s`" % {
    "catalog": catalog.name,
    "schema": zone,
    "table": full_table_name,
}

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute transformation functions

# COMMAND ----------

functions = {}

# COMMAND ----------
# MAGIC %md
# MAGIC #### CustomerNew

# COMMAND ----------

functions["CustomerNew"] = {
  "name": "transform_first_step",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
    {"dm8l": "/Stage/Sales/Customer/Customer"},
    {"dm8l": "/Stage/Sales/Customer/CustomerAddress"}
  ],
}

# COMMAND ----------

# MAGIC %run ./Customer_functions/CustomerNew

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
    "__BusinessFunction": F.lit("CustomerNew"),
    "__InsertTimestampUTC": F.current_timestamp(),
})
functions["CustomerNew"]["df"] = business_function  # noqa: F821

# COMMAND ----------
final_df = functions["CustomerNew"]["df"]

# COMMAND ----------

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.current_timestamp(),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write into target table

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ### Prepare merge statement

# COMMAND ----------

target_table = DeltaTable.forName(spark, table_name_ref)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
merge_builder = (
    target_table.alias("tgt")
    .merge(
        final_df.alias("src"),
        "tgt.`KundenNummer` <=> src.`KundenNummer`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`Vorname` <=> src.`Vorname`) OR NOT (tgt.`Nachname` <=> src.`Nachname`) OR NOT (tgt.`AddressType` <=> src.`AddressType`)
    """,
    set={
        "Vorname": 'src.`Vorname`', 
        "Nachname": 'src.`Nachname`', 
        "AddressType": 'src.`AddressType`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__BusinessFunction": 'src.__BusinessFunction', 
        "KundenNummer": 'src.`KundenNummer`', 
        "Vorname": 'src.`Vorname`', 
        "Nachname": 'src.`Nachname`', 
        "AddressType": 'src.`AddressType`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------