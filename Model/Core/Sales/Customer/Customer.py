business_function = spark.sql("""
    SELECT *
    FROM
        staging.sales_customer_customer_de
    UNION ALL
    SELECT *
    FROM staging.sales_customer_customer_en
""")
