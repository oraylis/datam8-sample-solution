"""Check the actual bundle configuration and its local asset closure offline."""
from pathlib import Path
import glob
import os
import re

from pathspec import GitIgnoreSpec
import yaml

def bundle_configuration(bundle: Path, output: Path | None = None):
    """Load configured resource includes; check generated coverage when supplied."""
    bundle = bundle.resolve()
    configuration = yaml.safe_load((bundle / "databricks.yml").read_text(encoding="utf-8"))
    included = set()
    for pattern in configuration.get("include", []):
        matches = {Path(name).resolve() for name in glob.glob(str(bundle / pattern), recursive=True)
                   if Path(name).is_file()}
        if not matches:
            raise ValueError("Missing resource include: " + pattern)
        included.update(matches)
    if output is not None:
        expected = {path.resolve() for path in output.rglob("*") if path.suffix in {".yml", ".yaml"}}
        if expected - included:
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
    missing = references - configuration.get("variables", {}).keys()
    if missing:
        raise ValueError("Undeclared bundle variables: " + str(sorted(missing)))
    return configuration


def required_assets(bundle: Path, output: Path | None = None):
    bundle = bundle.resolve()
    configuration = bundle_configuration(bundle, output)
    sync = configuration.get("sync", {})
    roots = {(bundle / value).resolve() for value in sync.get("paths", ["."])}
    for path in roots:
        if not path.exists():
            raise ValueError("Missing sync path: " + str(path))
    root = Path(os.path.commonpath([bundle, *roots]))
    required = set()

    def local(value):
        variables = configuration.get("variables", {})
        for _ in range(len(variables) + 1):
            resolved = value
            for name, definition in variables.items():
                if "default" in definition:
                    resolved = resolved.replace("${var." + name + "}", str(definition["default"]))
            if resolved == value:
                break
            value = resolved
        for prefix in ("${workspace.file_path}/", "${workspace.root_path}/files/"):
            if value.startswith(prefix):
                if "${" in value[len(prefix):]:
                    raise ValueError("Unresolved bundle asset path: " + value)
                path = root / value[len(prefix):]
                if not path.is_file() and path.with_suffix(".py").is_file():
                    path = path.with_suffix(".py")
                if not path.is_file() or not path.resolve().is_relative_to(root):
                    raise ValueError("Missing or external bundle asset: " + value)
                required.add(path.resolve())
                return
        raise ValueError("Unresolved bundle asset path: " + value)

    resources = configuration.get("resources", {})
    for job in resources.get("jobs", {}).values():
        for task in job.get("tasks", []):
            if "notebook_task" in task:
                local(task["notebook_task"]["notebook_path"])
    for pipeline in resources.get("pipelines", {}).values():
        for library in pipeline.get("libraries", []):
            for kind in ("file", "notebook"):
                if kind in library:
                    local(library[kind]["path"])
    if output is not None:
        required.update(path.resolve() for path in (output / "runtime").glob("*.py"))
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
    include = GitIgnoreSpec.from_lines(sync.get("include", []))
    exclude = GitIgnoreSpec.from_lines(sync.get("exclude", []))
    for path in required:
        relative = Path(os.path.relpath(path, bundle)).as_posix()
        if (not any(path.is_relative_to(folder) for folder in roots)
                or (_ignored(path, root) and not include.match_file(relative))
                or exclude.match_file(relative)):
            raise ValueError("Referenced asset excluded from bundle sync: " + path.relative_to(root).as_posix())
    return sorted(path.relative_to(root).as_posix() for path in required)


def _ignored(path: Path, root: Path):
    """Apply scoped .gitignore rules, including excluded parent directories."""
    ignored = False
    for folder in reversed([parent for parent in path.parents if parent.is_relative_to(root)]):
        rules = folder / ".gitignore"
        if not rules.is_file():
            continue
        spec = GitIgnoreSpec.from_lines(rules.read_text(encoding="utf-8").splitlines())
        for parent in path.parents:
            if parent != folder and parent.is_relative_to(folder):
                if spec.match_file(parent.relative_to(folder).as_posix() + "/"):
                    return True
        decision = spec.check_file(path.relative_to(folder).as_posix()).include
        if decision is not None:
            ignored = decision
    return ignored
