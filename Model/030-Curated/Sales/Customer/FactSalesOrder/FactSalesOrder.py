from pyspark.sql import functions as F

core_schema = f"{schema_prefix}core" if schema_prefix else "core"
sales_order_line = spark.table(f"{catalog_name}.{core_schema}.sales_order_salesorderline")

business_function = (
    sales_order_line
    .select(
        F.col("CustomerID").alias("CustomerSID"),
        F.col("ProductID").alias("ProductSID"),
        F.coalesce(F.col("ShipDateID"), F.lit(-1)).alias("ShipDateID"),
        F.col("SalesOrderLineID"),
        F.col("OrderQuantity"),
        F.col("LineTotal"),
        F.col("TotalDue").alias("TotalCosts"),
    )
)
