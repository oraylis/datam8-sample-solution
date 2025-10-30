# Databricks notebook source
business_function = spark.sql("""
    SELECT
        int(date_format(salesheader.ShipDate, 'yyyyMMdd')) AS ShipDateID,
        salesheader.CustomerID,
        SUM(salesheader.TotalDue) AS TotalCosts,
        SUM(salesorder.LineTotal) AS OrderQuantity

    FROM stage.sales_order_salesorderdetail AS salesorder
    JOIN stage.sales_order_salesorderheader AS salesheader ON salesorder.SalesOrderID = salesheader.SalesOrderID
                              
    GROUP BY ALL
""")
