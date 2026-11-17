"""Technical quality validation and audit I/O; execution stays in notebooks.

DQX is needed only when quality-enabled artifacts execute. No cloud I/O occurs
at import time. Target writes remain owned by generated DML notebooks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class QualityThresholdExceeded(RuntimeError):
    pass


def load_checks(manifest_path):
    import yaml
    from databricks.labs.dqx.engine import DQEngineCore

    path = Path(manifest_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["checks"] = {}
    for mode, filename in spec["files"].items():
        checks = yaml.safe_load((path.parent / filename).read_text(encoding="utf-8"))
        status = DQEngineCore.validate_checks(checks)
        if status.has_errors:
            raise ValueError(f"Invalid generated DQX checks: {status}")
        spec["checks"][mode] = checks
    return spec


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


def validate_check_inputs(df, checks):
    from pyspark.sql import functions as F, types as T

    # DQX can report an invalid expression/column as skipped. Resolve supported
    # inputs first so technical configuration errors also fail on empty data.
    for check in checks:
        arguments = check["check"].get("arguments", {})
        if check["check"]["function"] == "sql_expression":
            datatype = df.select(F.expr(arguments["expression"])).schema.fields[0].dataType
            if not isinstance(datatype, T.BooleanType):
                raise ValueError(f"Quality SQL check {check['name']} must return BOOLEAN")
        elif "column" in arguments:
            df.select(F.col(arguments["column"])).schema


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
        "severity": rule["severity"],
        "evaluated_at": ctx["evaluatedAt"],
        "checked_rows": int(total),
        "failed_rows": int(failed) if failed is not None else None,
        "measured_value": float(measured) if measured is not None else None,
        "parameters": json.dumps(rule.get("parameters", {}), sort_keys=True),
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
