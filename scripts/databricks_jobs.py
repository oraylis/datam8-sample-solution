"""Discover generated resource graphs without cloud execution or deployment bindings."""

from __future__ import annotations

import time
import re
from urllib.parse import urlencode

import yaml

PHASE_TIMEOUTS = {"create": 1800, "load": 5400, "validate": 1800}
TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
JOB_REFERENCE = re.compile(r"\$\{resources\.jobs\.([^.]+)\.id\}")


def generated_resources(output) -> dict:
    resources = {}
    for path in sorted(output.rglob("*.yml")):
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

