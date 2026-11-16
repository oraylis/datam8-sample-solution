"""Native DQX artifacts derived directly from DataM8 quality requirements."""

from __future__ import annotations

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
