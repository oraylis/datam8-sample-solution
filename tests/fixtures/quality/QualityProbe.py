# Synthetic acceptance input only; never reads a live source.
dbutils.widgets.text("quality_input_table", "")
business_function = spark.table(dbutils.widgets.get("quality_input_table"))
