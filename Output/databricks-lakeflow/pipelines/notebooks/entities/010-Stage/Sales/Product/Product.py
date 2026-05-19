# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Product_Product")
def lakeflow_entity_stage_sales_product_product():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Product_Product"
        ).selectExpr(
            "try_cast(`ProductID` as int) AS `ProductID`",
            "try_cast(`Name` as string) AS `Name`",
            "try_cast(`ProductNumber` as string) AS `ProductNumber`",
            "try_cast(`Color` as string) AS `Color`",
            "try_cast(`StandardCost` as decimal) AS `StandardCost`",
            "try_cast(`ListPrice` as decimal) AS `ListPrice`",
            "try_cast(`Size` as string) AS `Size`",
            "try_cast(`Weight` as decimal) AS `Weight`",
            "try_cast(`ProductCategoryID` as int) AS `ProductCategoryID`",
            "try_cast(`ProductModelID` as int) AS `ProductModelID`",
            "try_cast(`SellStartDate` as timestamp) AS `SellStartDate`",
            "try_cast(`SellEndDate` as timestamp) AS `SellEndDate`",
            "try_cast(`DiscontinuedDate` as timestamp) AS `DiscontinuedDate`",
            "try_cast(`ThumbNailPhoto` as string) AS `ThumbNailPhoto`",
            "try_cast(`ThumbnailPhotoFileName` as string) AS `ThumbnailPhotoFileName`",
            "try_cast(`rowguid` as string) AS `rowguid`",
            "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
            "'Product' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Product_Product has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)