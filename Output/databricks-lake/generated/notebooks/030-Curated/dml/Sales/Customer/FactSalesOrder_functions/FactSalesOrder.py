# Databricks notebook source
# Databricks notebook source
business_function = spark.sql("""
    SELECT
        int(date_format(salesheader.ShipDate, 'yyyyMMdd')) AS ShipDateID,
        salesheader.CustomerID,
        CAST(SUM(salesheader.TotalDue) AS double) AS TotalCosts,
        CAST(SUM(salesorder.LineTotal) AS double) AS OrderQuantity

    FROM stage.sales_order_salesorderdetail AS salesorder
    JOIN stage.sales_order_salesorderheader AS salesheader ON salesorder.SalesOrderID = salesheader.SalesOrderID
                              
    GROUP BY ALL
""")
