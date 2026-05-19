# Databricks notebook source
from pyspark import pipelines as dp
from pyspark.sql import functions as F


@dp.table(name="Sales_Customer_Customer_DE")
def lakeflow_external_sales_customer_customer_de():
    source_df = spark.sql("SELECT * FROM remote_query(\u0027adventureworks\u0027, query =\u003e \u0027SELECT * FROM [AdventureWorks].[SalesLT].[Customer_DE]\u0027)")
    return source_df.select(
        F.current_timestamp().alias('__InsertTimestampUTC'),
        F.year(F.current_timestamp()).cast('smallint').alias('__Year'),
        F.month(F.current_timestamp()).cast('smallint').alias('__Month'),
        F.dayofmonth(F.current_timestamp()).cast('smallint').alias('__Day'),
        F.col('KundenID').alias('KundenID'),
        F.col('NamensTyp').alias('NamensTyp'),
        F.col('Titel').alias('Titel'),
        F.col('Vorname').alias('Vorname'),
        F.col('Nameszusatz1').alias('Nameszusatz1'),
        F.col('Nachname').alias('Nachname'),
        F.col('Namenszusatz2').alias('Namenszusatz2'),
        F.col('Firma').alias('Firma'),
        F.col('Verkaeufer').alias('Verkaeufer'),
        F.col('Email').alias('Email'),
        F.col('Telefon').alias('Telefon'),
        F.col('PasswordHash').alias('PasswordHash'),
        F.col('PasswordSalt').alias('PasswordSalt'),
        F.col('rowguid').alias('rowguid'),
        F.col('GeaendertAm').alias('GeaendertAm')
    )