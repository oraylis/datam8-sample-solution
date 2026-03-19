# Databricks notebook source
# MAGIC %md
# MAGIC # DDL for curated.Sales_Customer_FactSalesOrder

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize base settings

# COMMAND ----------

# MAGIC %md
# MAGIC ### Imports

# COMMAND ----------

from pyspark.sql.types import (
    StructType,  # noqa: F401
    StructField,  # noqa: F401
    DataType,  # noqa: F401
)

# COMMAND ----------

from delta.tables import DeltaTable

# COMMAND ----------

# MAGIC %md
# MAGIC ### Get variable values

# COMMAND ----------

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
zone = "curated"
data_product = "Sales"
data_module = "Customer"
table_name = "FactSalesOrder"
full_table_name = "Sales_Customer_FactSalesOrder"

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
print("Schema: %s" % zone)
print("Table: %s" % full_table_name)
print("Owner: %s" % owner)
print("Data Product: %s" % data_product)
print("Data Module: %s" % data_module)
# print("Mode: %s" % run_mode)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.schema = zone
catalog.set_active()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define table schema

# COMMAND ----------

# DBTITLE 1,Define schema
table_name = f"{catalog_name}.{zone}.{full_table_name}"
table_comment = "Fact table with sales orders"

schema = StructType([
    StructField("__InsertTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Load timestamp (UTC)'}),
    StructField("__UpdateTimestampUTC", DataType.fromDDL("TIMESTAMP"), False, metadata={'comment': 'Last update timestamp (UTC)'}),
    StructField("__BusinessFunction", DataType.fromDDL("STRING"), False, metadata={'comment': 'Business function marker'}),
    StructField("CustomerSID", DataType.fromDDL("BIGINT"), False, metadata={'comment': 'Customer surrogate key', 'foreign_key': True, 'foreign_key_table': 'curated.Sales_Customer_DimCustomer'}),
    StructField("ShipDateID", DataType.fromDDL("INT"), False, metadata={'comment': 'Ship date as integer'}),
    StructField("TotalCosts", DataType.fromDDL("DOUBLE"), True, metadata={'comment': 'Costs of sales orders'}),
])

# COMMAND ----------

# DBTITLE 1,Define partitions
partitions = []

# COMMAND ----------

# DBTITLE 1,Define table properties
tblproperties_parts = {
    "delta.logRetentionDuration": "interval 7 days",
    "delta.deletedFileRetentionDuration": "interval 7 days",
}

tblproperties_sql = ', '.join([f"'{key}'='{value}'" for key, value in tblproperties_parts.items()])
tblproperties_sql = f"TBLPROPERTIES ({tblproperties_sql})" if tblproperties_sql else ""

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or migrate table

# COMMAND ----------

# DBTITLE 1,Build & execute SQL Statement
table_base = table_name.replace(".", "_")
col_lines, pk_cols, fk_constraints = [], [], []

# Build column definitions
for f in schema.fields:
    md = getattr(f, "metadata", {}) or {}
    col = f"`{f.name}` {f.dataType.simpleString().upper()}"
    if md.get("surrogate_key"): col += " GENERATED ALWAYS AS IDENTITY" # Flag as Identity column if it's a surrogate key
    if not f.nullable: col += " NOT NULL" # Add NOT NULL if column is non-nullable
    if md.get("comment"): col += f" COMMENT '{md['comment']}'" # Add COMMENT for column if available
    if md.get("surrogate_key"): pk_cols.append(f"`{f.name}`")
    if md.get("foreign_key"):
        ref_table = md.get("foreign_key_table")
        if ref_table:
            constraint_name = f"fk_{table_base}"
            fk_constraints.append(
                f"CONSTRAINT `{constraint_name}` "
                f"FOREIGN KEY (`{f.name}`) REFERENCES {catalog.name}.{ref_table} RELY"
            )
    col_lines.append(col)

# Add a table-level primary key constraint if surrogate_key fields exist
if pk_cols:
    col_lines.append(f"CONSTRAINT `pk_{table_base}` PRIMARY KEY ({', '.join(pk_cols)}) RELY")

# Add table-level foreign key constraints (if exist)
col_lines.extend(fk_constraints)

# Start CREATE TABLE statement
parts = [f"CREATE TABLE IF NOT EXISTS {table_name} (", "  " + ",\n  ".join(col_lines), ")", "USING DELTA"]

# Optional: add table comment
if table_comment: parts.append(f"COMMENT '{table_comment}'")

# Add CLUSTER BY if partitions are defined
if partitions:
    part_str = ", ".join(f"`{p}`" for p in partitions)
    parts.append(f"CLUSTER BY ({part_str})")

# Add TBLPROPERTIES if provided
if tblproperties_sql: parts.append(tblproperties_sql)

create_sql = "\n".join(parts) + ";"
print(create_sql)

# Execute SQL statement
spark.sql(create_sql)

# COMMAND ----------

# DBTITLE 1,Define refactored columns
refactored_columns = [
]

# COMMAND ----------

# DBTITLE 1,Call migrate_schema method
table_instance = Table(f"{zone}.{full_table_name}", catalog)

try:
    result = table_instance.migrate_schema(
        ddl=create_sql,
        schema=schema,
        refactored_columns=refactored_columns,
        new_partitions=partitions,
    )

    print("Result: %s" % str(result))
except Exception as e:
    print(f"Migration failed: {e}")

table_instance.owner = owner

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tags

# COMMAND ----------

# DBTITLE 1,Set table & column tags
# table attributes
table_instance.set_table_tags({'business_area': 'sales', 'jobs': 'sales_weekly', 'write_mode': 'merge', 'data_retention': '7_days'})

# column attributes