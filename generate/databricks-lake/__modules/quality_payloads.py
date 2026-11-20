"""Solution-owned SQL validation, Databricks translation and native DQX payloads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.tokens import TokenType, Tokenizer
import yaml
from datam8.errors import Datam8ValidationError
from datam8.quality import validate_quality_value

CLOCK_COLUMN = "__dm8_dq_evaluated_at"
_ALLOWED_NODES = frozenset(
    """
Alias Identifier Column Literal Null Boolean Star Paren And Or Not EQ NEQ LT LTE GT GTE
NullSafeEQ NullSafeNEQ Add Sub Mul Div Mod Neg Is In Between Like Escape Case If Cast
DataType DataTypeParam Coalesce Nullif Trim Length RegexpLike Count Sum Min Max Window
Select From Join Where Group Having Subquery With CTE Table TableAlias Distinct
CurrentTimestamp TimestampDiff Var
""".split()
)
_ALLOWED_TYPES = frozenset(
    "BOOLEAN TINYINT SMALLINT INT BIGINT FLOAT DOUBLE DECIMAL CHAR VARCHAR TEXT DATE TIMESTAMP TIMESTAMPTZ".split()
)


def quoted(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _placeholders(text: str, references: dict, query: bool) -> tuple[str, dict[str, str]]:
    """Recognize relation placeholders only outside literals and comments."""
    tokens = Tokenizer().tokenize(text)
    replacements = []
    bindings = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.token_type == TokenType.L_BRACE:
            end = index + 1
            while end < len(tokens) and tokens[end].token_type != TokenType.R_BRACE:
                end += 1
            if end == len(tokens):
                raise ValueError("Unclosed relation placeholder")
            key = text[token.start + 1 : tokens[end].end]
            if not query:
                raise ValueError("Relation placeholders are only allowed in monitoring sql")
            if key == "target":
                parameter = "dm8_target"
            elif key.startswith("references.") and key[11:] in references:
                parameter = "dm8_ref_" + key[11:]
            else:
                raise ValueError("Unknown relation placeholder {" + key + "}")
            sentinel = "__dm8_sql_source_" + str(len(bindings))
            bindings[sentinel] = parameter
            replacements.append((token.start, tokens[end].end + 1, sentinel))
            index = end
        elif token.token_type == TokenType.R_BRACE:
            raise ValueError("Unexpected closing relation placeholder")
        elif token.text.startswith("__dm8_sql_source_") and token.token_type != TokenType.STRING:
            raise ValueError("Reserved SQL identifier")
        index += 1
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text, bindings


def compile_sql(text: str, *, query: bool = False, references: dict | None = None) -> dict[str, Any]:
    """Compile the bounded public SQL profile; never execute SQL during generation."""
    prepared, bindings = _placeholders(text, references or {}, query)
    trees = sqlglot.parse(prepared)
    if len(trees) != 1 or trees[0] is None:
        raise ValueError("Exactly one SQL expression or query is required")
    tree = trees[0]
    if query != isinstance(tree, exp.Select):
        raise ValueError("Expected a SELECT query" if query else "Expected a Boolean expression, not a query")

    def normalize_time(node):
        if isinstance(node, exp.TimestampDiff):
            # The public syntax is TIMESTAMPDIFF(unit, start, end); the generic
            # SQLGlot parser's field order differs. Normalize explicitly.
            unit = node.this
            if not isinstance(unit, (exp.Column, exp.Var)) or unit.name.upper() not in ("SECOND", "MICROSECOND"):
                raise ValueError("TIMESTAMPDIFF supports SECOND and MICROSECOND")
            return exp.TimestampDiff(
                this=node.args["unit"].copy(),
                expression=node.expression.copy(),
                unit=exp.Var(this=unit.name.upper()),
            )
        return node

    tree = tree.transform(normalize_time)
    for node in tree.walk():
        name = type(node).__name__
        if name not in _ALLOWED_NODES:
            raise ValueError(f"Unsupported SQL construct: {name}")
        node.comments = []
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise ValueError("Recursive CTEs are not supported")
        if isinstance(node, exp.Join) and (node.side not in ("", "LEFT") or node.kind not in ("", "INNER")):
            raise ValueError("Only INNER and LEFT JOIN are supported")
        if isinstance(node, exp.Window):
            if (
                not isinstance(node.this, (exp.Count, exp.Sum))
                or not node.args.get("partition_by")
                or node.args.get("order")
                or node.args.get("spec")
            ):
                raise ValueError("Windows require COUNT/SUM and PARTITION BY without ORDER BY or a frame")
        if isinstance(node, exp.DataType) and node.this.name not in _ALLOWED_TYPES:
            raise ValueError("Unsupported SQL cast type: " + node.this.name)
        if isinstance(node, exp.Column) and node.name.startswith("__dm8_dq_"):
            raise ValueError("Expressions must not reference reserved quality columns")
        if not query:
            if isinstance(node, (exp.Select, exp.Table, exp.Subquery)):
                raise ValueError("Expression subqueries are not supported; use monitoring sql")
            if isinstance(node, exp.AggFunc) and node.find_ancestor(exp.Window) is None:
                raise ValueError("Row expressions require aggregate functions inside a supported window")
    used_bindings = {}
    used_references = set()
    if query:
        if len(tree.expressions) != 2 or {x.alias_or_name for x in tree.expressions} != {
            "checked_rows",
            "measured_value",
        }:
            raise ValueError("Monitoring sql must select exactly checked_rows and measured_value")
        for scope in traverse_scope(tree):
            ctes = {name.casefold() for name in scope.cte_sources}
            for table in scope.tables:
                if table.name in bindings and not table.db and not table.catalog:
                    used_bindings[id(table)] = bindings[table.name]
                elif table.db or table.catalog or table.name.casefold() not in ctes:
                    raise ValueError("Table access requires {target} or a declared {references.alias}")
        if len(used_bindings) != len(bindings):
            raise ValueError("Relation placeholders must occur as table references")
        for parameter in used_bindings.values():
            if parameter.startswith("dm8_ref_"):
                used_references.add(parameter[8:])

        def bind_table(node):
            parameter = used_bindings.get(id(node))
            if parameter:
                alias = node.args.get("alias")
                return exp.Table(
                    this=exp.Anonymous(this="IDENTIFIER", expressions=[exp.Placeholder(this=parameter)]),
                    alias=alias.copy() if alias is not None else None,
                )
            return node

        tree = tree.transform(bind_table, copy=False)
    uses_clock = any(isinstance(n, exp.CurrentTimestamp) for n in tree.walk())
    tree = tree.transform(
        lambda n: (
            (exp.Placeholder(this="evaluated_at") if query else exp.column(CLOCK_COLUMN))
            if isinstance(n, exp.CurrentTimestamp)
            else n
        )
    )
    return {
        "text": tree.sql(dialect="databricks", unsupported_level=sqlglot.ErrorLevel.RAISE),
        "uses_clock": uses_clock,
        "references": sorted(used_references),
    }


def validate_target_quality(value: dict[str, Any]) -> dict[str, dict]:
    validate_quality_value(value)
    compiled = {}
    for rule in value["checks"]:
        field = "expression"
        try:
            expression = compile_sql(rule["expression"])
            result = {
                "id": rule["id"],
                "expression": expression["text"],
                "uses_clock": expression["uses_clock"],
                "references": [],
            }
            if "sql" in rule:
                field = "sql"
                query = compile_sql(rule["sql"], query=True, references=value.get("references", {}))
                result.update(sql=query["text"], references=query["references"])
            compiled[rule["id"]] = result
        except (ValueError, sqlglot.errors.SqlglotError) as error:
            raise Datam8ValidationError(
                message=f"Quality check {rule['id']} {field}: {error}",
                details={"checkId": rule["id"], "field": f"quality.checks.{rule['id']}.{field}"},
            ) from error
    return compiled


def quality_spec(entity: Any) -> dict[str, Any] | None:
    quality = getattr(entity, "quality", None)
    if quality is None or not quality.checks:
        return None
    value = quality.model_dump(mode="json", exclude_none=True)
    try:
        compiled = validate_target_quality(value)
    except Datam8ValidationError as error:
        raise Datam8ValidationError(
            message=f"Entity {entity.id}: {error}",
            details={**(error.details or {}), "entityId": entity.id},
        ) from error
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"entityId": entity.id, "ruleSetHash": digest, "quality": value, "compiled": compiled}


def native_check(rule: dict[str, Any], expression: str | None = None) -> dict[str, Any]:
    expression = expression if expression is not None else compile_sql(rule["expression"])["text"]
    return {
        "name": rule["id"],
        "criticality": "warn" if rule.get("severity", "error") == "warning" else "error",
        "check": {
            "function": "sql_expression",
            "arguments": {
                "expression": f"COALESCE(({expression}), FALSE)",
                "msg": rule.get("description") or rule["id"],
            },
        },
        "user_metadata": {"datam8_check_id": rule["id"]},
    }


def monitoring_groups(spec: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    rows = [r for r in spec["quality"]["checks"] if r["execution"] == "monitoring" and "sql" not in r]
    if rows:
        groups.append({"key": "monitoring_rows", "rules": rows, "ids": [r["id"] for r in rows], "aggregate": False})
    for rule in spec["quality"]["checks"]:
        if "sql" in rule:
            compiled = spec["compiled"][rule["id"]]
            groups.append(
                {
                    "key": "monitoring_aggregate_" + rule["id"],
                    "rules": [rule],
                    "ids": [rule["id"]],
                    "aggregate": True,
                    "sql_literal": sql_python_literal(compiled["sql"]),
                    "references": compiled["references"],
                    "on_empty": rule.get("onEmpty", "evaluate"),
                }
            )
    return groups


def quality_files(entity: Any) -> dict[Path, str]:
    spec = quality_spec(entity)
    if spec is None:
        return {}
    groups = {"enforcement": [r for r in spec["quality"]["checks"] if r["execution"] == "enforcement"]}
    groups.update({g["key"]: g["rules"] for g in monitoring_groups(spec)})
    root = Path("quality", str(entity.id))
    files = {
        root / f"{key}.yaml": yaml.safe_dump(
            [native_check(rule, spec["compiled"][rule["id"]]["expression"]) for rule in rules],
            sort_keys=False,
            allow_unicode=True,
        )
        for key, rules in groups.items()
    }
    spec["files"] = {key: f"{key}.yaml" for key in groups}
    spec["expression_groups"] = {key: [rule["id"] for rule in rules] for key, rules in groups.items()}
    files[root / "manifest.json"] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    return files


def notebook_quality(entity: Any) -> dict[str, Any] | None:
    spec = quality_spec(entity)
    if spec is None:
        return None
    checks = spec["quality"]["checks"]
    spec["enforcement"] = [r for r in checks if r["execution"] == "enforcement"]
    spec["monitoring_groups"] = monitoring_groups(spec)
    heading = ["| ID | Execution | Severity | Expression | On empty |", "| --- | --- | --- | --- | --- |"]
    lines = [
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
