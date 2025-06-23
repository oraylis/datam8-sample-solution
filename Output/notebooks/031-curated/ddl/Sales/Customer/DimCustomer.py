# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for curated.Sales_Customer_DimCustomer

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

# DBTITLE 1,Initialize Migration Framework
# MAGIC %run ../../../../000-utils/MigrationFramework

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
        dbutils.secrets.get(
            "akv_standard", "fs-azure-account-key-%s-dfs-core-windows-net" % data_lake_name),
    )

# COMMAND ----------

# DBTITLE 1, Define schema
schema = StructType([
    StructField("CustomerSID", StructType.fromDDL("bigint"), False),
    StructField("DisplayName", StructType.fromDDL("string"), False),
    StructField("AddressType", StructType.fromDDL("string"), False),
    StructField("Address", StructType.fromDDL("string"), False),
    StructField("PostalCode", StructType.fromDDL("string"), False),
    StructField("CityName", StructType.fromDDL("string"), False),
    StructField("CountryName", StructType.fromDDL("string"), False),
    StructField('__BusinessFunction', StringType(), False),
    StructField('__InsertTimestampUTC', TimestampType(), False),
    StructField('__UpdateTimestampUTC', TimestampType(), False),
])

# COMMAND ----------

# DBTITLE 1,Define new partitions
new_partitions = (
)

# COMMAND ----------

# DBTITLE 1, DDL statement
ddl = """
CREATE TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
(
    -- Table columns
    `CustomerSID`                  bigint      NOT NULL  COMMENT 'BK'
,   `DisplayName`                  string      NOT NULL  COMMENT 'SCD1'
,   `AddressType`                  string      NOT NULL  COMMENT 'SCD1'
,   `Address`                      string      NOT NULL  COMMENT 'SCD1'
,   `PostalCode`                   string      NOT NULL  COMMENT 'SCD1'
,   `CityName`                     string      NOT NULL  COMMENT 'SCD1'
,   `CountryName`                  string      NOT NULL  COMMENT 'SCD1'

    -- Technical columns
,   `__BusinessFunction`           string      NOT NULL
,   `__InsertTimestampUTC`         timestamp   NOT NULL
,   `__UpdateTimestampUTC`         timestamp   NOT NULL
)
USING DELTA
""" % {
    "catalog": catalog.name,
    "schema": zone,
    "table": full_table_name,
}

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
    {
        "name": "DisplayName",
        "refactorNames": [
            "CustomerName",
        ]
    },
]

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
