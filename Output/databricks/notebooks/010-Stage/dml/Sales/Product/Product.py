# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Product_Product
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['ProductID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['ProductID', 'Name', 'ProductNumber', 'Color', 'StandardCost', 'ListPrice', 'Size', 'Weight', 'ProductCategoryID', 'ProductModelID', 'SellStartDate', 'SellEndDate', 'DiscontinuedDate', 'ThumbNailPhoto', 'ThumbnailPhotoFileName', 'rowguid', 'ModifiedDate']
# MAGIC - __SCD2 columns__: []

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: F401
from pyspark.sql.window import Window  # noqa: F401
from delta import DeltaTable  # noqa: F401
from datetime import datetime, timezone

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
zone = f"{schema_prefix}stage" if schema_prefix else "stage"
data_product = "Sales"
data_module = "Product"
table_name = "Product"
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
load_timestamp_utc = datetime.now(timezone.utc).replace(tzinfo=None)
load_timestamp_utc_sql = load_timestamp_utc.strftime("%Y-%m-%d %H:%M:%S.%f")

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
# MAGIC #### 'Sales_Product_Product'

# COMMAND ----------

max_source["raw_Sales_Product_Product"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampSourceUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxSource
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Product_Product'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.{schema_prefix}raw.Sales_Product_Product")
    .filter(F.col("__InsertTimestampUTC") > F.lit(max_source["raw_Sales_Product_Product"]))
    .selectExpr(
        "try_cast(`ProductID` as int) AS `ProductID`",
        "try_cast(`Name` as string) AS `Name`",
        "try_cast(`ProductNumber` as string) AS `ProductNumber`",
        "try_cast(`Color` as string) AS `Color`",
        "try_cast(`StandardCost` as decimal) AS `StandardCost`",
        "try_cast(`ListPrice` as decimal) AS `ListPrice`",
        "try_cast(`Size` as string) AS `Size`",
        "try_cast(`Weight` as decimal) AS `Weight`",
        "try_cast(`ProductCategoryID` as int) AS `ProductCategoryID`",
        "try_cast(`ProductModelID` as int) AS `ProductModelID`",
        "try_cast(`SellStartDate` as timestamp) AS `SellStartDate`",
        "try_cast(`SellEndDate` as timestamp) AS `SellEndDate`",
        "try_cast(`DiscontinuedDate` as timestamp) AS `DiscontinuedDate`",
        "try_cast(`ThumbNailPhoto` as string) AS `ThumbNailPhoto`",
        "try_cast(`ThumbnailPhotoFileName` as string) AS `ThumbnailPhotoFileName`",
        "try_cast(`rowguid` as string) AS `rowguid`",
        "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
        "'Product' AS __SourceTable",
        f"CAST('{load_timestamp_utc_sql}' AS TIMESTAMP) AS __InsertTimestampUTC",
        f"CAST('{load_timestamp_utc_sql}' AS TIMESTAMP) AS __UpdateTimestampUTC",
        "__UpdateTimestampUTC AS __InsertTimestampSourceUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)
latest_snapshot_key_cols = ["ProductID"]
if latest_snapshot_key_cols:
    # Keep only the latest snapshot per business key to avoid duplicate records from source feeds.
    latest_snapshot_window = Window.partitionBy(*latest_snapshot_key_cols).orderBy(
        F.col("__InsertTimestampSourceUTC").desc(),
    )
    union_df = (
        union_df
        .withColumn("__dm8_latest_snapshot_rank", F.row_number().over(latest_snapshot_window))
        .where(F.col("__dm8_latest_snapshot_rank") == 1)
        .drop("__dm8_latest_snapshot_rank")
    )

if union_df.isEmpty():
    print("No new source rows found. Skip write to target table.")
    dbutils.notebook.exit("SKIPPED_EMPTY_SOURCE_DELTA")

union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to STAGE

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
        "tgt.`ProductID` <=> src.`ProductID`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`Name` <=> src.`Name`) OR NOT (tgt.`ProductNumber` <=> src.`ProductNumber`) OR NOT (tgt.`Color` <=> src.`Color`) OR NOT (tgt.`StandardCost` <=> src.`StandardCost`) OR NOT (tgt.`ListPrice` <=> src.`ListPrice`) OR NOT (tgt.`Size` <=> src.`Size`) OR NOT (tgt.`Weight` <=> src.`Weight`) OR NOT (tgt.`ProductCategoryID` <=> src.`ProductCategoryID`) OR NOT (tgt.`ProductModelID` <=> src.`ProductModelID`) OR NOT (tgt.`SellStartDate` <=> src.`SellStartDate`) OR NOT (tgt.`SellEndDate` <=> src.`SellEndDate`) OR NOT (tgt.`DiscontinuedDate` <=> src.`DiscontinuedDate`) OR NOT (tgt.`ThumbNailPhoto` <=> src.`ThumbNailPhoto`) OR NOT (tgt.`ThumbnailPhotoFileName` <=> src.`ThumbnailPhotoFileName`) OR NOT (tgt.`rowguid` <=> src.`rowguid`) OR NOT (tgt.`ModifiedDate` <=> src.`ModifiedDate`)
    """,
    set={
        "Name": 'src.`Name`', 
        "ProductNumber": 'src.`ProductNumber`', 
        "Color": 'src.`Color`', 
        "StandardCost": 'src.`StandardCost`', 
        "ListPrice": 'src.`ListPrice`', 
        "Size": 'src.`Size`', 
        "Weight": 'src.`Weight`', 
        "ProductCategoryID": 'src.`ProductCategoryID`', 
        "ProductModelID": 'src.`ProductModelID`', 
        "SellStartDate": 'src.`SellStartDate`', 
        "SellEndDate": 'src.`SellEndDate`', 
        "DiscontinuedDate": 'src.`DiscontinuedDate`', 
        "ThumbNailPhoto": 'src.`ThumbNailPhoto`', 
        "ThumbnailPhotoFileName": 'src.`ThumbnailPhotoFileName`', 
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
        "ProductID": 'src.`ProductID`', 
        "Name": 'src.`Name`', 
        "ProductNumber": 'src.`ProductNumber`', 
        "Color": 'src.`Color`', 
        "StandardCost": 'src.`StandardCost`', 
        "ListPrice": 'src.`ListPrice`', 
        "Size": 'src.`Size`', 
        "Weight": 'src.`Weight`', 
        "ProductCategoryID": 'src.`ProductCategoryID`', 
        "ProductModelID": 'src.`ProductModelID`', 
        "SellStartDate": 'src.`SellStartDate`', 
        "SellEndDate": 'src.`SellEndDate`', 
        "DiscontinuedDate": 'src.`DiscontinuedDate`', 
        "ThumbNailPhoto": 'src.`ThumbNailPhoto`', 
        "ThumbnailPhotoFileName": 'src.`ThumbnailPhotoFileName`', 
        "rowguid": 'src.`rowguid`', 
        "ModifiedDate": 'src.`ModifiedDate`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------

# COMMAND ----------

# DBTITLE 1,Update load status
record_count = spark.table(table_name_ref).filter(
    F.col("__UpdateTimestampUTC") == F.lit(load_timestamp_utc)
).count()
print(f"Loaded {record_count} records into target table")