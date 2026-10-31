business_function = spark.sql(f"""
SELECT r.ReturnID,r.SalesOrderID,r.SalesOrderDetailID,r.ProductID,h.CustomerID,r.Quantity,r.Reason,r.Status
FROM {catalog.name}.core.commerce_returns_returnrequest r
LEFT JOIN {catalog.name}.stage.adventureworks_saleslt_salesorderheader h ON r.SalesOrderID=h.SalesOrderID
""")

# Resolve the current customer version for cross-system facts.
current_customer = spark.table(f"{catalog.name}.curated.masterdata_customer_dimcustomer").filter("__IsCurrent AND SourceSystem = 'AdventureWorks_US'").select("CustomerID", "CustomerSID")
business_function = business_function.join(current_customer, on="CustomerID", how="left")
