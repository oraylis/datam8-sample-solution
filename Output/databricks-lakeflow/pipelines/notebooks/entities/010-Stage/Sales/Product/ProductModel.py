# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Product_ProductModel")
def lakeflow_entity_stage_sales_product_productmodel():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Product_ProductModel"
        ).selectExpr(
            "try_cast(`ProductModelID` as int) AS `ProductModelID`",
            "try_cast(`Name` as string) AS `Name`",
            "try_cast(`CatalogDescription` as string) AS `CatalogDescription`",
            "try_cast(`rowguid` as string) AS `rowguid`",
            "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
            "'ProductModel' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Product_ProductModel has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)