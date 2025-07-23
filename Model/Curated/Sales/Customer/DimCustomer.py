# Databricks notebook source
from pyspark.sql import functions as F

# COMMAND ----------

customer = spark.table("core.sales_customer_customer")
customer_address = spark.table("core.sales_customer_customeraddress")
address = spark.table("core.sales_other_address")

# COMMAND ----------

business_function = (
    customer.alias("c")
    .join(
        other=customer_address.alias("ca"),
        how="left",
        on=[
            F.col("c.CustomerID") == F.col("ca.CustomerID"),
            F.col("ca.AddressType") == "Main Office"
        ]
    )
    .join(
        other=address.alias("a"),
        how="left",
        on=[
            F.col("a.AddressID") == F.col("ca.AddressID")
        ]
    )
    .select(
        F.col("c._CustomerSID").alias("CustomerSID"),
        "c.DisplayName",
        "ca.AddressType",
        F.concat("a.AddressLine1", "a.AddressLine2").alias("Address"),
        "a.PostalCode",
        "a.CityName",
        F.col("a.CountryRegionName").alias("CountryName"),
    )
    .fillna({
        "AddressType": "N/A",
        "CountryName": "N/A",
        "CityName": "N/A",
        "PostalCode": "N/A",
        "Address": "N/A"
    })
)
