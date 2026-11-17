"""Shared batch DQX runtime. Importable locally and from generated notebooks.

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


def _engine(ctx):
    from databricks.sdk import WorkspaceClient
    from databricks.labs.dqx.engine import DQEngineCore

    return DQEngineCore(WorkspaceClient(), ctx["spark"])


def _apply_checks(df, checks, ctx):
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
    return _engine(ctx).apply_checks_by_metadata(df, checks)


def _has_result(column, check_id=None):
    from pyspark.sql import functions as F

    if check_id is None:
        return F.coalesce(F.size(F.col(column)) > 0, F.lit(False))
    return F.coalesce(F.exists(F.col(column), lambda result: result["name"] == check_id), F.lit(False))


def _records(checked, rules, ctx, execution):
    from pyspark.sql import functions as F

    aggs = [F.count("*").alias("total"), F.sum(F.when(_has_result("_errors"), 1).otherwise(0)).alias("errors")]
    for i, rule in enumerate(rules):
        result = "_errors" if rule["severity"] == "error" else "_warnings"
        aggs.append(F.sum(F.when(_has_result(result, rule["id"]), 1).otherwise(0)).alias(f"c{i}"))
    row = checked.agg(*aggs).first().asDict()
    total = row["total"]
    metrics = []
    for i, rule in enumerate(rules):
        failed = row[f"c{i}"] or 0
        metrics.append(
            _metric(
                rule,
                ctx,
                execution,
                total,
                failed,
                failed / total if total else None,
                "NO_DATA" if not total else "FAILED" if failed else "PASSED",
            )
        )
    return total, row["errors"] or 0, metrics


def _metric(rule, ctx, execution, total, failed, measured, status):
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


def enforce(df, spec, ctx):
    """Evaluate once, preserve warning rows, retain error rows for quarantine."""
    rules = [c for c in spec["quality"]["checks"] if c["execution"] == "enforcement"]
    if not rules:
        return {
            "valid": df,
            "invalid": None,
            "metrics": [],
            "total": None,
            "errors": 0,
            "checked": None,
            "threshold": None,
        }
    checked = _apply_checks(df, spec["checks"]["enforcement"], ctx).persist()
    try:
        total, errors, metrics = _records(checked, rules, ctx, "enforcement")
    except Exception:
        checked.unpersist()
        raise
    return {
        "valid": checked.where(~_has_result("_errors")).select(*df.columns),
        "invalid": checked.where(_has_result("_errors")),
        "metrics": metrics,
        "total": total,
        "errors": errors,
        "checked": checked,
        "threshold": spec["quality"].get("settings", {}).get("maxFailureRatePct"),
    }


def _quote(name):
    return "`" + name.replace("`", "``") + "`"


def ensure_tables(spark, target_table):
    """Quarantine allows invalid NULLs and excludes identity/generated constraints."""
    from pyspark.sql import types as T

    parts = target_table.replace("`", "").split(".")
    if len(parts) != 3:
        raise ValueError("Quality requires a fully qualified target table")
    catalog = parts[0]
    schema = spark.table(target_table).schema
    if any(f.name.startswith("__dm8_dq_") or f.name in ("_errors", "_warnings", "_dq_info") for f in schema):
        raise ValueError("Target uses reserved quality audit column names")
    fields = [T.StructField(f.name, f.dataType, True) for f in schema]
    fields += [T.StructField("__dm8_dq_audit", T.StringType(), True)]
    empty = spark.createDataFrame([], T.StructType(fields))
    empty.write.format("delta").mode("ignore").saveAsTable(target_table + "_quarantine")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {_quote(catalog)}.quality")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {_quote(catalog)}.quality.dqx_metrics (
        entity_id BIGINT, target_table STRING, run_id STRING, attempt_id STRING, rule_set_hash STRING,
        check_id STRING, execution STRING, severity STRING, evaluated_at TIMESTAMP, checked_rows BIGINT,
        failed_rows BIGINT, measured_value DOUBLE, parameters STRING, status STRING) USING DELTA""")


def write_quarantine(result, ctx):
    from pyspark.sql import functions as F

    invalid = result["invalid"]
    if invalid is None or not result["errors"]:
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
    table = _quote(ctx["target"].replace("`", "").split(".")[0]) + ".quality.dqx_metrics"
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


def finish_enforcement(result, ctx):
    """Call only after a successful target write (or a deliberate empty skip)."""
    try:
        write_metrics(result["metrics"], ctx)
        total, threshold = result["total"], result["threshold"]
        if total and threshold is not None and 100 * result["errors"] / total > threshold:
            raise QualityThresholdExceeded(
                f"Quality error rate {100 * result['errors'] / total:.2f}% exceeds {threshold}% "
                "after writing valid rows"
            )
    finally:
        if result["checked"] is not None:
            result["checked"].unpersist()


def monitor(spec, ctx):
    """Read the committed target; persist metrics without writing target rows."""
    from pyspark.sql import functions as F

    df = ctx["spark"].table(ctx["target"])
    rules = [c for c in spec["quality"]["checks"] if c["execution"] == "monitoring"]
    row_rules = [c for c in rules if c["type"] not in ("completeness", "freshness", "row_count")]
    metrics = []
    if row_rules:
        checked = _apply_checks(df, spec["checks"]["monitoring_rows"], ctx)
        _, _, metrics = _records(checked, row_rules, ctx, "monitoring")
    summary_rules = [c for c in rules if c not in row_rules]
    if summary_rules:
        aggregates = [F.count("*").alias("__dm8_total")]
        for rule in summary_rules:
            kind = rule["type"]
            if kind == "row_count":
                measure = F.count("*")
            elif kind == "completeness":
                measure = F.count(F.col(_quote(rule["attribute"]))) / F.when(F.count("*") > 0, F.count("*"))
            else:
                measure = F.lit(ctx["evaluatedAt"]).cast("double") - F.max(F.col(_quote(rule["attribute"]))).cast(
                    "double"
                )
            aggregates.append(measure.alias("__dm8_q_" + rule["id"]))
        summary = df.agg(*aggregates)
        checked = _apply_checks(summary, spec["checks"]["monitoring_summary"], ctx)
        value = checked.first().asDict(recursive=True)
        failed_ids = {r["name"] for r in (value.get("_errors") or []) + (value.get("_warnings") or [])}
        for rule in summary_rules:
            total = value["__dm8_total"]
            measured = value["__dm8_q_" + rule["id"]]
            status = (
                "NO_DATA"
                if not total and rule["type"] == "completeness"
                else "FAILED"
                if rule["id"] in failed_ids
                else "PASSED"
            )
            metrics.append(_metric(rule, ctx, "monitoring", total, None, measured, status))
    write_metrics(metrics, ctx)
    return metrics
