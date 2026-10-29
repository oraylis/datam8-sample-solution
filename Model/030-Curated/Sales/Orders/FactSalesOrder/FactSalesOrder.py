business_function = spark.sql(f"""
SELECT h.CustomerID, 'AdventureWorks_US' AS SourceSystem,
       COALESCE(d.AddressType,'N/A') AS AddressType,
       COALESCE(int(date_format(h.ShipDate,'yyyyMMdd')),0) AS ShipDateID,
       CAST(SUM(h.TotalDue) AS DECIMAL(18,4)) AS TotalCosts
FROM {catalog.name}.stage.adventureworks_saleslt_salesorderheader h
LEFT JOIN {catalog.name}.curated.masterdata_customer_dimcustomer d
  ON h.CustomerID=d.CustomerID
 AND d.SourceSystem='AdventureWorks_US'
 AND d.__IsCurrent
GROUP BY h.CustomerID, COALESCE(d.AddressType,'N/A'), COALESCE(int(date_format(h.ShipDate,'yyyyMMdd')),0)
""")
