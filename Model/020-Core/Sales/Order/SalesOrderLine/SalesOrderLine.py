from pyspark.sql import functions as F

stage_schema = f"{schema_prefix}stage" if schema_prefix else "stage"
core_schema = f"{schema_prefix}core" if schema_prefix else "core"

header = spark.table(f"{catalog_name}.{stage_schema}.sales_order_salesorderheader").alias("h")
detail = spark.table(f"{catalog_name}.{stage_schema}.sales_order_salesorderdetail").alias("d")
product = spark.table(f"{catalog_name}.{core_schema}.sales_product_product").alias("p")

business_function = (
    detail
    .join(header, F.col("d.SalesOrderID") == F.col("h.SalesOrderID"), "inner")
    .join(product, F.col("d.ProductID") == F.col("p.ProductID"), "left")
    .select(
        F.concat_ws("-", F.col("d.SalesOrderID"), F.col("d.SalesOrderDetailID")).alias("SalesOrderLineID"),
        F.col("d.SalesOrderID"),
        F.col("d.SalesOrderDetailID"),
        F.col("h.CustomerID"),
        F.col("d.ProductID"),
        F.date_format(F.col("h.OrderDate"), "yyyyMMdd").cast("int").alias("OrderDateID"),
        F.date_format(F.col("h.DueDate"), "yyyyMMdd").cast("int").alias("DueDateID"),
        F.date_format(F.col("h.ShipDate"), "yyyyMMdd").cast("int").alias("ShipDateID"),
        F.col("d.OrderQty").cast("int").alias("OrderQuantity"),
        F.col("d.UnitPrice").cast("double").alias("UnitPrice"),
        F.col("d.UnitPriceDiscount").cast("double").alias("UnitPriceDiscount"),
        F.col("d.LineTotal").cast("double").alias("LineTotal"),
        F.col("h.TaxAmt").cast("double").alias("TaxAmount"),
        F.col("h.Freight").cast("double").alias("FreightAmount"),
        F.col("h.TotalDue").cast("double").alias("TotalDue"),
        F.when(F.col("h.Status") == 1, F.lit("In process"))
        .when(F.col("h.Status") == 2, F.lit("Approved"))
        .when(F.col("h.Status") == 3, F.lit("Backordered"))
        .when(F.col("h.Status") == 4, F.lit("Rejected"))
        .when(F.col("h.Status") == 5, F.lit("Shipped"))
        .when(F.col("h.Status") == 6, F.lit("Cancelled"))
        .otherwise(F.lit("Unknown"))
        .alias("OrderStatus"),
    )
)
