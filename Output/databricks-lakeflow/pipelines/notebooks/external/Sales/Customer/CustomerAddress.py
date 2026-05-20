# Databricks notebook source
from pyspark import pipelines as dp
from pyspark.sql import functions as F


@dp.table(name="Sales_Customer_CustomerAddress")
def lakeflow_external_sales_customer_customeraddress():
    source_df = spark.sql("SELECT * FROM remote_query(\u0027adventureworks\u0027, database =\u003e \u0027AdventureWorks\u0027, query =\u003e \u0027SELECT * FROM [SalesLT].[CustomerAddress] WHERE CustomerID \u003e 1\u0027)")
    return source_df.select(
        F.current_timestamp().alias('__InsertTimestampUTC'),
        F.year(F.current_timestamp()).cast('smallint').alias('__Year'),
        F.month(F.current_timestamp()).cast('smallint').alias('__Month'),
        F.dayofmonth(F.current_timestamp()).cast('smallint').alias('__Day'),
        F.col('CustomerID').alias('CustomerID'),
        F.col('AddressID').alias('AddressID'),
        F.col('AddressType').alias('AddressType'),
        F.col('rowguid').alias('rowguid'),
        F.col('ModifiedDate').alias('ModifiedDate')
    )