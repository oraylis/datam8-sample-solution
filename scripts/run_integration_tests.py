"""Deploy and exercise existing Databricks bundles, then verify their catalog data."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from check_generation import check_generated_python
from databricks_jobs import PHASE_TIMEOUTS, execute_root, generated_resources, lifecycle_roots

ROOT = Path(__file__).resolve().parents[1]
TARGETS = json.loads((ROOT / "tests/integration/targets.json").read_text(encoding="utf-8"))
SCHEMAS = {"raw": 12, "stage": 11, "core": 3, "curated": 3}


def cli(args: list[str], *, cwd: Path, profile: str | None, timeout: int = 3600) -> str:
    command = ["databricks"] + (["--profile", profile] if profile else []) + args
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Databricks command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout


def sql(statement: str, *, warehouse: str, profile: str | None) -> list[list[str]]:
    payload = json.dumps({"warehouse_id": warehouse, "statement": statement, "wait_timeout": "50s"})
    result = cli(["--output", "json", "api", "post", "/api/2.0/sql/statements", "--json", payload], cwd=ROOT, profile=profile, timeout=90)
    response = json.loads(result)
    deadline = time.monotonic() + 1800
    while response["status"]["state"] in {"PENDING", "RUNNING"}:
        if time.monotonic() >= deadline:
            cli(["--output", "json", "api", "post", f"/api/2.0/sql/statements/{response['statement_id']}/cancel", "--json", "{}"], cwd=ROOT, profile=profile, timeout=60)
            raise TimeoutError(f"SQL statement timed out: {statement[:120]}")
        time.sleep(5)
        response = json.loads(cli(["--output", "json", "api", "get", f"/api/2.0/sql/statements/{response['statement_id']}"] , cwd=ROOT, profile=profile, timeout=60))
    if response["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {response['status']}")
    return response.get("result", {}).get("data_array", [])


def api(method: str, path: str, body: dict | None = None, *, profile: str | None):
    args = ["--output", "json", "api", method.lower(), path]
    if body is not None:
        args += ["--json", json.dumps(body)]
    response = cli(args, cwd=ROOT, profile=profile, timeout=120)
    return json.loads(response) if response.strip() else {}


def bundle_summary(bundle: Path, profile: str | None) -> dict:
    return json.loads(cli(["--output", "json", "bundle", "summary", "--force-pull", "--target", "e2e-serverless"], cwd=bundle, profile=profile, timeout=120))["resources"]


def require_existing_deployment(resources: dict, summary: dict) -> None:
    for kind, values in summary.items():
        unexpected = set(values) - set(resources.get(kind, {}))
        if unexpected:
            raise RuntimeError(f"Deployment state has unexpected {kind}: {sorted(unexpected)}; refusing resource deletion")
    for kind, values in resources.items():
        for key in values:
            if not summary.get(kind, {}).get(key, {}).get("id"):
                raise RuntimeError(f"Existing bundle resource is not bound: {kind}.{key}; refusing to create a second deployment")


def assert_no_rows(statement: str, *, warehouse: str, profile: str | None) -> None:
    rows = sql(statement, warehouse=warehouse, profile=profile)
    if rows:
        raise RuntimeError(f"Data integrity check failed: {statement}")


def generated_table_names(bundle: Path) -> dict[str, set[str]]:
    tables = {schema: set() for schema in SCHEMAS}
    notebooks = bundle / "generated" / "notebooks"
    for path in notebooks.rglob("*.py"):
        if "/ddl/" not in path.as_posix().lower():
            continue
        source = path.read_text(encoding="utf-8")
        ddl = re.search(r"# MAGIC # DDL for ([^.]+)\.([^\s]+)", source)
        if ddl and ddl.group(1).lower() in tables:
            tables[ddl.group(1).lower()].add(ddl.group(2).lower())
    external_notebooks = bundle / "generated" / "pipelines" / "notebooks" / "external"
    for path in external_notebooks.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for name in re.findall(r'@dp\.table\(name=[\"\']([^\"\']+)[\"\']\)', source):
            tables["raw"].add(name.lower())
    entity_notebooks = bundle / "generated" / "pipelines" / "notebooks" / "entities"
    zone_by_folder = {"010-stage": "stage", "020-core": "core", "030-curated": "curated"}
    for path in entity_notebooks.rglob("*.py"):
        schema = next(
            (zone for folder, zone in zone_by_folder.items() if folder in {part.lower() for part in path.parts}),
            None,
        )
        if not schema:
            continue
        source = path.read_text(encoding="utf-8")
        for name in re.findall(r'@dp\.table\(name=[\"\']([^\"\']+)[\"\']\)', source):
            tables[schema].add(name.lower())
    external_pipelines = bundle / "generated" / "pipelines" / "external"
    for path in external_pipelines.rglob("*.yml"):
        source = path.read_text(encoding="utf-8")
        for name in re.findall(r"^\s*destination_table:\s*([^\s]+)\s*$", source, re.MULTILINE):
            tables["raw"].add(name.lower())
    for schema, expected_count in SCHEMAS.items():
        if len(tables[schema]) != expected_count:
            raise RuntimeError(
                f"Generated bundle has {len(tables[schema])} {schema} DDL notebooks; "
                f"expected {expected_count}"
            )
    return tables


def test_target(name, args, record):
    spec = TARGETS[name]
    catalog = spec["catalog"]
    # Reset only the dedicated test schemas. Unexpected schemas or table counts stop before DROP.
    existing = {row[0] for row in sql(f"SHOW SCHEMAS IN `{catalog}`", warehouse=args.warehouse_id, profile=args.profile)}
    foreign = existing - set(SCHEMAS) - {"default", "information_schema"}
    if foreign:
        raise RuntimeError(f"Refusing reset of {catalog}; unexpected schemas: {sorted(foreign)}")
    with tempfile.TemporaryDirectory(prefix=f"datam8-{name}-") as temporary:
        solution = Path(temporary) / "solution"
        shutil.copytree(ROOT, solution, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".databricks", "generated", "e2e-test-reports"))
        bundle = solution / spec["bundle_path"]
        descriptor = solution / "ORAYLISDatabricksSample.dm8s"
        subprocess.run(["datam8", "validate", "--solution", str(descriptor)], cwd=solution, check=True, timeout=300)
        subprocess.run(["datam8", "generate", name, "--solution", str(descriptor), "--clean-output"], cwd=solution, check=True, timeout=900)
        cli(["bundle", "validate", "--target", "e2e-serverless"], cwd=bundle, profile=args.profile, timeout=300)
        check_generated_python(bundle / "generated")
        resources = generated_resources(bundle)
        roots = lifecycle_roots(resources)
        before = bundle_summary(bundle, args.profile)
        require_existing_deployment(resources, before)
        record({"roots": [{"phase": phase, "resource": key} for phase, key in roots], "resources_before": before})
        for job in before.get("jobs", {}).values():
            active = api("GET", f"/api/2.2/jobs/runs/list?job_id={job['id']}&active_only=true", profile=args.profile).get("runs", [])
            if active:
                raise RuntimeError(f"Active test runs exist for job {job['id']}")
        for pipeline in before.get("pipelines", {}).values():
            status = api("GET", f"/api/2.0/pipelines/{pipeline['id']}", profile=args.profile)
            if any(update.get("state") not in {"COMPLETED", "FAILED", "CANCELED"} for update in status.get("latest_updates", [])[:1]):
                raise RuntimeError(f"Active pipeline update exists for {pipeline['id']}")
        expected_tables = generated_table_names(bundle)
        for schema in existing & set(SCHEMAS):
            for object_kind, schema_column, name_column in (("routines", "routine_schema", "routine_name"), ("volumes", "volume_schema", "volume_name")):
                foreign_objects = sql(f"SELECT {name_column} FROM `{catalog}`.information_schema.{object_kind} WHERE {schema_column} = '{schema}'", warehouse=args.warehouse_id, profile=args.profile)
                if foreign_objects:
                    raise RuntimeError(f"Refusing reset: {catalog}.{schema} contains {object_kind}")
            names = {
                row[1].lower()
                for row in sql(f"SHOW TABLES IN `{catalog}`.`{schema}`", warehouse=args.warehouse_id, profile=args.profile)
            }
            unexpected = names - expected_tables[schema]
            if unexpected:
                raise RuntimeError(
                    f"Refusing reset: {catalog}.{schema} contains unexpected tables: {sorted(unexpected)}"
                )
        for schema in reversed(SCHEMAS):
            if schema in existing:
                sql(f"DROP SCHEMA `{catalog}`.`{schema}` CASCADE", warehouse=args.warehouse_id, profile=args.profile)
        cli(["bundle", "deploy", "--target", "e2e-serverless"], cwd=bundle, profile=args.profile, timeout=900)
        after = bundle_summary(bundle, args.profile)
        require_existing_deployment(resources, after)
        for kind, values in before.items():
            for key, value in values.items():
                if after.get(kind, {}).get(key, {}).get("id") != value.get("id"):
                    raise RuntimeError(f"Deployment replaced existing resource: {kind}.{key}")
        record({"deployment": "passed", "resources_after": after})
        started = time.monotonic()
        job_runs = {}
        for phase, key in roots:
            def record_run(value):
                job_runs[key] = {"phase": phase, **value}
                record({"job_runs": job_runs})
                print(f"{name}: {phase} root {key}, run {value['root_run_id']}: {value.get('result')}", flush=True)
            execute_root(
                lambda method, path, body=None: api(method, path, body, profile=args.profile),
                int(after["jobs"][key]["id"]), timeout=PHASE_TIMEOUTS[phase], record=record_run,
            )
        counts = {}
        tables_by_schema = {}
        for schema, expected_count in SCHEMAS.items():
            tables = [row[1] for row in sql(f"SHOW TABLES IN `{catalog}`.`{schema}`", warehouse=args.warehouse_id, profile=args.profile)]
            if len(tables) != expected_count:
                raise RuntimeError(f"{catalog}.{schema}: expected {expected_count} tables, got {len(tables)}")
            counts[schema] = {}
            tables_by_schema[schema] = {table.lower(): table for table in tables}
            for table in tables:
                rows = int(sql(f"SELECT COUNT(*) FROM `{catalog}`.`{schema}`.`{table}`", warehouse=args.warehouse_id, profile=args.profile)[0][0])
                if rows == 0:
                    raise RuntimeError(f"Empty table: {catalog}.{schema}.{table}")
                counts[schema][table] = rows
        curated = {key.rsplit("_", 1)[-1]: value for key, value in tables_by_schema["curated"].items()}
        required = {"dimcustomer", "dimdate", "factsalesorder"}
        if not required <= curated.keys():
            raise RuntimeError(f"Missing curated tables: {sorted(required - curated.keys())}")
        customer, date, fact = (curated[key] for key in ("dimcustomer", "dimdate", "factsalesorder"))
        dimcustomer = f"`{catalog}`.`curated`.`{customer}`"
        dimdate = f"`{catalog}`.`curated`.`{date}`"
        factsales = f"`{catalog}`.`curated`.`{fact}`"
        assert_no_rows(f"SELECT CustomerSID FROM {dimcustomer} WHERE CustomerSID IS NULL GROUP BY CustomerSID HAVING COUNT(*) > 0", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT CustomerSID FROM {dimcustomer} GROUP BY CustomerSID HAVING COUNT(*) > 1", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT DateSID FROM {dimdate} WHERE DateSID IS NULL GROUP BY DateSID HAVING COUNT(*) > 0", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT DateSID FROM {dimdate} GROUP BY DateSID HAVING COUNT(*) > 1", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT DateID FROM {dimdate} GROUP BY DateID HAVING COUNT(*) > 1", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT f.CustomerSID FROM {factsales} f LEFT ANTI JOIN {dimcustomer} d ON f.CustomerSID = d.CustomerSID", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT f.ShipDateID FROM {factsales} f LEFT ANTI JOIN {dimdate} d ON f.ShipDateID = d.DateID WHERE f.ShipDateID IS NOT NULL", warehouse=args.warehouse_id, profile=args.profile)
        assert_no_rows(f"SELECT CustomerID, AddressType FROM {dimcustomer} WHERE __IsCurrent GROUP BY CustomerID, AddressType HAVING COUNT(*) > 1", warehouse=args.warehouse_id, profile=args.profile)
        return {"tables": counts, "result": "passed", "elapsed_seconds": round(time.monotonic() - started)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="all")
    parser.add_argument("--profile")
    parser.add_argument("--warehouse-id", default=os.getenv("DATABRICKS_SQL_WAREHOUSE_ID"))
    args = parser.parse_args()
    selected = list(TARGETS) if args.target == "all" else [args.target]
    if not selected or any(target not in TARGETS for target in selected):
        parser.error(f"Unknown target. Available: {', '.join(TARGETS)}")
    if not args.warehouse_id:
        parser.error("Set --warehouse-id or DATABRICKS_SQL_WAREHOUSE_ID for catalog data checks")
    if not args.profile and not os.getenv("DATABRICKS_HOST"):
        parser.error("Use --profile locally or configure DATABRICKS_HOST and Databricks authentication")
    warehouse = json.loads(cli(["--output", "json", "api", "get", f"/api/2.0/sql/warehouses/{args.warehouse_id}"], cwd=ROOT, profile=args.profile, timeout=60))
    if not (
        warehouse.get("warehouse_type") == "SERVERLESS"
        or warehouse.get("enable_serverless_compute") is True
    ):
        parser.error("The configured SQL warehouse must be serverless")
    report_dir = ROOT / "Output/e2e-test-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"integration-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    versions = {program: subprocess.run([program, "--version"], capture_output=True, text=True, check=True).stdout.strip() for program in ("datam8", "databricks")}
    report = {"commit": os.getenv("GITHUB_SHA") or revision.stdout.strip(), "versions": versions, "created_at": datetime.now(timezone.utc).isoformat(), "selected_targets": selected, "targets": [], "result": "running"}

    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for name in selected:
        target = {"target": name, "catalog": TARGETS[name]["catalog"], "result": "running"}
        report["targets"].append(target)

        def record(value):
            target.update(value)
            save()

        record({})
        print(f"Testing {name}", flush=True)
        try:
            record(test_target(name, args, record))
        except Exception as error:
            record({"result": "failed", "error": f"{type(error).__name__}: {error}"})
            print(f"FAIL: {name}: {error}", flush=True)

    passed = [target for target in report["targets"] if target["result"] == "passed"]
    if len(passed) > 1:
        report["comparison"] = "passed" if all(target["tables"] == passed[0]["tables"] for target in passed[1:]) else "failed"
    report["result"] = "passed" if len(passed) == len(selected) and report.get("comparison") != "failed" else "failed"
    save()
    print(f"Integration result: {report['result']}; report: {report_path}", flush=True)
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report_dir = ROOT / "Output/e2e-test-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "commit": os.getenv("GITHUB_SHA", "local"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "result": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        (report_dir / f"integration-failed-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json").write_text(
            json.dumps(failure, indent=2), encoding="utf-8"
        )
        raise
