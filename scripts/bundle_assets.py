"""Check the actual bundle configuration and its local asset closure offline."""
from pathlib import Path
import glob
import os
import re

import yaml

from databricks_jobs import generated_resources


def bundle_configuration(bundle: Path):
    """Load explicit generated includes; reject missing or omitted resources."""
    configuration = yaml.safe_load((bundle / "databricks.yml").read_text(encoding="utf-8"))
    root = bundle.resolve().parents[1]
    included = set()
    for pattern in configuration["include"]:
        matches = {Path(name).resolve() for name in glob.glob(str(bundle / pattern))}
        if not matches or any(not path.is_relative_to(root / "output/databricks") for path in matches):
            raise ValueError("Missing or external resource include: " + pattern)
        included.update(matches)
    expected = {path.resolve() for path in (root / "output/databricks").rglob("*.yml")}
    if included != expected:
        raise ValueError("Bundle includes must cover every generated resource YAML")
    for path in sorted(included):
        addition = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section in ("variables", "resources"):
            destination = configuration.setdefault(section, {})
            for key, value in addition.get(section, {}).items():
                if section == "resources":
                    group = destination.setdefault(key, {})
                    if group.keys() & value.keys():
                        raise ValueError("Duplicate resource in " + str(path))
                    group.update(value)
                else:
                    if key in destination:
                        raise ValueError("Duplicate variable: " + key)
                    destination[key] = value
    references = set(re.findall(r"\$\{var\.([^}]+)\}", yaml.safe_dump(configuration)))
    if references - configuration["variables"].keys():
        raise ValueError("Undeclared bundle variables: " + str(sorted(references - configuration["variables"].keys())))
    return configuration


def required_assets(bundle: Path):
    configuration = bundle_configuration(bundle)
    root = bundle.resolve().parents[1]
    sync = configuration["sync"]
    roots = {(bundle / value).resolve() for value in sync["paths"]}
    if roots != {root / "output/databricks", root / "utils"}:
        raise ValueError("Sync must select only generated Databricks output and authored utils")
    if Path(os.path.commonpath([bundle.resolve(), *roots])) != root:
        raise ValueError("Unexpected bundle sync root")
    required = set()

    def local(value):
        prefix = "${workspace.file_path}/"
        if not value.startswith(prefix):
            raise ValueError("Unresolved bundle asset path: " + value)
        path = root / value[len(prefix):]
        if not path.is_file() and path.with_suffix(".py").is_file():
            path = path.with_suffix(".py")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Missing or external bundle asset: " + value)
        required.add(path.resolve())

    resources = generated_resources(root / "output/databricks")
    for job in resources.get("jobs", {}).values():
        for task in job.get("tasks", []):
            if "notebook_task" in task:
                local(task["notebook_task"]["notebook_path"])
    required.update(path.resolve() for path in (root / "output/databricks/runtime").glob("*.py"))
    pending = list(required)
    while pending:
        path = pending.pop()
        for target in re.findall(r"(?m)^# MAGIC %run\s+([^\s]+)", path.read_text(encoding="utf-8")):
            dependency = (path.parent / target).with_suffix(".py").resolve()
            if not dependency.is_relative_to(root) or not dependency.is_file():
                raise ValueError("Missing %run dependency in " + str(path.relative_to(root)))
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)
    # Fail closed if these simple patterns change; do not approximate the CLI's
    # full gitignore semantics in this repository-specific offline check.
    def covered(path, pattern):
        if not pattern.endswith('/**') or any(char in pattern[:-3] for char in '*?!['):
            raise ValueError("Unsupported sync pattern in offline checker: " + pattern)
        return path.is_relative_to((bundle / pattern[:-3]).resolve())

    for path in required:
        if (not any(path.is_relative_to(folder) for folder in roots)
                or not any(covered(path, pattern) for pattern in sync.get("include", []))
                or any(covered(path, pattern) for pattern in sync.get("exclude", []))):
            raise ValueError("Referenced asset excluded from bundle sync: " + str(path.relative_to(root)))
    return sorted(path.relative_to(root).as_posix() for path in required)
