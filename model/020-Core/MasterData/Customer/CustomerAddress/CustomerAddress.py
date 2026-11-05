business_function = spark.sql(f"""
    SELECT
        concat(CustomerID, AddressID) AS _CustomerAddressBK,
        AddressID,
        CustomerID,
        AddressType
    FROM {catalog.name}.stage.adventureworks_saleslt_customeraddress
""")
