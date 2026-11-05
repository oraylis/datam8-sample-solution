from pyspark.sql import functions as F

start_date = globals().get("sample_date_start", "2000-01-01")
end_date = globals().get("sample_date_end", "2030-12-31")

date_values = spark.range(1).select(
    F.explode(
        F.sequence(
            F.to_date(F.lit(start_date)),
            F.to_date(F.lit(end_date)),
            F.expr("interval 1 day"),
        )
    ).alias("Date")
)
business_function = date_values.select(
    F.to_timestamp("Date").alias("Date"),
).select(
    F.date_format("Date", "yyyyMMdd").cast("int").alias("DateID"),
    "Date",
    F.date_format("Date", "yyyy").alias("CalendarYear"),
    F.date_format("Date", "MMMM").alias("MonthName"),
)
unknown_date = spark.createDataFrame([(0,)], "DateID int").select(
    "DateID",
    F.to_timestamp(F.lit("1900-01-01")).alias("Date"),
    F.lit("Unknown").alias("CalendarYear"),
    F.lit("Unknown").alias("MonthName"),
)
business_function = business_function.unionByName(unknown_date)
