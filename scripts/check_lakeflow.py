"""Generate disposable solutions and verify Lakeflow contracts and existing-target parity.

Run with a pinned DataM8 runtime; see the Lakeflow architecture document. No source
connections or Databricks APIs are used. Each target runs in a fresh process so
payload registries and imported target modules cannot leak between test runs.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import yaml


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def file_map(root: Path, *, docs: bool = False) -> dict[str, str]:
    files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8").rstrip()
        for path in root.rglob("*")
        if path.is_file()
    }
    if docs:
        for name, content in files.items():
            content = re.sub(
                r"(?m)^(Generated at \*\*)[^*]+(\*\*)", r"\1<generation-time>\2", content
            )
            content = re.sub(
                r"(?m)^Generated \S+ from schema",
                "Generated <generation-time> from schema",
                content,
            )
            files[name] = re.sub(
                r'(<mxfile [^>]*modified=")[^"]+(\")', r"\1<generation-time>\2", content
            )
    return files


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


def check_lakeflow(model, output: Path) -> None:
    import jinja2
    from datam8.utils.cache import Cache
    from datam8_model.attribute import HistoryType
    from datam8_model.property import PropertyReference
    from ddl_payloads import DdlColumn
    from dml_payloads import DmlPayload
    from lakeflow_payloads import (
        LakeflowExternalNotebookPayload,
        LakeflowExternalPipelinePayload,
        cursor_column,
        uses_entity_pipeline,
    )
    from payload import dml_function_scripts
    from payload_common import collect_transformations, get_model_entity_wrappers, get_one

    resources: dict[str, dict] = {}
    for path in output.rglob("*.yml"):
        for kind, items in (yaml.safe_load(path.read_text()) or {}).get("resources", {}).items():
            existing = resources.setdefault(kind, {})
            require(not existing.keys() & items.keys(), f"Duplicate resource in {path}")
            existing.update(items)
    require(resources.get("pipelines"), "No Lakeflow pipelines generated")
    require(len(resources.get("schemas", {})) == 4, "Main Databricks zones were not preserved")
    jobs = resources["jobs"]
    for job in jobs.values():
        check_graph(job["tasks"])
        for task in job["tasks"]:
            if "pipeline_task" in task:
                key = task["pipeline_task"]["pipeline_id"].split(".")[2]
                require(key in resources["pipelines"], f"Missing pipeline {key}")
            if "run_job_task" in task:
                key = task["run_job_task"]["job_id"].split(".")[2]
                require(key in jobs, f"Missing child job {key}")
            if "notebook_task" in task:
                name = task["notebook_task"]["notebook_path"].split("${var.lakeflow_output_path}/")[
                    1
                ]
                require((output / f"{name}.py").is_file(), f"Missing job notebook {name}")

    for path in output.rglob("*.py"):
        content = path.read_text()
        ast.parse(content, filename=str(path))
        for name in re.findall(r"^# MAGIC %run (.+)$", content, re.MULTILINE):
            require(
                (path.parent / f"{name}.py").resolve().is_file(), f"Missing %run {name} in {path}"
            )

    wrappers = get_model_entity_wrappers(model)
    customer = next(
        w for w in wrappers if w.entity.name == "Customer" and w.locator.folders[0] == "010-Stage"
    )
    require(not uses_entity_pipeline(customer, model), "SCD2 customer must retain notebook history")
    customer_dml = (output / "notebooks/010-Stage/dml/Sales/Customer/Customer.py").read_text()
    require("tgt.__IsCurrent = true" in customer_dml, "SCD2 merge must target current records")
    require(
        "__IsCurrent"
        in (output / "notebooks/010-Stage/ddl/Sales/Customer/Customer.py").read_text(),
        "Missing history schema",
    )
    require(
        "`CustomerID` as int" in customer_dml, "Native ingestion column names were remapped twice"
    )
    require(
        'F.col("__InsertTimestampUTC") >' not in customer_dml,
        "Managed ingestion has no synthetic snapshot cursor",
    )

    core_customer = next(w for w in wrappers if w.entity.id == 2000)
    scripts = [
        p for p in dml_function_scripts(model, Cache()) if "CustomerNew" in str(p.get_output_path())
    ]
    require(len(scripts) == 1, "Missing customer function")
    require(
        scripts[0].get_output_path().name == "CustomerNew.py",
        "Function source path leaked into output path",
    )
    content = scripts[0].get_data().content
    require("datam8_campus_dev_fka" not in content, "Hard-coded catalog in Lakeflow function")
    require(".stage.Sales_Customer_Customer" in content, "Function must honor zone targetName")
    require("bronze" not in content, "Function must not use the bronze layer name")
    require("c.__IsCurrent = True" in content, "Existing customer filter was removed")
    require(
        collect_transformations(core_customer, model)[0]["script_name"] == "CustomerNew.py",
        "Nested function path is not normalized",
    )

    dimensions = next(w for w in wrappers if w.entity.id == 3000)
    keys = [
        DdlColumn(a, model)
        for a in dimensions.entity.attributes
        if any(p.value.lower() == "sk" for p in a.properties or [])
    ]
    require(
        keys and all("GENERATED ALWAYS AS IDENTITY" in c.sql_definition for c in keys),
        "Missing identity DDL",
    )
    require(
        all("surrogate_key" in c.metadata_repr for c in keys), "Missing identity schema metadata"
    )
    fact = next(w for w in wrappers if w.entity.id == 3001)
    require(
        DmlPayload(fact, model, collect_transformations(fact, model)).has_lookup_dimensions,
        "Missing fact-to-dimension lookup",
    )
    fact_task = next(
        task
        for job in jobs.values()
        for task in job["tasks"]
        if task["task_key"].startswith("lakeflow_delta_")
        and task["task_key"].endswith("factsalesorder")
    )
    require(
        any(d["task_key"].endswith("dimcustomer") for d in fact_task["depends_on"]),
        "Fact load can race its dimension lookup",
    )
    require(
        "DataType.fromDDL"
        not in (output / "notebooks/030-Curated/ddl/Sales/Customer/DimCustomer.py").read_text(),
        "DDL depends on a Spark 4 API although the sample can select an older runtime",
    )
    overwrite = (output / "notebooks/020-Core/dml/Sales/Customer/CustomerAddress.py").read_text()
    require(
        "whenNotMatchedBySourceDelete()" in overwrite,
        "Keyed overwrite must remove absent rows without recreating identities",
    )

    source = next(s for s in customer.entity.sources if s.sourceAlias == "Customer_EN")
    require(
        cursor_column(source) == "ModifiedDate", "Legacy extract_column marker is not supported"
    )
    source = source.model_copy(deep=True)
    for mapping in source.mapping:
        for prop in mapping.properties or []:
            if prop.property == "extract_column":
                prop.property = "extract_mode"
    require(cursor_column(source) == "ModifiedDate", "New cursor marker is not supported")
    source.mapping[0].properties = [PropertyReference(property="extract_mode", value="delta")]
    try:
        cursor_column(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Multiple delta cursors did not fail")
    for mapping in source.mapping:
        mapping.properties = []
    try:
        LakeflowExternalPipelinePayload(customer, model, source).cursor_column
    except ValueError:
        pass
    else:
        raise AssertionError("Missing delta cursor did not fail")

    oracle = next(w for w in wrappers if w.entity.name == "DIMTIME")
    pipeline = LakeflowExternalPipelinePayload(oracle, model, oracle.entity.sources[0])
    sql = LakeflowExternalNotebookPayload(pipeline).remote_query_sql
    require(
        "service_name => 'ORCLPDB1'" in sql and "database =>" not in sql,
        "Oracle remote_query options are wrong",
    )

    # Exercise the snapshot-only entity pipeline without changing persisted metadata.
    snapshot = SimpleNamespace(
        entity=customer.entity.model_copy(deep=True), locator=customer.locator
    )
    for attr in snapshot.entity.attributes:
        attr.history = HistoryType.SCD1
    snapshot.entity.properties = [PropertyReference(property="write_mode", value="overwrite")]
    require(
        uses_entity_pipeline(snapshot, model), "Simple overwrite should support an entity pipeline"
    )
    snapshot.entity.properties = [PropertyReference(property="write_mode", value="append")]
    require(
        not uses_entity_pipeline(snapshot, model), "Append must not become a materialized overwrite"
    )
    try:
        DmlPayload(snapshot, model, [])
    except ValueError:
        pass
    else:
        raise AssertionError("Append would replay the entire external snapshot")
    snapshot.entity.properties = [PropertyReference(property="write_mode", value="merge")]
    snapshot.entity.attributes[1].history = HistoryType.SCD0
    snapshot.entity.attributes[2].history = HistoryType.SCD2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(output.parents[2] / "Generate/databricks-lakeflow"),
        undefined=jinja2.StrictUndefined,
    )
    history_notebook = env.get_template("notebooks/dml_notebook.jinja2").render(
        data=DmlPayload(snapshot, model, [])
    )
    ast.parse(history_notebook)
    require(
        "F.when(" in history_notebook and ".otherwise(F.col(" in history_notebook,
        "SCD0 values, including null, must survive a new history version",
    )

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(output.parents[2] / "Generate/databricks-lakeflow"),
        undefined=jinja2.StrictUndefined,
    )
    pipeline = LakeflowExternalPipelinePayload(customer, model, customer.entity.sources[1])
    spec = yaml.safe_load(
        env.get_template("pipelines/external_pipeline.yml.jinja2").render(data=pipeline)
    )
    managed = next(iter(spec["resources"]["pipelines"].values()))
    require(
        "ingestion_definition" in managed
        and managed.get("serverless") is True
        and "libraries" not in managed,
        "Managed ingestion mixes incompatible pipeline settings",
    )
    table = managed["ingestion_definition"]["objects"][0]["table"]
    require(
        table["table_configuration"]["primary_keys"] == ["CustomerID"],
        "Managed ingestion key must use the physical source name",
    )
    require(
        get_one(model.folders, "010-Stage/Sales").entity.name == "Sales",
        "Existing folder lookup failed",
    )
    print(
        "PASS: Lakeflow paths, job graphs, history, identity, lookups, source mappings and connectors"
    )


def worker(root: Path, target: str) -> None:
    from datam8 import config, generate, parser

    config.set_solution(root.resolve() / "ORAYLISDatabricksSample.dm8s")
    config.mode = config.RunMode.TEST
    model = asyncio.run(parser.parse_full_solution_async(config.solution_path))
    model.resolve()
    output = generate.generate_output(model, target, [], generate_all=True, clean_output=False)
    check_notebook_markdown_cells(output)
    if target == "databricks-lakeflow":
        check_lakeflow(model, output)
    print(f"PASS: generated {target}: {len(file_map(output))} artifacts")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline-ref", default="main")
    cli.add_argument(
        "--worker", nargs=2, metavar=("SOLUTION_ROOT", "TARGET"), help=argparse.SUPPRESS
    )
    args = cli.parse_args()
    if args.worker:
        worker(Path(args.worker[0]), args.worker[1])
        return
    repo = Path(__file__).resolve().parent.parent
    runtime = metadata.distribution("datam8")
    provenance = json.loads(runtime.read_text("direct_url.json") or "{}")
    print(
        f"DataM8 {runtime.version}: {provenance.get('vcs_info', {}).get('commit_id', 'installed release')}",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="datam8-lakeflow-check-") as temporary:
        root = Path(temporary).resolve()
        baseline, candidate = root / "baseline", root / "candidate"
        baseline.mkdir()
        archive = subprocess.check_output(["git", "archive", args.baseline_ref], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(baseline, filter="data")
        shutil.copytree(
            repo,
            candidate,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "__pycache__", ".ruff_cache", ".databricks", "generated"
            ),
        )
        for target in ["databricks", "powerbi", "docs"]:
            results = []
            for solution in [baseline, candidate]:
                results.append(
                    subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--worker",
                            str(solution),
                            target,
                        ],
                        capture_output=True,
                        encoding="utf-8",
                        env={**os.environ, "PYTHONUTF8": "1"},
                    )
                )
            before, after = results
            if before.returncode:
                require(
                    target == "powerbi"
                    and "'Model' object has no attribute 'get_model_entity_by_id'" in before.stderr,
                    before.stderr,
                )
                require(
                    after.returncode == before.returncode, f"Baseline failure changed for {target}"
                )
                errors_before = [
                    line.replace(str(baseline), "<solution>")
                    for line in before.stderr.splitlines()
                    if line.startswith("payload ")
                ]
                errors_after = [
                    line.replace(str(candidate), "<solution>")
                    for line in after.stderr.splitlines()
                    if line.startswith("payload ")
                ]
                require(
                    errors_before and errors_before == errors_after,
                    f"Different failure for {target}: {after.stderr}",
                )
                print(f"BASELINE LIMITATION ({target}): {errors_before[0]}", flush=True)
            else:
                require(after.returncode == 0, after.stderr)
            descriptor = json.loads((baseline / "ORAYLISDatabricksSample.dm8s").read_text())
            relative = next(
                t["outputPath"] for t in descriptor["generatorTargets"] if t["name"] == target
            )
            require(
                file_map(baseline / relative, docs=target == "docs")
                == file_map(candidate / relative, docs=target == "docs"),
                f"Output changed for existing target {target}",
            )
            qualifier = "partial output after baseline failure" if before.returncode else "output"
            print(f"PASS: unchanged {qualifier} for {target}", flush=True)
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(candidate),
                "databricks-lakeflow",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
