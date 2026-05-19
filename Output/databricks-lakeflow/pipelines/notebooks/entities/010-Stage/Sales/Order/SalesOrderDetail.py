# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Order_SalesOrderDetail")
def lakeflow_entity_stage_sales_order_salesorderdetail():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Order_SalesOrderDetail"
        ).selectExpr(
            "try_cast(`SalesOrderID` as int) AS `SalesOrderID`",
            "try_cast(`SalesOrderDetailID` as int) AS `SalesOrderDetailID`",
            "try_cast(`OrderQty` as smallint) AS `OrderQty`",
            "try_cast(`ProductID` as int) AS `ProductID`",
            "try_cast(`UnitPrice` as decimal) AS `UnitPrice`",
            "try_cast(`UnitPriceDiscount` as decimal) AS `UnitPriceDiscount`",
            "try_cast(`LineTotal` as decimal) AS `LineTotal`",
            "try_cast(`rowguid` as string) AS `rowguid`",
            "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
            "'SalesOrderDetail' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Order_SalesOrderDetail has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)