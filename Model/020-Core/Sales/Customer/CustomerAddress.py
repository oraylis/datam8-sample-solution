business_function = spark.sql("""
    SELECT *
    FROM staging.sales_customer_customeraddress
""")
