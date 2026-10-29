business_function = spark.sql(f"""
SELECT p.PurchaseOrderID,p.ProductID,p.SupplierID,p.WarehouseID,p.Quantity,p.Status,
       s.UnitCost,s.CurrencyCode,CAST(p.Quantity*s.UnitCost AS DECIMAL(18,4)) AS EstimatedPurchaseValue
FROM {catalog.name}.core.procurement_orders_purchaseorder p
LEFT JOIN {catalog.name}.core.procurement_supplier_productsupplier s ON p.ProductID=s.ProductID AND p.SupplierID=s.SupplierID
""")
