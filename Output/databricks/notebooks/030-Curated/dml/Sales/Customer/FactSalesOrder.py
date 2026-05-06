# Databricks notebook source
# MAGIC %md
# MAGIC # DML for gold.Sales_Customer_FactSalesOrder
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: []
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['CustomerSID', 'ShipDateID', 'TotalCosts']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ../../../../../../../utils/MigrationFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("schema_prefix", "", "Schema Prefix")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
schema_prefix = dbutils.widgets.get("schema_prefix")
job_run_id = dbutils.widgets.get("job_run_id")

# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = f"{schema_prefix}gold" if schema_prefix else "gold"
data_product = "Sales"
data_module = "Customer"
table_name = "FactSalesOrder"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)

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
# MAGIC #### FactSalesOrder

# COMMAND ----------

functions["FactSalesOrder"] = {
  "name": "transform_sales_orders",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
  ],
}

# COMMAND ----------

# MAGIC %run ./FactSalesOrder_functions/FactSalesOrder

# COMMAND ----------

business_function = business_function.withColumns({  # noqa: F821
    "__BusinessFunction": F.lit("FactSalesOrder"),
    "__InsertTimestampUTC": F.current_timestamp(),
})
functions["FactSalesOrder"]["df"] = business_function  # noqa: F821

# COMMAND ----------
final_df = functions["FactSalesOrder"]["df"]

# COMMAND ----------

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.current_timestamp(),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write into target table

# COMMAND ----------
final_write_df = final_df.select(
    "__InsertTimestampUTC", 
    "__UpdateTimestampUTC", 
    "__BusinessFunction", 
    "CustomerSID", 
    "ShipDateID", 
    "TotalCosts"
)
final_write_df.write.saveAsTable(table_name_ref, mode="overwrite")

# COMMAND ----------