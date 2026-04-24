# Databricks notebook source
from pyspark.sql import functions as F

customer = spark.table("datam8_campus_dev_fka.stage.sales_customer_customer")
customeraddress = spark.table("datam8_campus_dev_fka.stage.sales_customer_customeraddress")

business_function = (
    customer.alias("c")
    .join(
        other=customeraddress.alias("ca"),
        how="left",
        on=[
            F.col("c.KundenID") == F.col("ca.CustomerID"),
            F.col("ca.AddressType") == "Main Office"
        ]
    )
    .filter("c.__IsCurrent = True")
    .select(
        F.col("c.KundenID").alias("KundenNummer"),
        "c.Vorname",
        "c.Nachname",
        "ca.AddressType",
    )
    .fillna({
        "AddressType": "N/A"
    })
)