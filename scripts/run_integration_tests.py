"""Deploy and exercise existing Databricks bundles, then verify their catalog data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

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


def run_job(resource: str, *, bundle: Path, profile: str | None, timeout: int) -> str:
    started = cli(["--output", "json", "bundle", "run", "--no-wait", "--target", "e2e-serverless", resource], cwd=bundle, profile=profile, timeout=120)
    run_id = json.loads(started)["run_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = json.loads(cli(["--output", "json", "api", "get", f"/api/2.1/jobs/runs/get?run_id={run_id}"], cwd=bundle, profile=profile, timeout=60))
        state = run.get("state", {})
        if state.get("life_cycle_state") in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            if state.get("result_state") != "SUCCESS":
                raise RuntimeError(f"Job {resource} run {run_id} failed: {state}")
            return run.get("run_page_url", str(run_id))
        time.sleep(15)
    cli(["--output", "json", "api", "post", "/api/2.1/jobs/runs/cancel", "--json", json.dumps({"run_id": run_id})], cwd=bundle, profile=profile, timeout=60)
    raise TimeoutError(f"Job {resource} run {run_id} exceeded {timeout} seconds; cancellation requested")


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
    if not args.profile and not (os.getenv("DATABRICKS_AUTH_TYPE") == "github-oidc" and os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_CLIENT_ID")):
        parser.error("Use --profile locally or configure GitHub Databricks OIDC variables")
    reports = []
    for name in selected:
        spec = TARGETS[name]
        bundle_source = ROOT / spec["bundle_path"]
        catalog = spec["catalog"]
        # Reset only the dedicated test schemas. Unexpected schemas or table counts stop before DROP.
        existing = {row[0] for row in sql(f"SHOW SCHEMAS IN `{catalog}`", warehouse=args.warehouse_id, profile=args.profile)}
        foreign = existing - set(SCHEMAS) - {"default", "information_schema"}
        if foreign:
            raise RuntimeError(f"Refusing reset of {catalog}; unexpected schemas: {sorted(foreign)}")
        for schema, expected_count in SCHEMAS.items():
            if schema not in existing:
                continue
            names = [row[1] for row in sql(f"SHOW TABLES IN `{catalog}`.`{schema}`", warehouse=args.warehouse_id, profile=args.profile)]
            if len(names) > expected_count:
                raise RuntimeError(f"Refusing reset: {catalog}.{schema} contains {len(names)} tables; expected at most {expected_count}")

        with tempfile.TemporaryDirectory(prefix=f"datam8-{name}-") as temporary:
            solution = Path(temporary) / "solution"
            shutil.copytree(ROOT, solution, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".databricks", "generated", "e2e-test-reports"))
            bundle = solution / spec["bundle_path"]
            descriptor = solution / "ORAYLISDatabricksSample.dm8s"
            cli(["validate", "--solution", str(descriptor)], cwd=solution, profile=None, timeout=300)
            cli(["generate", name, "--solution", str(descriptor), "--clean-output"], cwd=solution, profile=None, timeout=900)
            cli(["bundle", "validate", "--target", "e2e-serverless"], cwd=bundle, profile=args.profile, timeout=300)
            cli(["bundle", "deploy", "--target", "e2e-serverless"], cwd=bundle, profile=args.profile, timeout=900)
            for schema in existing & set(SCHEMAS):
                sql(f"DROP SCHEMA `{catalog}`.`{schema}` CASCADE", warehouse=args.warehouse_id, profile=args.profile)
            started = time.monotonic()
            job_links = {}
            for phase, timeout in (("create", 1800), ("daily", 2700), ("weekly", 2700)):
                job_links[phase] = run_job(spec["jobs"][phase], bundle=bundle, profile=args.profile, timeout=timeout)
            counts = {}
            for schema, expected_count in SCHEMAS.items():
                tables = [row[1] for row in sql(f"SHOW TABLES IN `{catalog}`.`{schema}`", warehouse=args.warehouse_id, profile=args.profile)]
                if len(tables) != expected_count:
                    raise RuntimeError(f"{catalog}.{schema}: expected {expected_count} tables, got {len(tables)}")
                counts[schema] = {}
                for table in tables:
                    rows = int(sql(f"SELECT COUNT(*) FROM `{catalog}`.`{schema}`.`{table}`", warehouse=args.warehouse_id, profile=args.profile)[0][0])
                    if rows == 0:
                        raise RuntimeError(f"Empty table: {catalog}.{schema}.{table}")
                    counts[schema][table] = rows
            reports.append({"target": name, "catalog": catalog, "job_runs": job_links, "tables": counts, "result": "passed", "elapsed_seconds": round(time.monotonic() - started)})

    if len(reports) > 1:
        baseline = reports[0]["tables"]
        for report in reports[1:]:
            if report["tables"] != baseline:
                raise RuntimeError(f"Target data comparison differs: {reports[0]['target']} vs {report['target']}")

    report = {"commit": os.getenv("GITHUB_SHA", "local"), "created_at": datetime.now(timezone.utc).isoformat(), "targets": reports}
    report_dir = ROOT / "Output/e2e-test-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"integration-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
