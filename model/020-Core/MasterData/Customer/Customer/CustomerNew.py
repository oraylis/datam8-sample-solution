from pyspark.sql import functions as F

customer = spark.table(f"{catalog.name}.stage.adventureworks_saleslt_customer")
customeraddress = spark.table(f"{catalog.name}.stage.adventureworks_saleslt_customeraddress")

business_function = (
    customer.alias("c")
    .join(
        other=customeraddress.alias("ca"),
        how="left",
        on=[
            F.col("c.KundenID") == F.col("ca.CustomerID"),
            F.col("ca.AddressType") == "Main Office"
        ]
    )
    .filter("c.__IsCurrent = True")
    .select(
        F.col("c.KundenID").alias("KundenNummer"),
        F.col("c.SourceSystem"),
        "c.Vorname",
        "c.Nachname",
        "ca.AddressType",
    )
    .fillna({
        "AddressType": "N/A"
    })
)
