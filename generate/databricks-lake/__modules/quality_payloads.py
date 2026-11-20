"""Solution-owned native DQX metadata and literal monitoring table bindings."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from datam8.errors import Datam8ValidationError
from datam8.quality import validate_quality_value


def quoted(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def bind_monitoring_sql(sql: str, references: dict) -> tuple[str, list[str]]:
    """Bind placeholders outside quotes/comments; leave every other byte alone.

    This scanner does not parse or validate SQL. IDENTIFIER parameters keep model
    table bindings separate from SQL text. Quoted tokens, escaped/doubled quotes,
    line comments and nested block comments are copied verbatim.
    """
    parts, used = [], set()
    index = 0
    while index < len(sql):
        start = index
        if sql[index] in ("'", '"', "`"):
            quote = sql[index]
            raw = (
                index > 0
                and sql[index - 1] in "rR"
                and (index < 2 or not (sql[index - 2].isalnum() or sql[index - 2] == "_"))
            )
            backslash_escape = quote != "`" and not raw
            delimiter = quote * 3 if quote != "`" and sql.startswith(quote * 3, index) else quote
            index += len(delimiter)
            while index < len(sql):
                if backslash_escape and sql[index] == "\\":
                    index += 2
                elif sql.startswith(delimiter, index):
                    index += len(delimiter)
                    if len(delimiter) == 1 and sql.startswith(delimiter, index):
                        index += 1
                    else:
                        break
                else:
                    index += 1
        elif sql.startswith("--", index):
            while index < len(sql) and sql[index] not in "\r\n":
                index += 1
        elif sql.startswith("/*", index):
            index += 2
            depth = 1
            while index < len(sql) and depth:
                if sql.startswith("/*", index):
                    depth += 1
                    index += 2
                elif sql.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
        elif sql.startswith("{target}", index):
            parts.append("IDENTIFIER(:dm8_target)")
            index += len("{target}")
            continue
        elif sql.startswith("{references.", index) and "}" in sql[index:]:
            end = sql.index("}", index)
            alias = sql[index + len("{references.") : end]
            if alias not in references:
                raise ValueError("Unknown quality reference alias: " + alias)
            used.add(alias)
            parts.append("IDENTIFIER(:dm8_ref_" + alias + ")")
            index = end + 1
            continue
        else:
            index += 1
        parts.append(sql[start:index])
    return "".join(parts), sorted(used)


def native_check(rule: dict[str, Any]) -> dict[str, Any]:
    arguments = {"expression": rule["expression"]}
    if "description" in rule:
        arguments["msg"] = rule["description"]
    return {
        "name": rule["id"],
        "criticality": "warn" if rule.get("severity", "error") == "warning" else "error",
        "check": {"function": "sql_expression", "arguments": arguments},
    }


def notebook_quality(entity: Any, target: str) -> dict[str, Any] | None:
    quality = getattr(entity, "quality", None)
    if quality is None or not quality.checks:
        return None
    value = quality.model_dump(mode="json", exclude_none=True)
    validate_quality_value(value)
    checks = value["checks"]
    enforcement = [r for r in checks if r["execution"] == "enforcement"]
    rows = [r for r in checks if r["execution"] == "monitoring" and "sql" not in r]
    aggregates, references = [], set()
    for rule in checks:
        if "sql" not in rule:
            continue
        try:
            sql, used = bind_monitoring_sql(rule["sql"], value.get("references", {}))
        except ValueError as error:
            raise Datam8ValidationError(
                message=f"Entity {entity.id} quality check {rule['id']} sql binding: {error}",
                details={"entityId": entity.id, "checkId": rule["id"], "field": f"quality.checks.{rule['id']}.sql"},
            ) from error
        references.update(used)
        aggregates.append(
            {
                "rule_literal": repr(rule),
                "checks_literal": repr([native_check(rule)]),
                "sql_literal": sql_python_literal(sql),
            }
        )
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    spec = {
        "config_literal": repr({"entityId": entity.id, "ruleSetHash": digest, "target": target, "quality": value}),
        "enforcement": enforcement,
        "enforcement_checks_literal": repr([native_check(r) for r in enforcement]),
        "monitoring_rows": rows,
        "row_checks_literal": repr([native_check(r) for r in rows]),
        "monitoring_aggregates": aggregates,
        "used_references": sorted(references),
    }
    heading = ["| ID | Execution | Severity | Expression | On empty |", "| --- | --- | --- | --- | --- |"]
    for mode in ("enforcement", "monitoring", "all"):
        lines = heading + [
            "| "
            + " | ".join(
                str(v).replace("|", "&#124;").replace("\n", " ")
                for v in [
                    r["id"],
                    r["execution"],
                    r.get("severity", "error"),
                    r["expression"],
                    r.get("onEmpty", "evaluate") if "sql" in r else "NO_DATA",
                ]
            )
            + " |"
            for r in checks
            if mode == "all" or r["execution"] == mode
        ]
        spec["overview" if mode == "all" else "overview_" + mode] = "\n".join("# MAGIC " + line for line in lines)
    return spec


def quality_ddl(columns: list[dict], zone: str, table: str, *, enforcement: bool = True) -> dict[str, str]:
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
        f"{quoted(table + '_quarantine')} (\n  " + ",\n  ".join(fields) + "\n) USING DELTA;",
        "metrics_schema_sql": "CREATE SCHEMA IF NOT EXISTS `{catalog_name}`.quality;",
        "metrics_sql": """CREATE TABLE IF NOT EXISTS `{catalog_name}`.quality.dqx_metrics (
  entity_id BIGINT, target_table STRING, run_id STRING, attempt_id STRING, rule_set_hash STRING,
  check_id STRING, execution STRING, severity STRING, evaluated_at TIMESTAMP, checked_rows BIGINT,
  failed_rows BIGINT, measured_value DOUBLE, parameters STRING, status STRING
) USING DELTA;""",
    }
    if not enforcement:
        del statements["quarantine_sql"]
    return {name: sql_python_literal(sql) for name, sql in statements.items()}


def sql_python_literal(sql: str) -> str:
    """Keep SQL readable across source lines without allowing Python string escapes."""
    return '"""' + sql.replace("\\", "\\\\").replace('"""', '\\"""') + '"""'
