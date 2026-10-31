"""Lazy frame shaping for declarative datasets; contains no Spark actions."""


def try_cast_expression(name, data_type):
    quoted_name = "`" + name.replace("`", "``") + "`"
    return f"try_cast({quoted_name} AS {data_type})"


def try_cast_columns(frame, columns):
    from pyspark.sql import functions as F
    for column in columns:
        name = column["name"]
        frame = frame.withColumn(name, F.expr(try_cast_expression(name, column["type"])))
    return frame.select(*[column["name"] for column in columns])


def validate_unique_keys(frame, keys, dataset_name, sequence_by=None):
    """Fail CDC input when keys are null or the same key/version is repeated."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    if not keys:
        raise ValueError(f"{dataset_name}: merge input requires business keys")

    uniqueness_columns = [*keys, *([sequence_by] if sequence_by else [])]
    duplicates = F.count(F.lit(1)).over(Window.partitionBy(*[F.col(key) for key in uniqueness_columns])) > 1
    invalid = duplicates
    for key in keys:
        invalid = invalid | F.col(key).isNull()
    if sequence_by:
        invalid = invalid | F.col(sequence_by).isNull()

    detail = "business keys and sequence values" if sequence_by else "business keys"
    failure = F.raise_error(F.lit(f"{dataset_name}: input contains null or duplicate {detail}"))
    for key in keys:
        frame = frame.withColumn(key, F.when(invalid, failure).otherwise(F.col(key)))
    return frame


def apply_dimension_lookups(frame, lookups, spark, catalog_name):
    from pyspark.sql import functions as F
    for lookup in lookups:
        dimension = spark.read.table(catalog_name + "." + lookup["dataset"])
        if lookup.get("current_filter"):
            dimension = dimension.filter(lookup["current_filter"])
        condition = None
        for key in lookup["joins"]:
            comparison = F.col("source.`" + key["source"] + "`") == F.col("dimension.`" + key["target"] + "`")
            condition = comparison if condition is None else condition & comparison
        frame = frame.alias("source").join(dimension.alias("dimension"), condition, "left").select("source.*", *[F.col("dimension.`" + name + "`").alias(name) for name in lookup["columns"]])
    return frame


def project_dataset(frame, specification, spark, catalog_name, *, include_surrogates=True, technical=True, history=False, apply_lookups=True):
    from pyspark.sql import functions as F
    surrogates = set(specification["surrogates"])
    if apply_lookups:
        frame = apply_dimension_lookups(frame, specification["lookups"], spark, catalog_name)
    # Canonicalize business values before hashing; source representation and
    # model attribute order must not affect a surrogate key.
    for column in specification["columns"]:
        name = column["name"]
        if name in surrogates:
            continue
        if column.get("expression"):
            frame = frame.withColumn(name, F.expr(column["expression"]))
        frame = frame.withColumn(name, F.expr(try_cast_expression(name, column["type"])))
    if include_surrogates:
        for column in specification["columns"]:
            if column["name"] not in surrogates:
                continue
            components = [F.col(key).alias(key) for key in sorted(specification["keys"])]
            if history:
                components.append(F.coalesce(F.unix_micros(F.col("__START_AT")), F.lit(-1)).alias("__version"))
            expression = F.xxhash64(F.to_json(F.struct(*components), options={"ignoreNullFields": "false"}))
            frame = frame.withColumn(column["name"], expression)
    names = [column["name"] for column in specification["columns"] if include_surrogates or column["name"] not in surrogates]
    output = frame.select(*names, *(["__START_AT", "__END_AT"] if history else []))
    if technical:
        output = output.withColumn("__IsCurrent", F.col("__END_AT").isNull() if history else F.lit(True))
        inserted_at = F.col("__START_AT") if history else F.current_timestamp()
        output = output.withColumn("__InsertTimestampUTC", inserted_at).withColumn("__UpdateTimestampUTC", inserted_at)
        if history:
            output = output.withColumn("__ValidFrom", F.col("__START_AT")).withColumn("__ValidTo", F.col("__END_AT"))
    return output
