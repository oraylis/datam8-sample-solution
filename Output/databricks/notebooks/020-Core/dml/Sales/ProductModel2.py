# Databricks notebook source
# MAGIC %md
# MAGIC # DML for silver.Sales_ProductModel2
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['ProductModelID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['ProductModelID', 'Name', 'CatalogDescription', 'rowguid', 'ModifiedDate']
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
zone = f"{schema_prefix}silver" if schema_prefix else "silver"
data_product = "Sales"
data_module = "default"
table_name = "ProductModel2"
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
# MAGIC ## Process source snapshots

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp in target table

# COMMAND ----------

max_source: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Product_ProductModel'

# COMMAND ----------

max_source["bronze_Sales_Product_ProductModel"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampSourceUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxSource
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
WHERE __SourceTable = 'ProductModel'
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Product_ProductModel'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.{schema_prefix}bronze.Sales_Product_ProductModel")
    .filter(F.col("__UpdateTimestampUTC") > F.lit(max_source["bronze_Sales_Product_ProductModel"]))
    .selectExpr(
        "try_cast(`ProductModelID` as int) AS `ProductModelID`",
        "try_cast(`Name` as string) AS `Name`",
        "try_cast(`CatalogDescription` as string) AS `CatalogDescription`",
        "try_cast(`rowguid` as string) AS `rowguid`",
        "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
        "'ProductModel' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__UpdateTimestampUTC AS __InsertTimestampSourceUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)
union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to SILVER

# COMMAND ----------# COMMAND ----------

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
        union_df.alias("src"),
        "tgt.`ProductModelID` <=> src.`ProductModelID`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`Name` <=> src.`Name`) OR NOT (tgt.`CatalogDescription` <=> src.`CatalogDescription`) OR NOT (tgt.`rowguid` <=> src.`rowguid`) OR NOT (tgt.`ModifiedDate` <=> src.`ModifiedDate`)
    """,
    set={
        "Name": 'src.`Name`', 
        "CatalogDescription": 'src.`CatalogDescription`', 
        "rowguid": 'src.`rowguid`', 
        "ModifiedDate": 'src.`ModifiedDate`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__SourceTable": 'src.__SourceTable', 
        "__InsertTimestampSourceUTC": 'src.__InsertTimestampSourceUTC', 
        "ProductModelID": 'src.`ProductModelID`', 
        "Name": 'src.`Name`', 
        "CatalogDescription": 'src.`CatalogDescription`', 
        "rowguid": 'src.`rowguid`', 
        "ModifiedDate": 'src.`ModifiedDate`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------