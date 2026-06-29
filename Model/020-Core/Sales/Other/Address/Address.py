stage_schema = f"{schema_prefix}stage" if schema_prefix else "stage"

business_function = spark.sql(f"""
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
    {catalog_name}.{stage_schema}.sales_other_address
""")
