from pyspark.sql.functions import (
    sequence,
    explode,
    to_date,
    col,
    date_format,
    lit,
    expr
)

# Parameter
start_date = "2000-01-01"
end_date   = "2010-12-31"

# Generate all dates between start_date and end_date
dates_df = (
    spark.range(1)  # Dummy row
    .select(
        explode(
            sequence(
                to_date(lit(start_date)),
                to_date(lit(end_date)),
                expr("interval 1 day")
            )
        ).alias("Date")
    )
)

result_df = (
    dates_df
    # Calendar date als timestamp oder date
    .withColumn("Date", col("Date").cast("date"))
    
    # CalendarYear als String
    .withColumn("CalendarYear", date_format(col("Date"), "yyyy"))
    
    # Monatname Englisch
    .withColumn("MonthName", date_format(col("Date"), "MMMM"))
    
    # DateID: numerisches Format yyyyMMdd
    .withColumn("DateID", date_format(col("Date"), "yyyyMMdd").cast("int"))
)

business_function = result_df.select(
    "DateID",
    "Date",
    "CalendarYear",
    "MonthName"
)

unknown_date = spark.createDataFrame(
    [(-1, "1900-01-01", "Unknown", "Unknown")],
    "DateID INT, Date STRING, CalendarYear STRING, MonthName STRING",
).withColumn("Date", col("Date").cast("date"))

business_function = unknown_date.unionByName(business_function)
