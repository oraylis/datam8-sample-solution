# Databricks notebook source
# MAGIC %md
# MAGIC # DML for curated.Sales_Orders_FactSalesOrder
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['CustomerSID', 'ShipDateID']
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

dbutils.widgets.text("date_start", "2000-01-01", "Calendar start")
dbutils.widgets.text("date_end", "2030-12-31", "Calendar end")
dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("owner", "", "Owner")
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
sample_date_start = dbutils.widgets.get("date_start")
sample_date_end = dbutils.widgets.get("date_end")
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")
if not catalog_name or not owner:
    raise ValueError("Set catalog_name and owner explicitly before running this notebook")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")


# static values
MAX_VALID_TO_DATE = "9999-12-31"
zone = "curated"
data_product = "Sales"
data_module = "Orders"
table_name = "FactSalesOrder"
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
# MAGIC #### FactSalesOrder

# COMMAND ----------

functions["FactSalesOrder"] = {
  "name": "transform_sales_orders",
  "merge_type": "replace",
  "frequency": "no_restriction",
  "source": [
    {"dm8l": "/Stage/AdventureWorks/SalesLT/SalesOrderHeader"},
    {"dm8l": "/Curated/MasterData/Customer/DimCustomer"}
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
# MAGIC %md
# MAGIC ### Lookup dimensions

# COMMAND ----------
dimension_df_1 = (
    spark.table(f"{catalog.name}.curated.MasterData_Customer_DimCustomer")
    .select(
        F.col("CustomerID").alias("dim_DimCustomer__CustomerID"), 
        F.col("SourceSystem").alias("dim_DimCustomer__SourceSystem"), 
        F.col("CustomerSID").alias("dim_DimCustomer__CustomerSID")
    )
)

final_df = (
    final_df.alias("fact")
    .join(
        dimension_df_1.alias("dim_DimCustomer"),
        (F.col("fact.CustomerID") == F.col("dim_DimCustomer__CustomerID")) & 
        (F.col("fact.SourceSystem") == F.col("dim_DimCustomer__SourceSystem"))
        ,
        "left",
    )
)

final_df = final_df.withColumn(
    "CustomerSID",
    F.coalesce(
        F.col("dim_DimCustomer__CustomerSID"),
        F.lit(-1),
    ),
)

final_df = final_df.drop(
    "dim_DimCustomer__CustomerID", 
    "dim_DimCustomer__SourceSystem", 
    "dim_DimCustomer__CustomerSID"
)

final_df = final_df.withColumns({
    "__UpdateTimestampUTC": F.current_timestamp(),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write into target table

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
final_write_df = final_df.select(
    "__InsertTimestampUTC", 
    "__UpdateTimestampUTC", 
    "__BusinessFunction", 
    "CustomerSID", 
    "ShipDateID", 
    "TotalCosts"
)
if final_write_df.limit(1).count() > 0:
    final_write_df.write.saveAsTable(table_name_ref, mode="overwrite")
else:
    print("No transformed rows to write; keeping the existing target table unchanged.")

# COMMAND ----------