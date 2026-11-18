"""DQX target artifacts from opaque, tool-neutral model definitions."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from datam8.errors import Datam8ValidationError


def quoted(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def validate_target_quality(value: dict[str, Any]) -> None:
    settings = value.get("settings", {})
    unknown = set(settings) - {"maxFailureRatePct", "dependencies", "inputs"}
    if unknown:
        raise ValueError("Unsupported Databricks quality settings: " + ", ".join(sorted(unknown)))
    dependencies = settings.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(v, str) or not v.strip() for v in dependencies):
        raise ValueError("Databricks quality dependencies must be PyPI requirement strings")
    inputs = settings.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("Databricks quality inputs must be named SQL input objects")
    for alias, config in inputs.items():
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", alias)
            or alias == "rows"
            or not isinstance(config, dict)
            or set(config) != {"sql"}
            or not isinstance(config["sql"], str)
            or not config["sql"].strip()
        ):
            raise ValueError(f"Invalid Databricks monitoring input {alias}")
    for alias, binding in value.get("referenceDatasets", {}).items():
        if (
            ("entityId" in binding) == ("table" in binding)
            or set(binding) - {"entityId", "table", "execution"}
            or ("table" in binding and (not isinstance(binding["table"], str) or not binding["table"].strip()))
        ):
            raise ValueError(f"DQX reference {alias} requires an entityId or a table binding")
    for rule in value["checks"]:
        definition = rule["definition"]
        check = definition.get("check")
        if not isinstance(check, dict) or not isinstance(check.get("function"), str) or not check["function"].strip():
            raise ValueError(f"DQX target requires definition.check.function for {rule['id']}")
        metadata = definition.get("user_metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict) or "datam8_check_id" in metadata:
            raise ValueError(f"DQX user_metadata.datam8_check_id is reserved: {rule['id']}")
        options = definition.get("datam8", {})
        if not isinstance(options, dict) or set(options) - {"input", "metrics"}:
            raise ValueError(f"Invalid Databricks execution options for {rule['id']}")
        if rule["execution"] == "enforcement" and options:
            raise ValueError(
                "Enforcement evaluates original input; SQL inputs/metric projections are monitoring options"
            )
        if "input" in options and (not isinstance(options["input"], str) or options["input"] not in inputs):
            raise ValueError(f"Unknown monitoring input for {rule['id']}")
        if "metrics" in options:
            metrics = options["metrics"]
            if (
                not isinstance(metrics, dict)
                or "checked_rows" not in metrics
                or set(metrics) - {"checked_rows", "failed_rows", "measured_value", "no_data_when"}
                or any(not isinstance(v, str) or not v.strip() for v in metrics.values())
            ):
                raise ValueError(f"Invalid metric projection for {rule['id']}")


def quality_spec(entity: Any) -> dict[str, Any] | None:
    quality = getattr(entity, "quality", None)
    if quality is None or not quality.checks:
        return None
    value = quality.model_dump(mode="json", exclude_none=True)
    try:
        validate_target_quality(value)
    except ValueError as error:
        raise Datam8ValidationError(
            message="Databricks quality target: " + str(error),
            details={"entityId": entity.id, "field": "quality"},
        ) from error
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"entityId": entity.id, "ruleSetHash": digest, "quality": value}


def native_check(rule: dict[str, Any]) -> dict[str, Any]:
    native = copy.deepcopy(rule["definition"])
    native.pop("datam8", None)
    native.setdefault("name", rule["id"])
    native["user_metadata"] = {**(native.get("user_metadata") or {}), "datam8_check_id": rule["id"]}
    return native


def monitoring_groups(spec: dict[str, Any]) -> list[dict[str, Any]]:
    groups = {}
    inputs = spec["quality"].get("settings", {}).get("inputs", {})
    for rule in spec["quality"]["checks"]:
        if rule["execution"] != "monitoring":
            continue
        alias = rule["definition"].get("datam8", {}).get("input")
        key = "monitoring_" + (alias or "rows")
        if key not in groups:
            sql = inputs[alias]["sql"] if alias else None
            groups[key] = {
                "key": key,
                "input": alias or "target",
                "rules": [],
                "sql_literal": sql_python_literal(sql) if sql else None,
                "ids": [],
            }
        groups[key]["rules"].append(rule)
        groups[key]["ids"].append(rule["id"])
    return list(groups.values())


def quality_files(entity: Any) -> dict[Path, str]:
    spec = quality_spec(entity)
    if spec is None:
        return {}
    groups = {"enforcement": [r for r in spec["quality"]["checks"] if r["execution"] == "enforcement"]}
    groups.update({g["key"]: g["rules"] for g in monitoring_groups(spec)})
    root = Path("quality", str(entity.id))
    files = {
        root / f"{name}.yaml": yaml.safe_dump([native_check(r) for r in rules], sort_keys=False, allow_unicode=True)
        for name, rules in groups.items()
    }
    spec["files"] = {name: f"{name}.yaml" for name in groups}
    files[root / "manifest.json"] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    return files


def notebook_quality(entity: Any) -> dict[str, Any] | None:
    spec = quality_spec(entity)
    if spec is None:
        return None
    checks = spec["quality"]["checks"]
    spec["enforcement"] = [r for r in checks if r["execution"] == "enforcement"]
    spec["monitoring_groups"] = monitoring_groups(spec)
    heading = ["| ID | Execution | Definition |", "| --- | --- | --- |"]
    lines = [
        "| "
        + " | ".join(
            str(v).replace("|", "&#124;").replace("\n", " ")
            for v in [r["id"], r["execution"], json.dumps(r["definition"], ensure_ascii=False)]
        )
        + " |"
        for r in checks
    ]
    for mode in ("enforcement", "monitoring", "all"):
        overview = heading + [line for line, rule in zip(lines, checks) if mode == "all" or rule["execution"] == mode]
        spec["overview" if mode == "all" else "overview_" + mode] = "\n".join("# MAGIC " + line for line in overview)
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
        f"{quoted(table + '_quarantine')} (\n  " + ",\n  ".join(fields) + "\n) USING DELTA;",
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
