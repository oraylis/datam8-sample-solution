# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Other_Address")
def lakeflow_entity_stage_sales_other_address():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Other_Address"
        ).selectExpr(
            "try_cast(`AddressID` as int) AS `AddressID`",
            "try_cast(`AddressLine1` as string) AS `AddressLine1`",
            "try_cast(`AddressLine2` as string) AS `AddressLine2`",
            "try_cast(`City` as string) AS `City`",
            "try_cast(`StateProvince` as string) AS `StateProvince`",
            "try_cast(`CountryRegion` as string) AS `CountryRegion`",
            "try_cast(`PostalCode` as string) AS `PostalCode`",
            "try_cast(`rowguid` as string) AS `rowguid`",
            "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
            "'Address' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Other_Address has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)