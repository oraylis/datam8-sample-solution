"""Discover bundle lifecycle roots and verify their complete remote execution trees."""

from __future__ import annotations

import time
import re
from urllib.parse import urlencode

import yaml

PHASE_TIMEOUTS = {"create": 1800, "load": 5400, "validate": 1800}
TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
JOB_REFERENCE = re.compile(r"\$\{resources\.jobs\.([^.]+)\.id\}")


def generated_resources(bundle) -> dict:
    resources = {}
    for path in sorted((bundle / "generated").rglob("*.yml")):
        for kind, values in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("resources", {}).items():
            destination = resources.setdefault(kind, {})
            if destination.keys() & values.keys():
                raise RuntimeError(f"Duplicate {kind} resource in {path}")
            destination.update(values)
    return resources


def execution_plan(resources: dict, manifest: dict, *, required_phases=("create", "load")) -> list[tuple[str, str]]:
    """Resolve existing job entry points and their modeled cross-job DAG."""
    jobs = resources.get("jobs", {})
    plan = manifest.get("execution_plan", {})
    ordered = []
    nested_jobs = {}
    for key, definition in jobs.items():
        children = set()
        for task in definition.get("tasks", []):
            nested = task.get("run_job_task")
            if nested:
                match = JOB_REFERENCE.fullmatch(str(nested.get("job_id", "")))
                if not match or match[1] not in jobs:
                    raise ValueError(f"{key}: nested job must reference a job in this bundle")
                children.add(match[1])
        nested_jobs[key] = children
    create = plan.get("create")
    if create:
        key = create.get("job")
        if key not in jobs or create.get("depends_on"):
            raise ValueError("Create execution plan must reference one existing root job")
        ordered.append(("create", key))
        create_jobs, active = set(), set()
        def visit_create(parent):
            if parent in active:
                raise ValueError("Cycle in nested create-job graph")
            if parent in create_jobs:
                return
            active.add(parent)
            for child in nested_jobs[parent]:
                visit_create(child)
            active.remove(parent)
            create_jobs.add(parent)
        visit_create(key)
    else:
        create_jobs = set()
    load = plan.get("load", [])
    if not isinstance(load, list) or not load:
        raise ValueError("Load execution plan must list existing model jobs")
    entries = {entry.get("job"): set(entry.get("depends_on", [])) for entry in load}
    if None in entries or len(entries) != len(load):
        raise ValueError("Load execution plan contains missing or duplicate jobs")
    if set(entries) - jobs.keys():
        raise ValueError("Load execution plan references a job outside this bundle")
    if set(entries) & create_jobs:
        raise ValueError("A job cannot be both a create task and a load entry point")
    if any(dependencies - entries.keys() for dependencies in entries.values()):
        raise ValueError("Load execution plan has a dependency outside the selected load jobs")
    if manifest.get("target") == "databricks":
        for key in entries:
            if nested_jobs[key]:
                raise ValueError(f"{key}: modeled load jobs must not invoke another load job")
    resolved, pending = set(), set(entries)
    while pending:
        ready = [entry["job"] for entry in load if entry["job"] in pending and entries[entry["job"]] <= resolved]
        if not ready:
            raise ValueError("Cycle in load execution plan")
        for key in ready:
            ordered.append(("load", key))
            resolved.add(key)
            pending.remove(key)
    phases = {phase for phase, _ in ordered}
    if set(required_phases) - phases:
        raise ValueError("Execution plan is missing required phases: " + ", ".join(sorted(set(required_phases) - phases)))
    if set(jobs) != create_jobs | set(entries):
        raise ValueError("Bundle contains jobs that are not represented in the manifest execution plan")
    return ordered


def get_run(api, run_id: int) -> dict:
    result = api("GET", "/api/2.2/jobs/runs/get?" + urlencode({"run_id": run_id}))
    tasks = list(result.get("tasks", []))
    page = result.get("next_page_token")
    while page:
        more = api("GET", "/api/2.2/jobs/runs/get?" + urlencode({"run_id": run_id, "page_token": page}))
        tasks.extend(more.get("tasks", []))
        page = more.get("next_page_token")
    result["tasks"] = tasks
    return result


def execution_tree(api, run_id: int, *, check_pipelines: bool = True) -> dict:
    """Collect child runs through task output, never by job-name matching."""
    runs, errors, seen = [], [], set()

    def visit(identifier):
        if identifier in seen:
            return
        seen.add(identifier)
        run = get_run(api, identifier)
        state = run.get("state", {})
        entry = {"run_id": identifier, "job_id": run.get("job_id"), "url": run.get("run_page_url"), "state": state, "tasks": []}
        runs.append(entry)
        if state.get("result_state") != "SUCCESS":
            errors.append(f"Run {identifier}: {state}")
        if not run.get("tasks"):
            errors.append(f"Run {identifier} returned no tasks")
        latest = {}
        for task in run.get("tasks", []):
            key = task["task_key"]
            rank = (task.get("attempt_number", 0), task.get("start_time", 0))
            previous = latest.get(key)
            if previous is None or rank > (previous.get("attempt_number", 0), previous.get("start_time", 0)):
                latest[key] = task
        for task in latest.values():
            task_state = task.get("state", {})
            item = {"task_key": task.get("task_key"), "run_id": task.get("run_id"), "state": task_state, "attempts": [
                {"run_id": attempt.get("run_id"), "attempt_number": attempt.get("attempt_number", 0), "state": attempt.get("state", {})}
                for attempt in run["tasks"] if attempt["task_key"] == task["task_key"]
            ]}
            entry["tasks"].append(item)
            if task_state.get("result_state") != "SUCCESS":
                errors.append(f"Run {identifier}, task {item['task_key']}: {task_state}")
            if "run_job_task" in task and task.get("run_id"):
                try:
                    output = api("GET", f"/api/2.2/jobs/runs/get-output?run_id={task['run_id']}")
                except RuntimeError:
                    if task_state.get("result_state") == "SUCCESS":
                        raise
                    output = {}
                child = output.get("run_job_output", {}).get("run_id")
                if child:
                    item["child_run_id"] = int(child)
                    visit(int(child))
                elif task_state.get("result_state") == "SUCCESS":
                    errors.append(f"Successful nested task {item['task_key']} has no child run ID")
            if check_pipelines and "pipeline_task" in task and task_state.get("result_state") == "SUCCESS":
                pipeline_id = task["pipeline_task"]["pipeline_id"]
                updates = api("GET", f"/api/2.0/pipelines/{pipeline_id}/updates").get("updates", [])
                matching = [update for update in updates if task.get("start_time", 0) <= update.get("creation_time", 0) <= task.get("end_time", 0)]
                if not matching:
                    errors.append(f"Pipeline task {item['task_key']} has no update in its execution window")
                else:
                    update = max(matching, key=lambda value: value["creation_time"])
                    item["pipeline_update"] = {"pipeline_id": pipeline_id, "update_id": update["update_id"], "state": update.get("state")}
                    if update.get("state") != "COMPLETED":
                        errors.append(f"Pipeline {pipeline_id} update {update['update_id']}: {update.get('state')}")

    visit(int(run_id))
    return {"root_run_id": int(run_id), "runs": runs, "errors": errors}


def execute_root(
    api,
    job_id: int,
    *,
    timeout: int,
    record,
    poll_seconds: int = 15,
    repair_run_id: int | None = None,
    rerun_tasks: list[str] | None = None,
) -> dict:
    if repair_run_id is None:
        run_id = int(api("POST", "/api/2.2/jobs/run-now", {"job_id": int(job_id)})["run_id"])
        repair_id = None
    else:
        if not rerun_tasks:
            raise ValueError("A repaired job run must name at least one failed task")
        history = api(
            "GET",
            "/api/2.2/jobs/runs/get?" + urlencode({"run_id": int(repair_run_id), "include_history": "true"}),
        ).get("repair_history", [])
        previous_repairs = [
            item for item in history
            if item.get("type") == "REPAIR" and item.get("id") is not None
        ]
        repair_request = {"run_id": int(repair_run_id), "rerun_tasks": sorted(set(rerun_tasks))}
        if previous_repairs:
            # The API returns repair history in chronological order, but the
            # opaque repair IDs are not monotonic. Use the latest entry, not
            # the numerically largest ID.
            repair_request["latest_repair_id"] = int(previous_repairs[-1]["id"])
        repair = api(
            "POST",
            "/api/2.2/jobs/runs/repair",
            repair_request,
        )
        run_id = int(repair_run_id)
        repair_id = repair.get("repair_id")
    receipt = {"root_run_id": run_id, "job_id": int(job_id), "result": "running"}
    if repair_id is not None:
        receipt["repair_id"] = repair_id
        receipt["repaired_tasks"] = sorted(set(rerun_tasks or []))
    record(receipt)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = get_run(api, run_id)
        if run.get("state", {}).get("life_cycle_state") in TERMINAL:
            tree = execution_tree(api, run_id)
            tree["result"] = "failed" if tree["errors"] else "passed"
            record(tree)
            if tree["errors"]:
                raise RuntimeError("; ".join(tree["errors"]))
            return tree
        time.sleep(poll_seconds)
    api("POST", "/api/2.2/jobs/runs/cancel", {"run_id": run_id})
    tree = execution_tree(api, run_id, check_pipelines=False)
    for run in reversed(tree["runs"]):
        if run["run_id"] != run_id and run["state"].get("life_cycle_state") not in TERMINAL:
            api("POST", "/api/2.2/jobs/runs/cancel", {"run_id": run["run_id"]})
    tree["result"] = "timed_out"
    record(tree)
    raise TimeoutError(f"Root run {run_id} exceeded {timeout}s; cancellation requested for active runs")
