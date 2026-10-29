"""Reusable structural checks for generated artifacts."""
from pathlib import Path
import re


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_graph(tasks: list[dict]) -> None:
    graph = {
        task["task_key"]: [d["task_key"] for d in task.get("depends_on", [])] for task in tasks
    }
    require(len(graph) == len(tasks), "Duplicate task key")
    visited, active = set(), set()

    def visit(key: str) -> None:
        require(key in graph, f"Missing dependency {key}")
        require(key not in active, f"Cyclic dependency {key}")
        if key in visited:
            return
        active.add(key)
        for dependency in graph[key]:
            visit(dependency)
        active.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def check_notebook_markdown_cells(output: Path) -> None:
    """Ensure executable Python never shares a source cell with a Markdown magic."""
    for path in output.rglob("*.py"):
        if "notebooks" not in path.parts:
            continue
        cells: list[list[str]] = []
        current: list[str] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if re.fullmatch(r"# COMMAND ----------(?:# COMMAND ----------)*", line.strip()):
                cells.append(current)
                current = []
            else:
                current.append(line)
        cells.append(current)

        for index, cell in enumerate(cells, start=1):
            if not any(line.strip() == "# MAGIC %md" for line in cell):
                continue
            executable_lines = [
                line
                for line in cell
                if line.strip()
                and not line.strip().startswith("# MAGIC")
                and line.strip() != "# Databricks notebook source"
            ]
            require(
                not executable_lines,
                f"{path}: Markdown cell {index} contains non-Markdown lines: {executable_lines[:3]}",
            )
