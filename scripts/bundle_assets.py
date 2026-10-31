"""Check referenced local assets against a bundle's explicit sync selection."""
from pathlib import Path
import fnmatch
import re

import yaml

from databricks_jobs import generated_resources


def required_assets(bundle: Path):
    configuration = yaml.safe_load((bundle / "databricks.yml").read_text())
    variables = {key: value.get("default") for key, value in configuration.get("variables", {}).items()}
    required = set()

    def local(value):
        for name, default in variables.items():
            if default is not None:
                value = value.replace("${var." + name + "}", str(default))
        for prefix in ("${workspace.root_path}/files/", "${workspace.file_path}/"):
            if value.startswith(prefix):
                path = bundle / value[len(prefix):]
                if not path.is_file() and path.with_suffix(".py").is_file():
                    path = path.with_suffix(".py")
                if not path.is_file() or not path.resolve().is_relative_to(bundle.resolve()):
                    raise ValueError("Missing or external bundle asset: " + value)
                required.add(path.resolve())
                return
        raise ValueError("Unresolved bundle asset path: " + value)

    resources = generated_resources(bundle)
    for job in resources.get("jobs", {}).values():
        for task in job.get("tasks", []):
            if "notebook_task" in task:
                local(task["notebook_task"]["notebook_path"])
    for pipeline in resources.get("pipelines", {}).values():
        for library in pipeline.get("libraries", []):
            for kind in ("file", "notebook"):
                if kind in library:
                    local(library[kind]["path"])
    required.update(path.resolve() for path in (bundle / "generated/runtime").glob("*.py"))
    pending = list(required)
    while pending:
        path = pending.pop()
        for target in re.findall(r"(?m)^# MAGIC %run\s+([^\s]+)", path.read_text(encoding="utf-8")):
            dependency = (path.parent / target).with_suffix(".py").resolve()
            if not dependency.is_relative_to(bundle.resolve()) or not dependency.is_file():
                raise ValueError("Missing %run dependency in " + str(path.relative_to(bundle)))
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)
    include = configuration.get("sync", {}).get("include", [])
    exclude = configuration.get("sync", {}).get("exclude", [])
    for path in required:
        relative = path.relative_to(bundle.resolve()).as_posix()
        if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in include) or any(fnmatch.fnmatchcase(relative, pattern) for pattern in exclude):
            raise ValueError("Referenced asset excluded from bundle sync: " + relative)
    return sorted(path.relative_to(bundle.resolve()).as_posix() for path in required)
