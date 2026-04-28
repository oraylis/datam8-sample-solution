# Databricks notebook source
# MAGIC %md
# MAGIC # DML for bronze.Sales_Customer_Customer
# MAGIC History configuration of this entity
# MAGIC - __Business Key Columns__: ['KundenID']
# MAGIC - __SCD0 columns__: []
# MAGIC - __SCD1 columns__: ['KundenID', 'NamensTyp', 'Titel', 'Vorname', 'Nameszusatz1', 'Namenszusatz2', 'Firma', 'Verkaeufer', 'Email', 'Telefon', 'GeaendertAm', 'KundenName']
# MAGIC - __SCD2 columns__: ['Nachname']

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
zone = f"{schema_prefix}bronze" if schema_prefix else "bronze"
data_product = "Sales"
data_module = "Customer"
table_name = "Customer"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)
source_zone = "raw"

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
# MAGIC ## Process captured snapshots

# COMMAND ----------

# MAGIC %md
# MAGIC ### Max timestamp in target table

# COMMAND ----------

max_external: dict = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_Customer_DE'

# COMMAND ----------

max_external["raw_Sales_Customer_Customer_DE"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampExternalUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxExternal
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_Customer_EN'

# COMMAND ----------

max_external["raw_Sales_Customer_Customer_EN"] = spark.sql(f"""
SELECT
  COALESCE(MAX(__InsertTimestampExternalUTC), CAST('1970-01-01' AS TIMESTAMP)) AS MaxExternal
FROM `{catalog.name}`.`{zone}`.`{full_table_name}`
""").first()[0]

# COMMAND ----------

source_delta_df_list = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### Extraction from source tables

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_Customer_DE'

# COMMAND ----------

source_delta_1_df = (
    spark.table(f"{catalog.name}.{schema_prefix}raw.Sales_Customer_Customer_DE")
    .filter(F.col("__InsertTimestampUTC") > max_external["raw_Sales_Customer_Customer_DE"])
    .selectExpr(
        "`KundenID`",
        "`NamensTyp`",
        "`Titel`",
        "`Vorname`",
        "`Nameszusatz1`",
        "`Nachname`",
        "`Namenszusatz2`",
        "`Firma`",
        "`Verkaeufer`",
        "`Email`",
        "`Telefon`",
        "`GeaendertAm`",
        "concat(Nachname, ' ', Vorname) AS `KundenName`",
        "'Customer_DE' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__InsertTimestampUTC AS __InsertTimestampExternalUTC"
    )
)
source_delta_df_list.append(source_delta_1_df)

# COMMAND ----------

# MAGIC %md
# MAGIC #### 'Sales_Customer_Customer_EN'

# COMMAND ----------

source_delta_2_df = (
    spark.table(f"{catalog.name}.{schema_prefix}raw.Sales_Customer_Customer_EN")
    .filter(F.col("__InsertTimestampUTC") > max_external["raw_Sales_Customer_Customer_EN"])
    .selectExpr(
        "`KundenID`",
        "`NamensTyp`",
        "`Titel`",
        "`Vorname`",
        "`Nameszusatz1`",
        "`Nachname`",
        "`Namenszusatz2`",
        "`Firma`",
        "`Verkaeufer`",
        "`Email`",
        "`Telefon`",
        "`GeaendertAm`",
        "concat(Nachname, ' ', Vorname) AS `KundenName`",
        "'Customer_EN' AS __SourceTable",
        "current_timestamp() AS __InsertTimestampUTC",
        "current_timestamp() AS __UpdateTimestampUTC",
        "__InsertTimestampUTC AS __InsertTimestampExternalUTC"
    )
)
source_delta_df_list.append(source_delta_2_df)

# COMMAND ----------

if not source_delta_df_list:
    raise ValueError("No delta sources configured for this entity.")

union_df = source_delta_df_list[0]
for additional_df in source_delta_df_list[1:]:
    union_df = union_df.unionByName(additional_df)

latest_snapshot_key_cols = ["KundenID"]
if latest_snapshot_key_cols:
    # Keep only the latest snapshot per business key to avoid duplicate records from external feeds.
    latest_snapshot_window = Window.partitionBy(*latest_snapshot_key_cols).orderBy(
        F.col("__InsertTimestampExternalUTC").desc(),
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
# MAGIC ## Write changes to BRONZE

# COMMAND ----------# COMMAND ----------

# MAGIC %md
# MAGIC ### Prepare merge statement

# COMMAND ----------

target_table = DeltaTable.forName(spark, table_name_ref)
current_snapshot_df = (
    spark.table(table_name_ref)
    .where(F.col("__IsCurrent").eqNullSafe(True))
)

staged_base = (
    union_df.alias("src")
    .join(
        current_snapshot_df.alias("tgt"),
        [
            (F.col("src.`KundenID`") == F.col("tgt.`KundenID`"))
        ],
        "left",
    )
    .withColumns({
        "__target_exists": F.col("tgt.__IsCurrent").isNotNull(),
        "scd2_changed":
        (
            (~F.col("tgt.`Nachname`").eqNullSafe(F.col("src.`Nachname`")))
        )
        ,
        "__ValidFrom": F.col("src.__InsertTimestampUTC"),
        "__ValidTo": F.to_timestamp(F.lit(MAX_VALID_TO_DATE)),
        "__IsCurrent": F.lit(True),
    })
    .select("src.*", "__target_exists", "scd2_changed", "__ValidFrom", "__ValidTo", "__IsCurrent")
)

staged_updates = staged_base.filter(F.col("__target_exists")).withColumn("__merge_action", F.lit("update"))
staged_inserts = (
    staged_base
    .filter(
        (~F.col("__target_exists")) | F.col("scd2_changed")
    )
    .withColumn("__merge_action", F.lit("insert"))
)
staged_union = staged_updates.unionByName(staged_inserts)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Execute merge

# COMMAND ----------
merge_builder = (
    target_table.alias("tgt")
    .merge(
        staged_union.alias("src"),
        "(tgt.`KundenID` <=> src.`KundenID`) AND src.__merge_action = 'update'",
    )
    .whenMatchedUpdate(
        condition="src.scd2_changed",
        set={
            "__ValidTo": "src.__InsertTimestampUTC",
            "__IsCurrent": "False",
            "__UpdateTimestampUTC": "src.__UpdateTimestampUTC",
        },
    )
)
merge_builder = merge_builder.whenMatchedUpdate(
    condition="(NOT src.scd2_changed) AND (NOT (tgt.`NamensTyp` <=> src.`NamensTyp`) OR NOT (tgt.`Titel` <=> src.`Titel`) OR NOT (tgt.`Vorname` <=> src.`Vorname`) OR NOT (tgt.`Nameszusatz1` <=> src.`Nameszusatz1`) OR NOT (tgt.`Namenszusatz2` <=> src.`Namenszusatz2`) OR NOT (tgt.`Firma` <=> src.`Firma`) OR NOT (tgt.`Verkaeufer` <=> src.`Verkaeufer`) OR NOT (tgt.`Email` <=> src.`Email`) OR NOT (tgt.`Telefon` <=> src.`Telefon`) OR NOT (tgt.`GeaendertAm` <=> src.`GeaendertAm`) OR NOT (tgt.`KundenName` <=> src.`KundenName`))",
    set={
        "NamensTyp": 'src.`NamensTyp`', 
        "Titel": 'src.`Titel`', 
        "Vorname": 'src.`Vorname`', 
        "Nameszusatz1": 'src.`Nameszusatz1`', 
        "Namenszusatz2": 'src.`Namenszusatz2`', 
        "Firma": 'src.`Firma`', 
        "Verkaeufer": 'src.`Verkaeufer`', 
        "Email": 'src.`Email`', 
        "Telefon": 'src.`Telefon`', 
        "GeaendertAm": 'src.`GeaendertAm`', 
        "KundenName": 'src.`KundenName`', 
        "__UpdateTimestampUTC": 'src.__UpdateTimestampUTC'
    },
)
merge_builder = merge_builder.whenNotMatchedInsert(
    values={
        "__ValidFrom": "src.__ValidFrom",
        "__ValidTo": "src.__ValidTo",
        "__IsCurrent": "src.__IsCurrent",
        "__InsertTimestampUTC":'src.__InsertTimestampUTC', 
        "__UpdateTimestampUTC":'src.__UpdateTimestampUTC', 
        "__SourceTable":'src.__SourceTable', 
        "__InsertTimestampExternalUTC":'src.__InsertTimestampExternalUTC', 
        "KundenID":'src.`KundenID`', 
        "NamensTyp":'src.`NamensTyp`', 
        "Titel":'src.`Titel`', 
        "Vorname":'src.`Vorname`', 
        "Nameszusatz1":'src.`Nameszusatz1`', 
        "Nachname":'src.`Nachname`', 
        "Namenszusatz2":'src.`Namenszusatz2`', 
        "Firma":'src.`Firma`', 
        "Verkaeufer":'src.`Verkaeufer`', 
        "Email":'src.`Email`', 
        "Telefon":'src.`Telefon`', 
        "GeaendertAm":'src.`GeaendertAm`', 
        "KundenName":'src.`KundenName`'
    },
)
result = merge_builder.execute()
print(result)

# COMMAND ----------