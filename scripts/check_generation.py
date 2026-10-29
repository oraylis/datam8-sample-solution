"""Validate and generate selected sample targets in the local sample solution."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from generation_checks import check_notebook_markdown_cells, check_graph
from check_public_sources import check_public_sources
from databricks_jobs import execution_plan, generated_resources

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "ORAYLISDatabricksSample.dm8s"


def run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env={**os.environ, "PYTHONUTF8": "1"})


def check_generated_python(output: Path) -> int:
    python_files = list(output.rglob("*.py"))
    failures = []
    for path in python_files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as error:
            failures.append(f"{path.relative_to(output)}:{error.lineno}: {error.msg}")
    if failures:
        raise RuntimeError("Generated Python syntax errors:\n" + "\n".join(failures))
    return len(python_files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="all")
    args = parser.parse_args()
    targets = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))["generatorTargets"]
    names = [item["name"] for item in targets]
    selected = names if args.target == "all" else [args.target]
    unknown = sorted(set(selected) - set(names))
    if unknown:
        parser.error(f"Unknown target(s): {', '.join(unknown)}. Available: {', '.join(names)}")
    check_public_sources()

    report_directory = ROOT / "Output/e2e-test-reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    failures = []
    results = []
    run([sys.executable, "-m", "datam8", "validate", "--solution", str(DESCRIPTOR)], cwd=ROOT)
    for name in selected:
        try:
            run([sys.executable, "-m", "datam8", "generate", name, "--solution", str(DESCRIPTOR), "--clean-output"], cwd=ROOT)
            output_path = next(item["outputPath"] for item in targets if item["name"] == name)
            output = ROOT / output_path
            files = [path for path in output.rglob("*") if path.is_file()]
            if not files:
                raise RuntimeError(f"Target {name} generated no files at {output_path}")
            python_count = check_generated_python(output)
            check_notebook_markdown_cells(output)
            if name in {"databricks", "databricks-lakeflow"}:
                manifest = json.loads((output / "manifest.json").read_text())
                resources = generated_resources(output.parent)
                roots = execution_plan(resources, manifest, required_phases=manifest["lifecycle"])
                platform = {"databricks": "databricks-lake", "databricks-lakeflow": "databricks-lakeflow"}[name]
                if name == "databricks":
                    ddl_notebooks = [
                        path for path in (output / "notebooks").rglob("*.py")
                        if "/ddl/" in path.as_posix()
                    ]
                    if not ddl_notebooks:
                        raise RuntimeError("Classic Databricks generation must emit DDL notebooks")
                    for path in ddl_notebooks:
                        notebook = path.read_text(encoding="utf-8")
                        if (
                            "# DBTITLE 1,Generated CREATE TABLE statement" not in notebook
                            or 'create_sql = """CREATE TABLE IF NOT EXISTS' not in notebook
                            or "print(create_sql)" not in notebook
                            or "spark.sql(create_sql)" not in notebook
                            or "col_lines" in notebook
                        ):
                            raise RuntimeError(
                                f"DDL notebook must show the fully generated CREATE TABLE statement before execution: {path.relative_to(output)}"
                            )
                for job_key, job in resources["jobs"].items():
                    if job.get("tags", {}) != {"platform": platform}:
                        raise RuntimeError(f"Job {job_key} must have only platform={platform}; phase tags are not allowed")
                    if not job.get("name", "").startswith("[${var.environment}] ") or platform in job["name"]:
                        raise RuntimeError(f"Job {job_key} violates the environment-first display-name convention")
                if name == "databricks":
                    cluster_file = output / "clusters/clusters.yml"
                    if cluster_file.exists() and "autotermination_minutes" in cluster_file.read_text(encoding="utf-8"):
                        raise RuntimeError("Job cluster configuration must not set interactive-cluster autotermination")
                    cluster_variables = yaml.safe_load(cluster_file.read_text(encoding="utf-8")).get("variables", {})
                    extra_small = cluster_variables.get("cluster_extra_small", {}).get("default", {})
                    if extra_small.get("driver_node_type_id") != "Standard_D8ds_v5":
                        raise RuntimeError("The extra-small job cluster must use the model-configured D8 driver")
                    load_jobs = {
                        key: job for key, job in resources["jobs"].items()
                        if key.startswith("Load_")
                    }
                    if set(load_jobs) != {"Load_sales_daily", "Load_sales_weekly"}:
                        raise RuntimeError(
                            "Classic target must generate exactly one load job per modeled jobs value"
                        )
                    expected_load_names = {
                        "Load_sales_daily": "[${var.environment}] Sales (Daily)",
                        "Load_sales_weekly": "[${var.environment}] Sales (Weekly)",
                    }
                    for job_key, expected_name in expected_load_names.items():
                        if load_jobs[job_key].get("name") != expected_name:
                            raise RuntimeError(f"{job_key} must use its model job display name")
                    daily_zones = {
                        "stage" if "/010-Stage/" in task.get("notebook_task", {}).get("notebook_path", "")
                        else "core" if "/020-Core/" in task.get("notebook_task", {}).get("notebook_path", "")
                        else "curated" if "/030-Curated/" in task.get("notebook_task", {}).get("notebook_path", "")
                        else "raw" if "/raw/" in task.get("notebook_task", {}).get("notebook_path", "")
                        else None
                        for task in load_jobs["Load_sales_daily"].get("tasks", [])
                    }
                    if not {"raw", "stage", "core", "curated"} <= daily_zones:
                        raise RuntimeError("Sales (Daily) must contain tasks across all modeled layers")
                    if any(task.get("run_job_task") for job in load_jobs.values() for task in job.get("tasks", [])):
                        raise RuntimeError("A classic load job must not invoke another model load job")
                    load_plan = {item["model_job"]: item for item in manifest["execution_plan"]["load"]}
                    if set(load_plan) != {"sales_daily", "sales_weekly"}:
                        raise RuntimeError("Manifest must retain one entry per modeled load job")
                    if load_plan["sales_daily"]["depends_on"] or load_plan["sales_weekly"]["depends_on"] != ["Load_sales_daily"]:
                        raise RuntimeError("Manifest must preserve the modeled Daily → Weekly dependency")
                    expected_stage_casts = {
                        "notebooks/010-Stage/dml/ShippingAPI/tracking_events/TrackingEvent.py": [
                            "TRY_CAST(`EventAt` AS TIMESTAMP) AS `EventAt`",
                            "TRY_CAST(`SalesOrderID` AS BIGINT) AS `SalesOrderID`",
                        ],
                        "notebooks/010-Stage/dml/OracleProcurement/AW_PROCUREMENT/PurchaseOrder.py": [
                            "TRY_CAST(`PurchaseOrderID` AS DECIMAL(19,0)) AS `PurchaseOrderID`",
                        ],
                        "notebooks/010-Stage/dml/MySQLWebshop/aw_webshop/CartItem.py": [
                            "TRY_CAST(`Purchased` AS BOOLEAN) AS `Purchased`",
                        ],
                    }
                    for relative_path, expressions in expected_stage_casts.items():
                        rendered = (output / relative_path).read_text(encoding="utf-8")
                        if any(expression not in rendered for expression in expressions):
                            raise RuntimeError(
                                f"External-source Stage notebook {relative_path} must try_cast to its modeled Databricks types"
                            )
                    source_projection_paths = [
                        "notebooks/020-Core/dml/Procurement/Orders/PurchaseOrder.py",
                        "notebooks/020-Core/dml/Shipping/Shipment/Shipment.py",
                        "notebooks/030-Curated/dml/Procurement/Supplier/DimSupplier.py",
                    ]
                    for relative_path in source_projection_paths:
                        rendered = (output / relative_path).read_text(encoding="utf-8")
                        if "spark.table(f\"{catalog.name}." not in rendered or "TRY_CAST(" not in rendered:
                            raise RuntimeError(
                                f"Modeled-source notebook {relative_path} must read its upstream table and cast to target types"
                            )
                    for path in (output / "notebooks").rglob("dml/*.py"):
                        if "This entity does not have configured DML logic" in path.read_text(encoding="utf-8"):
                            raise RuntimeError(
                                f"Generated DML notebook has no processing logic: {path.relative_to(output)}"
                            )
                    create_key = manifest["execution_plan"]["create"]["job"]
                    create_jobs = resources["jobs"]
                    root_tasks = create_jobs[create_key].get("tasks", [])
                    zone_keys = set()
                    expected_zone_order = ["Create_raw_tables", "Create_stage_tables", "Create_core_tables", "Create_curated_tables"]
                    if [task["task_key"] for task in root_tasks] != expected_zone_order:
                        raise RuntimeError("Create All must list the four zone jobs in dependency order")
                    for index, task in enumerate(root_tasks):
                        expected_dependencies = [root_tasks[index - 1]["task_key"]] if index else []
                        if [item["task_key"] for item in task.get("depends_on", [])] != expected_dependencies:
                            raise RuntimeError("Create All zone jobs must follow raw → stage → core → curated prerequisites")
                        reference = task.get("run_job_task", {}).get("job_id", "")
                        prefix, suffix = chr(36) + "{resources.jobs.", ".id}"
                        if not (reference.startswith(prefix) and reference.endswith(suffix)):
                            raise RuntimeError("Create All must invoke generated zone jobs")
                        zone_keys.add(reference[len(prefix):-len(suffix)])
                    emitted_create_keys = {
                        key for key in create_jobs
                        if key == create_key or key in zone_keys
                        or any(key.startswith(f"Create_{zone}_") for zone in ("raw", "stage", "core", "curated"))
                    }
                    if emitted_create_keys != {create_key, *zone_keys}:
                        raise RuntimeError("Classic target must emit only Create All and one create job per zone")
                    for zone_key in zone_keys:
                        tasks = create_jobs[zone_key].get("tasks", [])
                        if not tasks or any("notebook_task" not in task for task in tasks):
                            raise RuntimeError(f"Create zone job {zone_key} must contain notebook tasks")
                        if any(task.get("depends_on") for task in tasks):
                            raise RuntimeError(f"Create zone job {zone_key} must run all entity DDL tasks in parallel")
                from bundle_assets import required_assets
                print(f"Bundle sync covers {len(required_assets(output.parent))} required assets")
                for job in generated_resources(output.parent)["jobs"].values():
                    check_graph(job["tasks"])
                    notebook_tasks = [task for task in job["tasks"] if task.get("notebook_task")]
                    if notebook_tasks:
                        cluster_keys = {item.get("job_cluster_key") for item in job.get("job_clusters", [])}
                        if not cluster_keys or any(task.get("job_cluster_key") not in cluster_keys for task in notebook_tasks):
                            raise RuntimeError("Classic Databricks notebook tasks must use a job cluster from their model job property")
                        if any(task.get("new_cluster") or task.get("existing_cluster_id") for task in notebook_tasks):
                            raise RuntimeError("Classic Databricks notebook tasks must not bypass the job-level cluster property")
                print(f"Manifest execution plan: {roots}")
            if name == "databricks-lakeflow":
                from check_native_lakeflow import check_output
                check_output(output)
            result = {"target": name, "result": "passed", "files": len(files), "python_files": python_count}
            print(f"PASS {name}: {len(files)} files, {python_count} Python files compile")
        except Exception as error:
            result = {"target": name, "result": "failed", "error": str(error)}
            failures.append(name)
            print(f"FAIL {name}: {error}", file=sys.stderr)
        results.append(result)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    from importlib.metadata import version
    report = {"commit": revision, "generator": version("datam8"), "selected_targets": selected, "targets": results, "result": "failed" if failures else "passed"}
    (report_directory / "generation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("Generation failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
