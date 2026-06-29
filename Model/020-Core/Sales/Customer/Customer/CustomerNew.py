from pyspark.sql import functions as F

stage_schema = f"{schema_prefix}stage" if schema_prefix else "stage"
customer = spark.table(f"{catalog_name}.{stage_schema}.sales_customer_customer")
customeraddress = spark.table(f"{catalog_name}.{stage_schema}.sales_customer_customeraddress")

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
    .select(
        F.col("c.KundenID").alias("KundenNummer"),
        "c.Vorname",
        "c.Nachname",
        "ca.AddressType",
    )
    .fillna({
        "AddressType": "N/A"
    })
    .distinct()
)
