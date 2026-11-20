# Synthetic model reference fixture; never reads a live source.
business_function = spark.createDataFrame([(1,), (2,)], "Id INT")
