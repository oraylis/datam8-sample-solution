"""Acceptance-only inspection and negative copies of generated notebooks.

No rule files are loaded by the runtime. These test helpers inspect literal
notebook configuration and create disposable negative-test notebook copies.
"""

import ast
import base64
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat, ImportFormat, Language


def notebook_source(path):
    return base64.b64decode(WorkspaceClient().workspace.export(str(path), format=ExportFormat.SOURCE).content).decode()


def notebook_configuration(path):
    for node in ast.walk(ast.parse(notebook_source(path))):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "quality_rules" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Generated notebook has no inline quality configuration")


def expect_expression_failure(dbutils, path, expression, params, *, assignment="enforcement_checks"):
    """Run actual notebook code with an invalid native expression, then delete the copy."""
    import uuid

    source = notebook_source(path)
    node = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == assignment for t in n.targets)
    )
    checks = ast.literal_eval(node.value)
    checks[0]["check"]["arguments"]["expression"] = expression
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [assignment + " = " + repr(checks) + "\n"]
    copy = str(path) + "__invalid_" + uuid.uuid4().hex
    client = WorkspaceClient()
    client.workspace.import_(
        copy,
        content=base64.b64encode("".join(lines).encode()).decode(),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )
    try:
        try:
            dbutils.notebook.run(copy, 180, params)
        except Exception:
            return
        raise AssertionError("Invalid SQL was neither failed nor reported as a DQX skip")
    finally:
        client.workspace.delete(copy)
