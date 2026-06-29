from pyspark.sql import functions as F

stage_schema = f"{schema_prefix}stage" if schema_prefix else "stage"

product = spark.table(f"{catalog_name}.{stage_schema}.sales_product_product").alias("p")
category = spark.table(f"{catalog_name}.{stage_schema}.sales_product_productcategory")
model = spark.table(f"{catalog_name}.{stage_schema}.sales_product_productmodel").alias("pm")
bridge = spark.table(f"{catalog_name}.{stage_schema}.sales_product_productmodelproductdescription").alias("pmpd")
description = spark.table(f"{catalog_name}.{stage_schema}.sales_product_productdescription").alias("pd")

category_child = category.alias("pc")
category_parent = category.alias("ppc")

business_function = (
    product
    .join(category_child, F.col("p.ProductCategoryID") == F.col("pc.ProductCategoryID"), "left")
    .join(category_parent, F.col("pc.ParentProductCategoryID") == F.col("ppc.ProductCategoryID"), "left")
    .join(model, F.col("p.ProductModelID") == F.col("pm.ProductModelID"), "left")
    .join(
        bridge,
        (F.col("p.ProductModelID") == F.col("pmpd.ProductModelID"))
        & (F.col("pmpd.Culture") == F.lit("en")),
        "left",
    )
    .join(description, F.col("pmpd.ProductDescriptionID") == F.col("pd.ProductDescriptionID"), "left")
    .select(
        F.col("p.ProductID"),
        F.col("p.Name").alias("ProductName"),
        F.col("p.ProductNumber"),
        F.col("p.Color"),
        F.col("p.Size"),
        F.col("p.StandardCost").cast("double").alias("StandardCost"),
        F.col("p.ListPrice").cast("double").alias("ListPrice"),
        F.col("p.ProductCategoryID"),
        F.col("pc.Name").alias("ProductCategoryName"),
        F.col("pc.ParentProductCategoryID"),
        F.col("ppc.Name").alias("ParentProductCategoryName"),
        F.col("p.ProductModelID"),
        F.col("pm.Name").alias("ProductModelName"),
        F.col("pd.Description").alias("ProductDescription"),
        F.col("p.SellStartDate"),
        F.col("p.SellEndDate"),
    )
    .fillna({
        "Color": "N/A",
        "Size": "N/A",
        "ProductCategoryName": "N/A",
        "ParentProductCategoryName": "N/A",
        "ProductModelName": "N/A",
        "ProductDescription": "N/A",
    })
)
