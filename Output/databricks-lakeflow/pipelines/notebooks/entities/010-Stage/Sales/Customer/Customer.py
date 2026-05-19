# Databricks notebook source
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

catalog_name = spark.conf.get("catalog_name")
schema_prefix = spark.conf.get("schema_prefix", "")


@dp.table(name="Sales_Customer_Customer")
def lakeflow_entity_stage_sales_customer_customer():
    source_frames: list[DataFrame] = []
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Customer_Customer_DE"
        ).selectExpr(
            "try_cast(`KundenID` as int) AS `KundenID`",
            "try_cast(`NamensTyp` as boolean) AS `NamensTyp`",
            "try_cast(`Titel` as string) AS `Titel`",
            "try_cast(`Vorname` as string) AS `Vorname`",
            "try_cast(`Nameszusatz1` as string) AS `Nameszusatz1`",
            "try_cast(`Nachname` as string) AS `Nachname`",
            "try_cast(`Namenszusatz2` as string) AS `Namenszusatz2`",
            "try_cast(`Firma` as string) AS `Firma`",
            "try_cast(`Verkaeufer` as string) AS `Verkaeufer`",
            "try_cast(`Email` as string) AS `Email`",
            "try_cast(`Telefon` as string) AS `Telefon`",
            "try_cast(`GeaendertAm` as timestamp) AS `GeaendertAm`",
            "concat(Nachname, ' ', Vorname) AS `KundenName`",
            "'Customer_DE' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    source_frames.append(
        spark.read.table(
            f"{catalog_name}.{schema_prefix}raw.Sales_Customer_Customer_EN"
        ).selectExpr(
            "try_cast(`CustomerID` as int) AS `KundenID`",
            "try_cast(`NameStyle` as boolean) AS `NamensTyp`",
            "try_cast(`Title` as string) AS `Titel`",
            "try_cast(`FirstName` as string) AS `Vorname`",
            "try_cast(`MiddleName` as string) AS `Nameszusatz1`",
            "try_cast(`LastName` as string) AS `Nachname`",
            "try_cast(`Suffix` as string) AS `Namenszusatz2`",
            "try_cast(`CompanyName` as string) AS `Firma`",
            "try_cast(`SalesPerson` as string) AS `Verkaeufer`",
            "try_cast(`EmailAddress` as string) AS `Email`",
            "try_cast(`Phone` as string) AS `Telefon`",
            "try_cast(`ModifiedDate` as timestamp) AS `GeaendertAm`",
            "concat(Nachname, ' ', Vorname) AS `KundenName`",
            "'Customer_EN' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "current_timestamp() AS __InsertTimestampSourceUTC"
        )
    )
    if not source_frames:
        raise ValueError("Entity Sales_Customer_Customer has no source frames.")
    return reduce(lambda left, right: left.unionByName(right), source_frames)