from pyspark.sql import functions as F

core_schema = f"{schema_prefix}core" if schema_prefix else "core"
product = spark.table(f"{catalog_name}.{core_schema}.sales_product_product")

unknown_product = spark.createDataFrame(
    [(-1, "Unknown", "Unknown", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", 0.0, 0.0)],
    "ProductID int, ProductName string, ProductNumber string, Color string, Size string, "
    "ProductCategoryName string, ParentProductCategoryName string, ProductModelName string, "
    "ProductDescription string, ListPrice double, StandardCost double",
)

business_function = (
    product.select(
        F.col("ProductID"),
        F.col("ProductName"),
        F.col("ProductNumber"),
        F.col("Color"),
        F.col("Size"),
        F.col("ProductCategoryName"),
        F.col("ParentProductCategoryName"),
        F.col("ProductModelName"),
        F.col("ProductDescription"),
        F.col("ListPrice"),
        F.col("StandardCost"),
    )
    .unionByName(unknown_product)
)
