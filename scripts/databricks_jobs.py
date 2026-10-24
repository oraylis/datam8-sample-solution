"""Discover bundle lifecycle roots and verify their complete remote execution trees."""

from __future__ import annotations

import re
import time
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


def lifecycle_roots(resources: dict) -> list[tuple[str, str]]:
    """Select graph roots by semantic tags, independently of generated job names."""
    jobs = resources.get("jobs", {})
    if not jobs:
        raise ValueError("Bundle defines no jobs")
    edges = {}
    for key, job in jobs.items():
        children = set()
        for task in job.get("tasks", []):
            nested = task.get("run_job_task")
            if not nested:
                continue
            match = JOB_REFERENCE.fullmatch(str(nested.get("job_id", "")))
            if not match or match[1] not in jobs:
                raise ValueError(f"{key}: nested job must reference a job in this bundle")
            children.add(match[1])
        edges[key] = children
    visited, pending = set(), set()

    def visit(key):
        if key in pending:
            raise ValueError(f"Cycle in bundle job graph at {key}")
        if key in visited:
            return
        pending.add(key)
        for child in edges[key]:
            visit(child)
        pending.remove(key)
        visited.add(key)

    for key in jobs:
        visit(key)
    called = set().union(*edges.values())
    phases = {}
    for key in sorted(set(jobs) - called):
        phase = jobs[key].get("tags", {}).get("datam8_phase")
        if phase not in PHASE_TIMEOUTS:
            raise ValueError(f"Root job {key} needs a supported datam8_phase tag")
        phases.setdefault(phase, []).append(key)
    if not {"create", "load"} <= phases.keys():
        raise ValueError("Bundle needs create and load lifecycle roots")
    return [(phase, key) for phase in PHASE_TIMEOUTS for key in phases.get(phase, [])]


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


def execute_root(api, job_id: int, *, timeout: int, record, poll_seconds: int = 15) -> dict:
    run_id = int(api("POST", "/api/2.2/jobs/run-now", {"job_id": int(job_id)})["run_id"])
    record({"root_run_id": run_id, "job_id": int(job_id), "result": "running"})
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
