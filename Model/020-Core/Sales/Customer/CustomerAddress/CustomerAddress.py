business_function = spark.sql("""
    SELECT
    concat(CustomerID, AddressID) AS _CustomerAddressBK,
    AddressID,
    CustomerID,
    AddressType
    FROM
    datam8_campus_dev_fka.stage.sales_customer_customeraddress
""")
