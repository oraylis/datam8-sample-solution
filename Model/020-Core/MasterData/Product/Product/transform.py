business_function = spark.sql(f"""
SELECT p.ProductID, p.Name AS ProductName, p.ProductNumber,
       c.Name AS CategoryName, m.Name AS ModelName,
       CAST(p.StandardCost AS DECIMAL(18,4)) AS StandardCost,
       CAST(p.ListPrice AS DECIMAL(18,4)) AS ListPrice
FROM {catalog.name}.stage.adventureworks_saleslt_product p
LEFT JOIN {catalog.name}.stage.adventureworks_saleslt_productcategory c ON p.ProductCategoryID=c.ProductCategoryID
LEFT JOIN {catalog.name}.stage.adventureworks_saleslt_productmodel m ON p.ProductModelID=m.ProductModelID
""")
