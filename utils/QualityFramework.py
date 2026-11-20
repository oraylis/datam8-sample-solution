"""Technical quality validation and audit I/O; execution stays in notebooks.

DQX is needed only when quality-enabled artifacts execute. No cloud I/O occurs
at import time. Target writes remain owned by generated DML notebooks.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone


class QualityThresholdExceeded(RuntimeError):
    pass


def context(spark, target_table, spec, job_run_id="", attempt_id=""):
    return {
        "spark": spark,
        "target": target_table.replace("`", ""),
        "entityId": spec["entityId"],
        "ruleSetHash": spec["ruleSetHash"],
        "runId": str(job_run_id or uuid.uuid4()),
        "attemptId": str(attempt_id or "0"),
        "evaluatedAt": datetime.now(timezone.utc),
    }


def validate_aggregate_result(df):
    """Validate the fixed scalar-query schema and values without changing data."""
    from pyspark.sql import types as T

    if len(df.columns) != 2 or set(df.columns) != {"checked_rows", "measured_value"}:
        raise ValueError("Monitoring SQL must return exactly checked_rows and measured_value")
    count_type = df.schema["checked_rows"].dataType
    if not (
        isinstance(count_type, (T.ByteType, T.ShortType, T.IntegerType, T.LongType))
        or isinstance(count_type, T.DecimalType)
        and count_type.scale == 0
    ):
        raise ValueError("checked_rows must have an integer data type")
    measure_type = df.schema["measured_value"].dataType
    if not isinstance(measure_type, (T.NumericType, T.NullType)):
        raise ValueError("measured_value must be numeric or NULL")
    rows = df.take(2)
    if len(rows) != 1:
        raise ValueError("Monitoring SQL must return exactly one row")
    row = rows[0]
    count = row["checked_rows"]
    measured = row["measured_value"]
    if count is None or isinstance(count, bool) or not 0 <= count <= 9223372036854775807:
        raise ValueError("checked_rows must be a nonnegative, non-NULL BIGINT-compatible integer")
    if measured is not None and not math.isfinite(float(measured)):
        raise ValueError("measured_value must be finite or NULL")
    return {"checked_rows": int(count), "measured_value": measured}


def validate_target_columns(schema):
    if any(f.name.startswith("__dm8_dq_") or f.name in ("_errors", "_warnings", "_dq_info") for f in schema):
        raise ValueError("Target uses reserved quality audit column names")


def quote(name):
    return "`" + name.replace("`", "``") + "`"


def metric(rule, ctx, execution, total, failed, measured, status):
    return {
        "entity_id": int(ctx["entityId"]),
        "target_table": ctx["target"],
        "run_id": ctx["runId"],
        "attempt_id": ctx["attemptId"],
        "rule_set_hash": ctx["ruleSetHash"],
        "check_id": rule["id"],
        "execution": execution,
        "severity": rule.get("severity", "error"),
        "evaluated_at": ctx["evaluatedAt"],
        "checked_rows": int(total),
        "failed_rows": int(failed) if failed is not None else None,
        "measured_value": float(measured) if measured is not None else None,
        "parameters": json.dumps(rule, sort_keys=True),
        "status": status,
    }


def write_quarantine(invalid, error_count, ctx):
    from pyspark.sql import functions as F

    if invalid is None or not error_count:
        return
    audit = F.to_json(
        F.struct(
            F.col("_errors").alias("errors"),
            F.col("_warnings").alias("warnings"),
            F.lit(ctx["runId"]).alias("runId"),
            F.lit(ctx["attemptId"]).alias("attemptId"),
            F.lit(ctx["ruleSetHash"]).alias("ruleSetHash"),
            F.lit(ctx["evaluatedAt"]).alias("evaluatedAt"),
        )
    )
    rows = invalid.withColumn("__dm8_dq_audit", audit).drop("_errors", "_warnings", "_dq_info")
    (
        rows.write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .option("txnAppId", f"dm8-quality-quarantine:{ctx['entityId']}:{ctx['runId']}:{ctx['attemptId']}")
        .option("txnVersion", 0)
        .saveAsTable(ctx["target"] + "_quarantine")
    )


def write_metrics(metrics, ctx):
    if not metrics:
        return
    spark = ctx["spark"]
    table = quote(ctx["target"].replace("`", "").split(".")[0]) + ".quality.dqx_metrics"
    schema = spark.table(table).schema
    rows = spark.createDataFrame(metrics, schema=schema)
    execution = metrics[0]["execution"]
    (
        rows.write.format("delta")
        .mode("append")
        .option("txnAppId", f"dm8-quality-metrics:{execution}:{ctx['entityId']}:{ctx['runId']}:{ctx['attemptId']}")
        .option("txnVersion", 0)
        .saveAsTable(table)
    )
    return rows
