business_function = spark.sql("""
    SELECT *
    FROM stage.sales_customer_customeraddress
""")
