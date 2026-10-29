business_function = spark.sql(f"""
WITH latest AS (
 SELECT SalesOrderID,EventAt,Status,
        ROW_NUMBER() OVER(PARTITION BY SalesOrderID ORDER BY EventAt DESC,EventID DESC) AS rn,
        COUNT(*) OVER(PARTITION BY SalesOrderID) AS EventCount
 FROM {catalog.name}.core.shipping_tracking_trackingevent
)
SELECT s.ShipmentID,s.SalesOrderID,s.CustomerID,s.WarehouseID,s.Carrier,s.TrackingNumber,
       s.Status,s.EstimatedDelivery,e.EventAt AS LatestEventAt,e.Status AS LatestEventStatus,
       COALESCE(e.EventCount,0) AS EventCount
FROM {catalog.name}.core.shipping_shipment_shipment s
LEFT JOIN latest e ON s.SalesOrderID=e.SalesOrderID AND e.rn=1
""")

# Resolve the current customer version for cross-system facts.
current_customer = spark.table(f"{catalog.name}.curated.masterdata_customer_dimcustomer").filter("__IsCurrent AND SourceSystem = 'AdventureWorks_US'").select("CustomerID", "CustomerSID")
business_function = business_function.join(current_customer, on="CustomerID", how="left")
