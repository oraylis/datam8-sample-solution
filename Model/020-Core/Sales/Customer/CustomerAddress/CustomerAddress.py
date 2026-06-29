stage_schema = f"{schema_prefix}stage" if schema_prefix else "stage"

business_function = spark.sql(f"""
    SELECT
    concat(CustomerID, AddressID) AS _CustomerAddressBK,
    AddressID,
    CustomerID,
    AddressType
    FROM
    {catalog_name}.{stage_schema}.sales_customer_customeraddress
""")
