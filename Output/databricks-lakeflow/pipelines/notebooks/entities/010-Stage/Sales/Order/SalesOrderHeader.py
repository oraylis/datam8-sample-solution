# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Order_SalesOrderHeader")
def lakeflow_entity_stage_sales_order_salesorderheader():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Order_SalesOrderHeader"
        ).selectExpr(
            "try_cast(`SalesOrderID` as int) AS `SalesOrderID`",
            "try_cast(`RevisionNumber` as int) AS `RevisionNumber`",
            "try_cast(`OrderDate` as timestamp) AS `OrderDate`",
            "try_cast(`DueDate` as timestamp) AS `DueDate`",
            "try_cast(`ShipDate` as timestamp) AS `ShipDate`",
            "try_cast(`Status` as int) AS `Status`",
            "try_cast(`OnlineOrderFlag` as boolean) AS `OnlineOrderFlag`",
            "try_cast(`SalesOrderNumber` as string) AS `SalesOrderNumber`",
            "try_cast(`PurchaseOrderNumber` as string) AS `PurchaseOrderNumber`",
            "try_cast(`AccountNumber` as string) AS `AccountNumber`",
            "try_cast(`CustomerID` as int) AS `CustomerID`",
            "try_cast(`ShipToAddressID` as int) AS `ShipToAddressID`",
            "try_cast(`BillToAddressID` as int) AS `BillToAddressID`",
            "try_cast(`ShipMethod` as string) AS `ShipMethod`",
            "try_cast(`CreditCardApprovalCode` as string) AS `CreditCardApprovalCode`",
            "try_cast(`SubTotal` as decimal) AS `SubTotal`",
            "try_cast(`TaxAmt` as decimal) AS `TaxAmt`",
            "try_cast(`Freight` as decimal) AS `Freight`",
            "try_cast(`TotalDue` as decimal) AS `TotalDue`",
            "try_cast(`Comment` as string) AS `Comment`",
            "try_cast(`rowguid` as string) AS `rowguid`",
            "try_cast(`ModifiedDate` as timestamp) AS `ModifiedDate`",
            "'SalesOrderHeader' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Order_SalesOrderHeader has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)