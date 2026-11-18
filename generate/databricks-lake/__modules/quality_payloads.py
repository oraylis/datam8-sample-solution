"""Native DQX artifacts derived directly from DataM8 quality requirements."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def quoted(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def quality_spec(entity: Any) -> dict[str, Any] | None:
    quality = getattr(entity, "quality", None)
    if quality is None or not quality.checks:
        return None
    value = quality.model_dump(mode="json", exclude_none=True)
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"entityId": entity.id, "ruleSetHash": digest, "quality": value}


def native_check(check: dict[str, Any]) -> dict[str, Any]:
    if check["type"] == "dqx":
        native = copy.deepcopy(check["definition"])
        native.setdefault("name", check["id"])
        native["user_metadata"] = {**(native.get("user_metadata") or {}), "datam8_check_id": check["id"]}
        return native
    kind, params = check["type"], check.get("parameters", {})
    attr = quoted(check.get("attribute", ""))
    if kind == "not_null":
        function, args = "is_not_null", {"column": attr}
    elif kind == "range":
        if "min" in params and "max" in params:
            function, args = "is_in_range", {"column": attr, "min_limit": params["min"], "max_limit": params["max"]}
        else:
            low = "min" in params
            function, args = (
                "is_not_less_than" if low else "is_not_greater_than",
                {"column": attr, "limit": params["min" if low else "max"]},
            )
    else:
        column = quoted("__dm8_q_" + check["id"])
        expression = params.get("expression", "")
        if kind == "completeness":
            expression = f"{column} >= {params['minCompleteness']}"
        elif kind == "freshness":
            expression = f"{column} BETWEEN 0 AND {params['maxAgeSeconds']}"
        elif kind == "row_count":
            expression = " AND ".join(
                f"{column} {op} {params[key]}" for key, op in (("minCount", ">="), ("maxCount", "<=")) if key in params
            )
        function, args = (
            "sql_expression",
            {"expression": f"COALESCE(({expression}), FALSE)", "msg": check.get("description") or check["id"]},
        )
    return {
        "name": check["id"],
        "criticality": "warn" if check["severity"] == "warning" else "error",
        "check": {"function": function, "arguments": args},
    }


def quality_files(entity: Any) -> dict[Path, str]:
    spec = quality_spec(entity)
    if spec is None:
        return {}
    groups: dict[str, list[dict[str, Any]]] = {"enforcement": [], "monitoring_rows": [], "monitoring_summary": []}
    for check in spec["quality"]["checks"]:
        group = (
            "enforcement"
            if check["execution"] == "enforcement"
            else "monitoring_summary"
            if check["type"] in ("completeness", "freshness", "row_count")
            else "monitoring_rows"
        )
        groups[group].append(native_check(check))
    root = Path("quality", str(entity.id))
    files = {
        root / f"{group}.yaml": yaml.safe_dump(checks, sort_keys=False, allow_unicode=True)
        for group, checks in groups.items()
    }
    spec["files"] = {group: f"{group}.yaml" for group in groups}
    files[root / "manifest.json"] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    return files


def notebook_quality(entity: Any) -> dict[str, Any] | None:
    spec = quality_spec(entity)
    if spec is None:
        return None
    checks = spec["quality"]["checks"]
    spec["enforcement"] = [c for c in checks if c["execution"] == "enforcement"]
    spec["monitoring_rows"] = [
        c
        for c in checks
        if c["execution"] == "monitoring" and c["type"] not in ("completeness", "freshness", "row_count")
    ]
    spec["monitoring_summary"] = [
        c for c in checks if c["execution"] == "monitoring" and c not in spec["monitoring_rows"]
    ]
    overview = [
        "| ID | Execution | Severity | Type | Attribute | Parameters |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        values = [
            c["id"],
            c["execution"],
            c.get("severity", "warning" if c.get("definition", {}).get("criticality") == "warn" else "error"),
            c["type"],
            c.get("attribute", ""),
            json.dumps(c.get("parameters", c.get("definition", {})), ensure_ascii=False),
        ]
        overview.append("| " + " | ".join(str(v).replace("|", "&#124;").replace("\n", " ") for v in values) + " |")
    spec["overview"] = "\n".join("# MAGIC " + line for line in overview)
    for execution in ("enforcement", "monitoring"):
        lines = overview[:2] + [line for line, check in zip(overview[2:], checks) if check["execution"] == execution]
        spec["overview_" + execution] = "\n".join("# MAGIC " + line for line in lines)
    aggregates = ["COUNT(*) AS `__dm8_total`"]
    for c in spec["monitoring_summary"]:
        attr = quoted(c.get("attribute", ""))
        expression = (
            "COUNT(*)"
            if c["type"] == "row_count"
            else f"COUNT({attr}) / NULLIF(COUNT(*), 0)"
            if c["type"] == "completeness"
            else f"CAST(:evaluated_at AS DOUBLE) - CAST(MAX({attr}) AS DOUBLE)"
        )
        aggregates.append(expression + " AS " + quoted("__dm8_q_" + c["id"]))
    spec["summary_sql"] = "SELECT\n  " + ",\n  ".join(aggregates) + "\nFROM {target_table}"
    spec["summary_sql_literal"] = sql_python_literal(spec["summary_sql"])
    return spec


def quality_ddl(columns: list[dict], zone: str, table: str) -> dict[str, str]:
    reserved = [
        c["name"]
        for c in columns
        if c["name"].startswith("__dm8_dq_") or c["name"] in ("_errors", "_warnings", "_dq_info")
    ]
    if reserved:
        raise ValueError("Target uses reserved quality audit column names: " + ", ".join(reserved))
    fields = [f"{quoted(c['name'])} {c['delta_type']}" for c in columns]
    fields.append("`__dm8_dq_audit` STRING")
    statements = {
        "quarantine_sql": f"CREATE TABLE IF NOT EXISTS `{{catalog_name}}`.{quoted(zone)}."
        f"{quoted(table + '_quarantine')} (\n  "
        + ",\n  ".join(fields)
        + "\n) USING DELTA;",
        "metrics_schema_sql": "CREATE SCHEMA IF NOT EXISTS `{catalog_name}`.quality;",
        "metrics_sql": """CREATE TABLE IF NOT EXISTS `{catalog_name}`.quality.dqx_metrics (
  entity_id BIGINT, target_table STRING, run_id STRING, attempt_id STRING, rule_set_hash STRING,
  check_id STRING, execution STRING, severity STRING, evaluated_at TIMESTAMP, checked_rows BIGINT,
  failed_rows BIGINT, measured_value DOUBLE, parameters STRING, status STRING
) USING DELTA;""",
    }
    return {name: sql_python_literal(sql) for name, sql in statements.items()}


def sql_python_literal(sql: str) -> str:
    """Keep SQL readable across source lines without allowing Python string escapes."""
    return '"""' + sql.replace("\\", "\\\\").replace('"""', '\\"""') + '"""'
