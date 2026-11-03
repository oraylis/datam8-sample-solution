"""Run the Dev bundle's real-table migration suite and save its notebook result."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote

from run_integration_tests import ROOT, ENVIRONMENTS, api, bundle_summary


def read_progress(call, task_run_id):
    """Read actual notebook output while the run is active; no remote log store."""
    exported = call("GET", f"/api/2.2/jobs/runs/export?run_id={task_run_id}&views_to_export=ALL")
    cases = []
    baseline = None
    for view in exported.get("views", []):
        match = re.search(r"__DATABRICKS_NOTEBOOK_MODEL = '([^']+)'", view.get("content", ""))
        if not match:
            continue
        notebook = json.loads(unquote(base64.b64decode(match[1]).decode()))
        for command in notebook.get("commands", []):
            data = (command.get("results") or {}).get("data", [])
            outputs = (
                [data] if isinstance(data, str) else [part.get("data", "") for part in data if isinstance(part, dict)]
            )
            for output in outputs:
                if not isinstance(output, str):
                    continue
                for line in output.splitlines():
                    if line.startswith("MIGRATION_TEST_CASE "):
                        cases.append(json.loads(line.split(" ", 1)[1]))
                    elif line.startswith("MIGRATION_TEST_BASELINE "):
                        baseline = json.loads(line.split(" ", 1)[1])
                    elif line.startswith(("MIGRATION_TEST_REPORT ", "MIGRATION_TEST_RECOVERY_REQUIRED ")):
                        report = json.loads(line.split(" ", 1)[1])
                        baseline = {k: v for k, v in report.items() if k != "tests"}
                        cases = report["tests"]
    return baseline, cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scenarios", default="*", help="Comma-separated scenario names/globs")
    parser.add_argument("--run-id", type=int, help="Collect an already submitted run; never resubmit it")
    parser.add_argument(
        "--permission-probe", action="store_true", help="Run the negative preflight as the local operator"
    )
    parser.add_argument(
        "--cleanup-backup",
        action="append",
        default=[],
        help="Explicit prior backup as FQN=registration-UUID, verified before removal after success",
    )
    parser.add_argument(
        "--recover-baseline", type=Path, help="Restore the explicit saved test baseline using clone provenance"
    )
    args = parser.parse_args()
    cleanup = []
    for value in args.cleanup_backup:
        name, separator, identity = value.rpartition("=")
        if not separator or not re.fullmatch(r"[0-9a-fA-F-]{36}", identity):
            parser.error("--cleanup-backup requires FQN=registration-UUID")
        cleanup.append({"table": name, "id": identity})
    bundle = ROOT / "Output/databricks-lake"

    def call(method, path, body=None):
        for attempt in range(3):
            try:
                return api(method, path, body, profile=args.profile)
            except subprocess.TimeoutExpired:
                if method != "GET" or attempt == 2:
                    raise
                print("Read request timed out; retrying observation of the existing run", flush=True)
                time.sleep(3)

    resources = bundle_summary(bundle, args.profile, "dev")
    job = resources["jobs"]["Migration_Framework_Recovery" if args.recover_baseline else "Migration_Framework_Tests"]
    settings = call("GET", "/api/2.2/jobs/get?job_id=" + str(job["id"]))["settings"]
    if settings.get("run_as", {}).get("service_principal_name") != ENVIRONMENTS["dev"]["run_principal"]:
        raise RuntimeError("Migration tests must use the configured Dev run principal")
    if args.run_id:
        run_id = args.run_id
    else:
        active = call("GET", "/api/2.2/jobs/runs/list?active_only=true").get("runs", [])
        if active:
            raise RuntimeError("An active job exists in Dev; stop writers before migration tests")
        if args.recover_baseline:
            baseline = json.loads(args.recover_baseline.read_text(encoding="utf-8"))
            baseline["mode"] = "restore"
            run_id = call(
                "POST",
                "/api/2.2/jobs/run-now",
                {"job_id": int(job["id"]), "job_parameters": {"recovery_input": json.dumps(baseline)}},
            )["run_id"]
        elif args.permission_probe:
            task = settings["tasks"][0]
            path = task["notebook_task"]["notebook_path"].rsplit("/", 1)[0] + "/Test_MigrationPermissions"
            run_id = call(
                "POST",
                "/api/2.2/jobs/runs/submit",
                {
                    "run_name": "Dev migration permission probe",
                    "tasks": [
                        {
                            "task_key": "permission_probe",
                            "new_cluster": settings["job_clusters"][0]["new_cluster"],
                            "notebook_task": {"notebook_path": path},
                            "timeout_seconds": 1800,
                        }
                    ],
                },
            )["run_id"]
        else:
            run_id = call(
                "POST",
                "/api/2.2/jobs/run-now",
                {
                    "job_id": int(job["id"]),
                    "job_parameters": {"scenarios": args.scenarios, "cleanup_backups": json.dumps(cleanup)},
                },
            )["run_id"]
    directory = ROOT / "Output/e2e-test-reports"
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / f"migration-run-{run_id}.json"
    if args.run_id:
        source_hashes = json.loads(receipt.read_text()).get("source_hashes") if receipt.exists() else None
    else:
        source_hashes = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "Output/databricks-lake/utils/MigrationFramework.py",
                "Output/databricks-lake/utils/Test_MigrationFramework.py",
                "Generate/databricks-lake/ddl_notebook.py.jinja2",
                "Generate/databricks-lake/ddl_notebook_raw.py.jinja2",
            )
        }
    receipt.write_text(
        json.dumps({"run_id": run_id, "scenarios": args.scenarios, "source_hashes": source_hashes}), encoding="utf-8"
    )
    print(f"Migration run: {run_id}; receipt: {receipt}", flush=True)
    previous = None
    progress_at, completed = 0, set()
    while True:
        run = call("GET", "/api/2.2/jobs/runs/get?run_id=" + str(run_id))
        state = run["state"]
        if state != previous:
            print(json.dumps(state), flush=True)
            previous = state
        if state["life_cycle_state"] in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            break
        if time.monotonic() - progress_at >= 60 and run.get("tasks"):
            task = run["tasks"][0]
            if task.get("state", {}).get("life_cycle_state") == "RUNNING":
                try:
                    baseline, cases = read_progress(call, task["run_id"])
                    if baseline is not None:
                        (directory / f"migration-baseline-{run_id}.json").write_text(
                            json.dumps(baseline, indent=2), encoding="utf-8"
                        )
                    for case in cases:
                        if case["name"] not in completed:
                            completed.add(case["name"])
                            print(
                                json.dumps({key: case.get(key) for key in ("name", "passed", "restored", "error")}),
                                flush=True,
                            )
                except RuntimeError:
                    pass  # Live export can be unavailable while the task initializes.
            progress_at = time.monotonic()
        time.sleep(15)
    tasks = run.get("tasks", [])
    outputs = [call("GET", "/api/2.2/jobs/runs/get-output?run_id=" + str(t["run_id"])) for t in tasks]
    report = {
        "run_id": run_id,
        "url": run.get("run_page_url"),
        "state": state,
        "source_hashes": source_hashes,
        "outputs": outputs,
    }
    # Failed notebooks can lose their exit value. Keep the printed baseline and
    # completed cases locally as well, so recovery does not depend on UI output.
    for task in tasks:
        try:
            baseline, cases = read_progress(call, task["run_id"])
        except RuntimeError:
            continue
        if baseline is not None:
            report["baseline"] = baseline
            baseline_path = directory / f"migration-baseline-{run_id}.json"
            baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        if cases:
            report["completed_cases"] = cases
            for case in cases:
                if not case.get("passed") or not case.get("restored"):
                    print(
                        json.dumps({k: case.get(k) for k in ("name", "passed", "restored", "error", "recovery_error")})
                    )
    receipt.write_text(json.dumps(report, indent=2), encoding="utf-8")
    results = []
    for output in outputs:
        value = output.get("notebook_output", {}).get("result")
        if value:
            result = json.loads(value)
            results.append(result)
            print(
                json.dumps(
                    {k: v for k, v in result.items() if k not in {"tests", "original_metadata", "original_spec"}}
                )
            )
            for entry in result.get("tests", []):
                print(json.dumps({k: v for k, v in entry.items() if k not in {"result", "traceback"}}))
        if output.get("error"):
            print(output["error"])
            trace = output.get("error_trace", "")
            print(trace[:4000] + ("\n...\n" + trace[-1000:] if len(trace) > 4000 else ""))
    if (
        state.get("result_state") != "SUCCESS"
        or not results
        or any(
            (
                not (r.get("permission_rejection_verified") or r.get("recovery_verified"))
                and (
                    not r.get("original_restored")
                    or any(not t.get("passed") or not t.get("restored") for t in r["tests"])
                )
            )
            for r in results
        )
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
