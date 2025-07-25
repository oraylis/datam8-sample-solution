business_function = spark.sql("""
    SELECT *
    FROM staging.sales_other_address
""")
