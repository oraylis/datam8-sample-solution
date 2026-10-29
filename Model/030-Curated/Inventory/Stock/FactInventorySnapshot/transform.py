business_function = spark.sql(f"""
SELECT ProductID,WarehouseID,OnHand,Reserved,OnHand-Reserved AS AvailableQuantity,
       current_timestamp() AS SnapshotAsOfUTC FROM {catalog.name}.core.inventory_stock_inventory
""")
