business_function = spark.sql("""
    SELECT
    concat(AddressID) AS _AddressBK,
    AddressID,
    AddressLine1,
    AddressLine2,
    City AS CityName,
    CountryRegion AS CountryRegionName,
    PostalCode,
    StateProvince AS StateProvinceName
    
    FROM
    stage.adventureworks_saleslt_address
""")
