business_function = spark.sql(f"""
SELECT s.SessionID,s.CustomerID,s.Channel,s.Device,
       COUNT(c.CartItemID) AS CartItemCount,COALESCE(SUM(c.Quantity),0) AS CartQuantity,
       COALESCE(MAX(CASE WHEN c.Purchased THEN 1 ELSE 0 END),0)=1 AS PurchasedAny
FROM {catalog.name}.core.commerce_session_websession s
LEFT JOIN {catalog.name}.core.commerce_cart_cartitem c ON s.SessionID=c.SessionID
GROUP BY s.SessionID,s.CustomerID,s.Channel,s.Device
""")

# Resolve the current customer version for cross-system facts.
current_customer = spark.table(f"{catalog.name}.curated.masterdata_customer_dimcustomer").filter("__IsCurrent AND SourceSystem = 'AdventureWorks_US'").select("CustomerID", "CustomerSID")
business_function = business_function.join(current_customer, on="CustomerID", how="left")
