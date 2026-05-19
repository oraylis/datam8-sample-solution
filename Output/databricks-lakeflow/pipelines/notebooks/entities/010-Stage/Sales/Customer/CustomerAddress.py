# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Customer_CustomerAddress")
def lakeflow_entity_stage_sales_customer_customeraddress():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Customer_CustomerAddress"
        ).selectExpr(
            "try_cast(`CustomerID` as int) AS `CustomerID`",
            "try_cast(`AddressID` as int) AS `AddressID`",
            "try_cast(`AddressType` as string) AS `AddressType`",
            "'CustomerAddress' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Customer_CustomerAddress has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)