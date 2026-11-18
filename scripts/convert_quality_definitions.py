"""Explicit one-time conversion of legacy DataM8 quality metadata to the DQX target dialect.

Preview by default; --write updates only explicitly selected entity JSON files.
This utility is not called by generation or runtime execution.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path


def quoted(name):
    return "`" + name.replace("`", "``") + "`"


def convert_quality(value):
    result = copy.deepcopy(value)
    checks = result.get("checks", [])
    aggregates = [c for c in checks if c.get("type") in ("completeness", "freshness", "row_count")]
    alias = "summary"
    existing_inputs = result.get("settings", {}).get("inputs", {})
    while alias in existing_inputs:
        alias += "_legacy"
    expressions = ["COUNT(*) AS `__dm8_total`"]
    converted = []
    for check in checks:
        if "type" not in check:
            converted.append(check)
            continue
        kind = check["type"]
        if kind == "dqx":
            check.pop("type")
            converted.append(check)
            continue
        params = check.get("parameters", {})
        if any(isinstance(v, (int, float)) and not math.isfinite(v) for v in params.values()):
            raise ValueError("Legacy parameters must be finite")
        native = {"criticality": "warn" if check["severity"] == "warning" else "error"}
        attr = quoted(check.get("attribute", ""))
        if kind == "not_null":
            function, arguments = "is_not_null", {"column": attr}
        elif kind == "range":
            if "min" in params and "max" in params:
                function, arguments = (
                    "is_in_range",
                    {"column": attr, "min_limit": params["min"], "max_limit": params["max"]},
                )
            else:
                low = "min" in params
                function = "is_not_less_than" if low else "is_not_greater_than"
                arguments = {"column": attr, "limit": params["min" if low else "max"]}
        elif kind in ("sql_expression", "completeness", "freshness", "row_count"):
            expression = params.get("expression")
            if kind != "sql_expression":
                if check["execution"] != "monitoring":
                    raise ValueError("Legacy aggregate checks must use monitoring")
                column = quoted("__dm8_q_" + check["id"])
                calculation = "COUNT(*)"
                if kind == "completeness":
                    calculation = f"COUNT({attr}) / NULLIF(COUNT(*), 0)"
                    expression = f"{column} >= {params['minCompleteness']}"
                elif kind == "freshness":
                    calculation = f"CAST(:evaluated_at AS DOUBLE) - CAST(MAX({attr}) AS DOUBLE)"
                    expression = f"{column} BETWEEN 0 AND {params['maxAgeSeconds']}"
                else:
                    expression = " AND ".join(
                        f"{column} {op} {params[key]}"
                        for key, op in (("minCount", ">="), ("maxCount", "<="))
                        if key in params
                    )
                expressions.append(calculation + " AS " + column)
                metrics = {"checked_rows": "`__dm8_total`", "measured_value": column}
                if kind == "completeness":
                    metrics["no_data_when"] = "`__dm8_total` = 0"
                native["datam8"] = {"input": alias, "metrics": metrics}
            function = "sql_expression"
            arguments = {
                "expression": f"COALESCE(({expression}), FALSE)",
                "msg": check.get("description") or check["id"],
            }
        else:
            raise ValueError(f"No legacy conversion for {kind}")
        native["check"] = {"function": function, "arguments": arguments}
        converted.append(
            {**{k: check[k] for k in ("id", "execution", "description") if k in check}, "definition": native}
        )
    result["checks"] = converted
    if aggregates:
        result.setdefault("settings", {}).setdefault("inputs", {})[alias] = {
            "sql": "SELECT\n  " + ",\n  ".join(expressions) + "\nFROM {target_table}"
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    pending = []
    for path in args.files:
        entity = json.loads(path.read_text())
        if "quality" not in entity:
            continue
        updated = convert_quality(entity["quality"])
        if updated != entity["quality"]:
            entity["quality"] = updated
            pending.append((path, entity))
    for path, entity in pending:
        if args.write:
            path.write_text(json.dumps(entity, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"written": args.write, "changed": [str(path) for path, _ in pending]}))


if __name__ == "__main__":
    main()
