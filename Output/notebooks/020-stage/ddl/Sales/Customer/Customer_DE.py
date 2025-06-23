# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for stage.Sales_Customer_Customer_DE

# COMMAND ----------

from pyspark.sql.types import (
    StructType,  # noqa: F401
    StructField,  # noqa: F401
    StringType,  # noqa: F401
    BooleanType,  # noqa: F401
    IntegerType,  # noqa: F401
    TimestampType,  # noqa: F401
    DoubleType,  # noqa: F401
    ShortType,  # noqa: F401
    ByteType,  # noqa: F401
    DecimalType,  # noqa: F401
    TimestampNTZType,  # noqa: F401
    LongType,  # noqa: F401
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get variable values

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
zone = stage_zone

# static values
MAX_VALID_TO_DATE = "2999-12-31"
data_product = "Sales"
data_module = "Customer"
table_name = "Customer_DE"
full_table_name = "%s_%s_%s" % (data_product, data_module, table_name)

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

# COMMAND ----------# DBTITLE 1, Define dataframe
schema = StructType([
    StructField("KundenID", StructType.fromDDL("int"), False),
    StructField("NamensTyp", StructType.fromDDL("boolean"), False),
    StructField("Titel", StructType.fromDDL("string"), True),
    StructField("Vorname", StructType.fromDDL("string"), False),
    StructField("Nameszusatz1", StructType.fromDDL("string"), True),
    StructField("Nachname", StructType.fromDDL("string"), False),
    StructField("Namenszusatz2", StructType.fromDDL("string"), True),
    StructField("Firma", StructType.fromDDL("string"), True),
    StructField("Verkaeufer", StructType.fromDDL("string"), True),
    StructField("Email", StructType.fromDDL("string"), True),
    StructField("Telefon", StructType.fromDDL("string"), True),
    StructField("PasswordHash", StructType.fromDDL("string"), False),
    StructField("PasswordSalt", StructType.fromDDL("string"), False),
    StructField("rowguid", StructType.fromDDL("string"), False),
    StructField("GeaendertAm", StructType.fromDDL("timestamp"), False),
    StructField("__Year", ShortType(), False),
    StructField("__Month", ByteType(), False),
    StructField("__Day", ByteType(), False),
    StructField("__InsertTimestampUTC", TimestampType(), False),
])

# COMMAND ----------

# DBTITLE 1,Define new partitions
new_partitions = (
    "__Year",
    "__Month",
    "__Day",
    "__InsertTimestampUTC",
)

# COMMAND ----------

# DBTITLE 1,Define DDL statement
ddl = """
CREATE TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
(
    -- Table columns
    `KundenID`                int         NOT NULL
,   `NamensTyp`               boolean     NOT NULL
,   `Titel`                   string          
,   `Vorname`                 string      NOT NULL
,   `Nameszusatz1`            string          
,   `Nachname`                string      NOT NULL
,   `Namenszusatz2`           string          
,   `Firma`                   string          
,   `Verkaeufer`              string          
,   `Email`                   string          
,   `Telefon`                 string          
,   `PasswordHash`            string      NOT NULL
,   `PasswordSalt`            string      NOT NULL
,   `rowguid`                 string      NOT NULL
,   `GeaendertAm`             timestamp   NOT NULL

    -- Technical columns
,   `__Year`                  smallint    NOT NULL
,   `__Month`                 tinyint     NOT NULL
,   `__Day`                   tinyint     NOT NULL
,   `__InsertTimestampUTC`    timestamp   NOT NULL
)
USING DELTA
PARTITIONED BY (
    `__Year`,
    `__Month`,
    `__Day`,
    `__InsertTimestampUTC`
)
""" % {
    "catalog": catalog.name,
    "schema": zone,
    "table": full_table_name,
}

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = []

# COMMAND ----------

# DBTITLE 1,Call migrate_schema method
try:
    table_instance = catalog.create_table_from_ddl(
        full_table_name="%s.%s" % (zone, full_table_name),
        ddl=ddl,
    )
    table_instance.owner = owner

    print("Table sucessfully created.")
except Exception as e:
    print(f"Creation of table failed: {e}")

# COMMAND ----------
