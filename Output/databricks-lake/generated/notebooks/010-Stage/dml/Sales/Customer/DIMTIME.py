# Databricks notebook source
# MAGIC %md
# MAGIC # DML for stage.Sales_Customer_DIMTIME
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['TIMEKEY']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['TIMEKEY', 'FULLDATEALTERNATEKEY', 'DAYNUMBEROFWEEK', 'ENGLISHDAYNAMEOFWEEK', 'SPANISHDAYNAMEOFWEEK', 'FRENCHDAYNAMEOFWEEK', 'DAYNUMBEROFMONTH', 'DAYNUMBEROFYEAR', 'WEEKNUMBEROFYEAR', 'ENGLISHMONTHNAME', 'SPANISHMONTHNAME', 'FRENCHMONTHNAME', 'MONTHNUMBEROFYEAR', 'CALENDARQUARTER', 'CALENDARYEAR', 'CALENDARSEMESTER', 'FISCALQUARTER', 'FISCALYEAR', 'FISCALSEMESTER']
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
zone = "stage"
data_product = "Sales"
data_module = "Customer"
table_name = "DIMTIME"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)
source_zone = "raw"

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
# MAGIC ## Process captured snapshots

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp in target table

# COMMAND ----------

max_raw: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_dimtime'

# COMMAND ----------

max_raw["Raw_Sales_Customer_dimtime"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampRawUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxRaw
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_dimtime'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.raw.Sales_Customer_dimtime")
    .filter(F.col("__InsertTimestampUTC") > max_raw["Raw_Sales_Customer_dimtime"])
    .selectExpr(
        "`TIMEKEY`",
        "`FULLDATEALTERNATEKEY`",
        "`DAYNUMBEROFWEEK`",
        "`ENGLISHDAYNAMEOFWEEK`",
        "`SPANISHDAYNAMEOFWEEK`",
        "`FRENCHDAYNAMEOFWEEK`",
        "`DAYNUMBEROFMONTH`",
        "`DAYNUMBEROFYEAR`",
        "`WEEKNUMBEROFYEAR`",
        "`ENGLISHMONTHNAME`",
        "`SPANISHMONTHNAME`",
        "`FRENCHMONTHNAME`",
        "`MONTHNUMBEROFYEAR`",
        "`CALENDARQUARTER`",
        "`CALENDARYEAR`",
        "`CALENDARSEMESTER`",
        "`FISCALQUARTER`",
        "`FISCALYEAR`",
        "`FISCALSEMESTER`",
        "'dimtime' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__InsertTimestampUTC AS __InsertTimestampRawUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

if not source_delta_df_list:
    raise ValueError("No delta sources configured for this entity.")

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)

latest_snapshot_key_cols = ["TIMEKEY"]
if latest_snapshot_key_cols:
    # Keep only the latest snapshot per business key to avoid duplicate records from external feeds.
    latest_snapshot_window = Window.partitionBy(*latest_snapshot_key_cols).orderBy(
        F.col("__InsertTimestampRawUTC").desc(),
    )
    union_df = (
        union_df
        .withColumn("__dm8_latest_snapshot_rank", F.row_number().over(latest_snapshot_window))
        .where(F.col("__dm8_latest_snapshot_rank") == 1)
        .drop("__dm8_latest_snapshot_rank")
    )

union_df.createOrReplaceTempView("union_df")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write changes to STAGE

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
        union_df.alias("src"),
        "tgt.`TIMEKEY` <=> src.`TIMEKEY`",
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="""
        NOT (tgt.`FULLDATEALTERNATEKEY` <=> src.`FULLDATEALTERNATEKEY`) OR NOT (tgt.`DAYNUMBEROFWEEK` <=> src.`DAYNUMBEROFWEEK`) OR NOT (tgt.`ENGLISHDAYNAMEOFWEEK` <=> src.`ENGLISHDAYNAMEOFWEEK`) OR NOT (tgt.`SPANISHDAYNAMEOFWEEK` <=> src.`SPANISHDAYNAMEOFWEEK`) OR NOT (tgt.`FRENCHDAYNAMEOFWEEK` <=> src.`FRENCHDAYNAMEOFWEEK`) OR NOT (tgt.`DAYNUMBEROFMONTH` <=> src.`DAYNUMBEROFMONTH`) OR NOT (tgt.`DAYNUMBEROFYEAR` <=> src.`DAYNUMBEROFYEAR`) OR NOT (tgt.`WEEKNUMBEROFYEAR` <=> src.`WEEKNUMBEROFYEAR`) OR NOT (tgt.`ENGLISHMONTHNAME` <=> src.`ENGLISHMONTHNAME`) OR NOT (tgt.`SPANISHMONTHNAME` <=> src.`SPANISHMONTHNAME`) OR NOT (tgt.`FRENCHMONTHNAME` <=> src.`FRENCHMONTHNAME`) OR NOT (tgt.`MONTHNUMBEROFYEAR` <=> src.`MONTHNUMBEROFYEAR`) OR NOT (tgt.`CALENDARQUARTER` <=> src.`CALENDARQUARTER`) OR NOT (tgt.`CALENDARYEAR` <=> src.`CALENDARYEAR`) OR NOT (tgt.`CALENDARSEMESTER` <=> src.`CALENDARSEMESTER`) OR NOT (tgt.`FISCALQUARTER` <=> src.`FISCALQUARTER`) OR NOT (tgt.`FISCALYEAR` <=> src.`FISCALYEAR`) OR NOT (tgt.`FISCALSEMESTER` <=> src.`FISCALSEMESTER`)
    """,
    set={
        "FULLDATEALTERNATEKEY": 'src.`FULLDATEALTERNATEKEY`', 
        "DAYNUMBEROFWEEK": 'src.`DAYNUMBEROFWEEK`', 
        "ENGLISHDAYNAMEOFWEEK": 'src.`ENGLISHDAYNAMEOFWEEK`', 
        "SPANISHDAYNAMEOFWEEK": 'src.`SPANISHDAYNAMEOFWEEK`', 
        "FRENCHDAYNAMEOFWEEK": 'src.`FRENCHDAYNAMEOFWEEK`', 
        "DAYNUMBEROFMONTH": 'src.`DAYNUMBEROFMONTH`', 
        "DAYNUMBEROFYEAR": 'src.`DAYNUMBEROFYEAR`', 
        "WEEKNUMBEROFYEAR": 'src.`WEEKNUMBEROFYEAR`', 
        "ENGLISHMONTHNAME": 'src.`ENGLISHMONTHNAME`', 
        "SPANISHMONTHNAME": 'src.`SPANISHMONTHNAME`', 
        "FRENCHMONTHNAME": 'src.`FRENCHMONTHNAME`', 
        "MONTHNUMBEROFYEAR": 'src.`MONTHNUMBEROFYEAR`', 
        "CALENDARQUARTER": 'src.`CALENDARQUARTER`', 
        "CALENDARYEAR": 'src.`CALENDARYEAR`', 
        "CALENDARSEMESTER": 'src.`CALENDARSEMESTER`', 
        "FISCALQUARTER": 'src.`FISCALQUARTER`', 
        "FISCALYEAR": 'src.`FISCALYEAR`', 
        "FISCALSEMESTER": 'src.`FISCALSEMESTER`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__InsertTimestampUTC": 'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC', 
        "__SourceTable": 'src.__SourceTable', 
        "__InsertTimestampRawUTC": 'src.__InsertTimestampRawUTC', 
        "TIMEKEY": 'src.`TIMEKEY`', 
        "FULLDATEALTERNATEKEY": 'src.`FULLDATEALTERNATEKEY`', 
        "DAYNUMBEROFWEEK": 'src.`DAYNUMBEROFWEEK`', 
        "ENGLISHDAYNAMEOFWEEK": 'src.`ENGLISHDAYNAMEOFWEEK`', 
        "SPANISHDAYNAMEOFWEEK": 'src.`SPANISHDAYNAMEOFWEEK`', 
        "FRENCHDAYNAMEOFWEEK": 'src.`FRENCHDAYNAMEOFWEEK`', 
        "DAYNUMBEROFMONTH": 'src.`DAYNUMBEROFMONTH`', 
        "DAYNUMBEROFYEAR": 'src.`DAYNUMBEROFYEAR`', 
        "WEEKNUMBEROFYEAR": 'src.`WEEKNUMBEROFYEAR`', 
        "ENGLISHMONTHNAME": 'src.`ENGLISHMONTHNAME`', 
        "SPANISHMONTHNAME": 'src.`SPANISHMONTHNAME`', 
        "FRENCHMONTHNAME": 'src.`FRENCHMONTHNAME`', 
        "MONTHNUMBEROFYEAR": 'src.`MONTHNUMBEROFYEAR`', 
        "CALENDARQUARTER": 'src.`CALENDARQUARTER`', 
        "CALENDARYEAR": 'src.`CALENDARYEAR`', 
        "CALENDARSEMESTER": 'src.`CALENDARSEMESTER`', 
        "FISCALQUARTER": 'src.`FISCALQUARTER`', 
        "FISCALYEAR": 'src.`FISCALYEAR`', 
        "FISCALSEMESTER": 'src.`FISCALSEMESTER`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------