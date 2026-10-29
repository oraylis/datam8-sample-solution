"""Revision-bound job evidence and cumulative phase budgets."""
from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import contextmanager

from databricks_jobs import PHASE_TIMEOUTS


def semantic_json(value, field=""):
    if isinstance(value, dict):
        return {key: semantic_json(item, key) for key, item in value.items()}
    if isinstance(value, list):
        items = [semantic_json(item) for item in value]
        if field in {"tasks", "depends_on", "job_clusters", "permissions", "parameters"}:
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return items
    return value


def job_fingerprints(bundle, resources, *, keys=None):
    configuration_files = [bundle / "databricks.yml", bundle / "bundle.targets.yml", *sorted((bundle / "generated/clusters").glob("*.yml"), key=lambda path: path.name)]
    config = b"".join(path.read_text(encoding="utf-8").encode() for path in configuration_files if path.exists())
    results = {}

    def digest_job(key):
        if key in results:
            return results[key]
        definition = resources["jobs"][key]
        digest = hashlib.sha256(config + json.dumps(semantic_json(definition), sort_keys=True).encode())
        paths = set()
        for task in definition.get("tasks", []):
            nested = task.get("run_job_task", {}).get("job_id", "")
            match = re.fullmatch(r"\$\{resources.jobs.([^.]+).id\}", str(nested))
            if match:
                digest.update(digest_job(match[1]).encode())
            pipeline = task.get("pipeline_task", {}).get("pipeline_id", "")
            match = re.fullmatch(r"\$\{resources.pipelines.([^.]+).id\}", str(pipeline))
            if match:
                spec = resources["pipelines"][match[1]]
                digest.update(json.dumps(semantic_json(spec), sort_keys=True).encode())
                for library in spec.get("libraries", []):
                    path = library.get("file", {}).get("path", "")
                    if "/pipelines/" in path:
                        paths.add(bundle / "generated/pipelines" / path.split("/pipelines/", 1)[1])
            path = task.get("notebook_task", {}).get("notebook_path", "")
            if "${var.notebook_path}/" in path:
                paths.add(bundle / "generated/notebooks" / (path.split("${var.notebook_path}/", 1)[1] + ("" if path.endswith(".py") else ".py")))
            elif "/files/utils/" in path:
                paths.add(bundle / "utils" / (path.split("/files/utils/", 1)[1] + ("" if path.endswith(".py") else ".py")))
        # Runtime and function files are actual dependencies of their importing notebooks.
        pending = list(paths)
        while pending:
            path = pending.pop()
            if not path.is_file():
                raise ValueError("Referenced job asset does not exist: " + str(path))
            source = path.read_text(encoding="utf-8")
            dependencies = []
            for module in re.findall(r"from (\w+) import", source):
                dependencies.extend((bundle / "generated/runtime").glob(module + ".py"))
                dependencies.extend((bundle / "utils").glob(module + ".py"))
            for relative in re.findall(r"%run\s+\./([^\s]+)", source):
                dependencies.append(path.parent / (relative if relative.endswith(".py") else relative + ".py"))
            for dep in dependencies:
                if dep not in paths:
                    paths.add(dep)
                    pending.append(dep)
        for path in sorted(paths, key=lambda item: item.relative_to(bundle).as_posix()):
            digest.update(path.relative_to(bundle).as_posix().encode() + b"\0" + path.read_text(encoding="utf-8").encode())
        results[key] = digest.hexdigest()
        return results[key]

    for key in resources.get("jobs", {}) if keys is None else keys:
        digest_job(key)
    return results


def task_fingerprints(bundle, resources):
    result = {}
    for key, definition in resources.get("jobs", {}).items():
        tasks = {}
        for task in definition.get("tasks", []):
            subset = {**resources, "jobs": {**resources["jobs"], key: {**definition, "tasks": [task]}}}
            tasks[task["task_key"]] = job_fingerprints(bundle, subset, keys=[key])[key]
        result[key] = tasks
    return result


def affected_tasks(definition, current, previous):
    changed = {key for key, value in current.items() if previous.get(key) != value}
    while True:
        dependent = {task["task_key"] for task in definition.get("tasks", []) if any(dep["task_key"] in changed for dep in task.get("depends_on", []))}
        if dependent <= changed:
            return sorted(changed)
        changed |= dependent


class PhaseBudget:
    def __init__(self, consumed=None):
        self.consumed = dict(consumed or {})

    def remaining(self, phase):
        remaining = int(PHASE_TIMEOUTS[phase] - self.consumed.get(phase, 0))
        if remaining <= 0:
            raise TimeoutError(f"The {phase} phase exceeded its {PHASE_TIMEOUTS[phase] // 60}-minute budget")
        return remaining

    @contextmanager
    def measure(self, phase):
        self.remaining(phase)
        start = time.monotonic()
        try:
            yield
        finally:
            self.consumed[phase] = self.consumed.get(phase, 0) + time.monotonic() - start
