from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dm8gen.model import Model

from metadata_utils import MetadataResolver


def _safe_name(value: str, *, lower: bool = False) -> str:
    """
    Produce a filesystem-safe token by replacing non-alphanumeric characters with underscores.

    Args:
        value: Arbitrary input string.
        lower: When True, force the result to lowercase.

    Returns:
        A sanitized identifier suitable for task/job keys.
    """
    if not value:
        return "default"
    name = re.sub(r"[^A-Za-z0-9]+", "_", value)
    name = re.sub(r"_+", "_", name).strip("_")
    return name.lower() if lower else name


def _slug(value: str) -> str:
    """Shortcut to `_safe_name` that always returns lowercase tokens."""
    return _safe_name(value, lower=True)


def _zone_title(zone_name: str) -> str:
    """Convert a zone name such as `core_sales` into a human-friendly label."""
    if not zone_name:
        return "Zone"
    return zone_name.replace("_", " ").title()


@dataclass
class EntityJobInfo:
    """Aggregated metadata required to emit create/load tasks for a single entity."""

    entity_id: int
    locator: Any
    name: str
    display_name: str
    zone_name: str
    zone_folder: str
    zone_display: str
    product_dir: str
    product_display: str
    module_dirs: tuple[str, ...]
    module_display: str
    subfolders: tuple[str, ...]
    job_value: str | None
    job_config: dict[str, Any] | None
    ddl_notebook: str
    dml_notebook: str
    raw_sources: list[dict[str, Any]]
    dependencies: set[int]


@dataclass
class ModuleGroup:
    """
    Container holding all entities for a zone/product/module combination.

    The grouping allows downstream steps to create both module-level jobs and zone aggregates.
    """

    zone_name: str
    zone_folder: str
    zone_display: str
    product_dir: str
    product_display: str
    module_dirs: tuple[str, ...]
    module_display: str
    entities: list[EntityJobInfo] = field(default_factory=list)


class JobsPlanner:
    """
    Prepare job metadata (create/load) for the Databricks lake generator.

    The planner shapes raw model metadata into hierarchical structures (module, zone, global)
    that the payload layer later renders as YAML job definitions.
    """

    ZONE_ORDER = ["raw", "stage", "core", "curated"]

    def __init__(self, model: Model, resolver: MetadataResolver, *, modelled_zones: set[str]):
        """Initialise the planner with the DM8 model and metadata resolver."""
        self.model = model
        self.resolver = resolver
        self.modelled_zones = modelled_zones
        raw_zone = resolver.zone_by_name("raw")
        if raw_zone:
            self.raw_zone_folder = resolver.zone_folder_name(raw_zone)
            self.raw_zone_display = raw_zone.display_name or _zone_title(raw_zone.name)
        else:
            self.raw_zone_folder = "raw"
            self.raw_zone_display = _zone_title("raw")

    # ------------------------------------------------------------------ public
    def build(self) -> dict[str, Any]:
        """Return the complete create/load plan with module, zone, and orchestration jobs."""
        modules = self._group_modules()
        create_plan = self._build_create_plan(modules)
        load_plan = self._build_load_plan(modules)
        return {
            "create_all": create_plan.get("create_all"),
            "create_zones": create_plan.get("create_zones", []),
            "create_modules": create_plan.get("create_modules", []),
            "load_all": load_plan.get("load_all"),
            "load_jobs": load_plan.get("load_jobs", []),
        }

    # ----------------------------------------------------------- build helpers
    def _group_modules(self) -> dict[tuple[str, str, tuple[str, ...]], ModuleGroup]:
        """Bucket entities by zone/product/module to simplify downstream planning."""
        modules: dict[tuple[str, str, tuple[str, ...]], ModuleGroup] = {}
        for info in self._collect_entities():
            module_key = (info.zone_name, info.product_dir, info.module_dirs)
            module = modules.get(module_key)
            if module is None:
                module = ModuleGroup(
                    zone_name=info.zone_name,
                    zone_folder=info.zone_folder,
                    zone_display=info.zone_display,
                    product_dir=info.product_dir,
                    product_display=info.product_display,
                    module_dirs=info.module_dirs,
                    module_display=info.module_display,
                )
                modules[module_key] = module
            module.entities.append(info)
        return modules

    def _collect_entities(self) -> list[EntityJobInfo]:
        """Expand model entities and their raw sources into job-friendly descriptors."""
        entities: list[EntityJobInfo] = []
        seen_raw_tables: set[tuple[str, tuple[str, ...], str]] = set()
        raw_entity_counter = 10_000_000
        for locator, wrapper in self.model.modelEntities.items():
            if not locator.folders:
                continue

            zone_meta = self.resolver.zone_from_folder(locator.folders[0])
            if zone_meta is None or zone_meta.name not in self.modelled_zones:
                continue

            entity = wrapper.entity
            entity_id = getattr(entity, "id", None)
            if entity_id is None:
                continue

            zone_folder = self.resolver.zone_folder_name(zone_meta)
            zone_display = zone_meta.display_name or _zone_title(zone_meta.name)

            subfolders = tuple(locator.folders[1:])
            product_dir = subfolders[0] if subfolders else "General"
            product_info = (
                self.resolver.folder_info(tuple(locator.folders[:2]))
                if len(locator.folders) >= 2
                else None
            )
            product_display = product_info.name if product_info else product_dir

            module_dirs = subfolders[1:] if len(subfolders) > 1 else ()
            module_info = (
                self.resolver.folder_info(tuple(locator.folders[:3]))
                if len(locator.folders) >= 3
                else None
            )
            module_display = module_info.name if module_info else (module_dirs[-1] if module_dirs else "General")

            job_value = self.resolver.resolve_property(locator, wrapper.entity, "jobs")
            job_config = self.resolver.job_definition(job_value) if job_value else None

            ddl_notebook = self._notebook_path(zone_folder, "ddl", subfolders, f"{locator.entityName}.py")
            dml_notebook = self._notebook_path(zone_folder, "dml", subfolders, f"{locator.entityName}.py")
            raw_sources = self.resolver.raw_sources(locator, wrapper.entity)
            dependencies = set(self.resolver.entity_dependencies(locator, wrapper.entity))

            entities.append(
                EntityJobInfo(
                    entity_id=entity_id,
                    locator=locator,
                    name=entity.name,
                    display_name=entity.displayName or entity.name,
                    zone_name=zone_meta.name,
                    zone_folder=zone_folder,
                    zone_display=zone_display,
                    product_dir=product_dir,
                    product_display=product_display,
                    module_dirs=module_dirs,
                    module_display=module_display,
                    subfolders=subfolders,
                    job_value=job_value,
                    job_config=job_config,
                    ddl_notebook=ddl_notebook,
                    dml_notebook=dml_notebook,
                    raw_sources=raw_sources,
                    dependencies=dependencies,
                )
            )

            if not raw_sources or zone_meta.name == "raw":
                continue

            for index, raw_source in enumerate(raw_sources, start=1):
                raw_table_name = raw_source.get("table_name")
                if not raw_table_name:
                    continue
                raw_key = (product_dir, module_dirs, raw_table_name)
                if raw_key in seen_raw_tables:
                    continue
                seen_raw_tables.add(raw_key)
                raw_entity_counter += 1
                raw_display = raw_source.get("display_name") or raw_table_name
                entities.append(
                    EntityJobInfo(
                        entity_id=raw_entity_counter,
                        locator=locator,
                        name=raw_table_name,
                        display_name=raw_display,
                        zone_name="raw",
                        zone_folder=self.raw_zone_folder,
                        zone_display=self.raw_zone_display,
                        product_dir=product_dir,
                        product_display=product_display,
                        module_dirs=module_dirs,
                        module_display=module_display,
                        subfolders=subfolders,
                        job_value=None,
                        job_config=None,
                        ddl_notebook=self._notebook_path(
                            self.raw_zone_folder,
                            "ddl",
                            subfolders,
                            f"{raw_table_name}.py",
                        ),
                        dml_notebook=self._notebook_path(
                            self.raw_zone_folder,
                            "dml",
                            subfolders,
                            f"{raw_table_name}.py",
                        ),
                        raw_sources=[],
                        dependencies=set(),
                    )
                )
        return entities

    # -------------------------------------------------------------- create plan
    def _build_create_plan(self, modules: dict[tuple[str, str, tuple[str, ...]], ModuleGroup]) -> dict[str, Any]:
        """Derive module, zone, and orchestration create jobs for the generator."""
        zone_map: dict[str, list[ModuleGroup]] = defaultdict(list)
        for module in modules.values():
            zone_map[module.zone_name].append(module)

        create_modules: list[dict[str, Any]] = []
        create_zones: list[dict[str, Any]] = []

        for zone_name in self.ZONE_ORDER:
            zone_modules = zone_map.get(zone_name, [])
            if not zone_modules:
                continue

            zone_modules.sort(key=lambda module: (module.product_display.lower(), module.module_display.lower()))

            module_entries: list[tuple[ModuleGroup, str]] = []

            for module in zone_modules:
                job_key = self._module_job_key("Create", module.zone_name, module.product_dir, module.module_dirs)
                tasks = []
                entities = sorted(module.entities, key=lambda entity: entity.display_name.lower())
                for entity in entities:
                    tasks.append(
                        {
                            "task_key": self._task_key([entity.zone_name, entity.product_dir, *entity.module_dirs, entity.name]),
                            "notebook_path": entity.ddl_notebook,
                        }
                    )

                output_path = Path(
                    "jobs",
                    module.zone_folder.lower(),
                    module.product_dir,
                    *module.module_dirs,
                    f"{job_key}.yml",
                )

                create_modules.append(
                    {
                        "job_key": job_key,
                        "job_name": f"Create {module.zone_display} {module.module_display}",
                        "zone_name": module.zone_name,
                        "zone_title": _zone_title(module.zone_name),
                        "tasks": tasks,
                        "output_path": output_path,
                    }
                )
                module_entries.append((module, job_key))

            zone_job_key = self._job_key(["Create", zone_name, "tables"])
            zone_folder_dir = zone_modules[0].zone_folder.lower()
            zone_output_path = Path("jobs", zone_folder_dir, f"Create_{_slug(zone_name)}.yml")

            zone_tasks: list[dict[str, Any]] = []
            previous_task: str | None = None
            for _, module_job_key in module_entries:
                depends_on = [previous_task] if previous_task else []
                zone_tasks.append(
                    {
                        "task_key": module_job_key,
                        "job_ref": module_job_key,
                        "depends_on": depends_on,
                    }
                )
                previous_task = module_job_key

            create_zones.append(
                {
                    "job_key": zone_job_key,
                    "job_name": f"Create {zone_name.title()} Tables",
                    "zone_name": zone_name,
                    "zone_modules": zone_modules,
                    "tasks": zone_tasks,
                    "output_path": zone_output_path,
                }
            )

        create_all = None
        if create_zones:
            tasks = []
            previous = None
            for zone_job in create_zones:
                task = {
                    "task_key": zone_job["job_key"],
                    "job_ref": zone_job["job_key"],
                    "depends_on": [previous] if previous else [],
                }
                tasks.append(task)
                previous = zone_job["job_key"]

            create_all = {
                "job_key": "Create_All_Tables",
                "job_name": "Create All Tables",
                "tasks": tasks,
                "output_path": Path("jobs", "create_all_tables.yml"),
            }

        return {
            "create_all": create_all,
            "create_zones": create_zones,
            "create_modules": create_modules,
        }

    # --------------------------------------------------------------- load plan
    def _build_load_plan(self, modules: dict[tuple[str, str, tuple[str, ...]], ModuleGroup]) -> dict[str, Any]:
        """Create load jobs per job value and a chained orchestration job."""
        job_groups: dict[str, dict[str, Any]] = {}

        for module in modules.values():
            for entity in module.entities:
                if not entity.job_value:
                    continue
                group = job_groups.setdefault(
                    entity.job_value,
                    {"job_value": entity.job_value, "job_config": entity.job_config, "entities": []},
                )
                group["entities"].append(entity)

        load_jobs: list[dict[str, Any]] = []

        for job_value in sorted(job_groups):
            group = job_groups[job_value]
            entities = group.get("entities", [])
            if not entities:
                continue

            job_config = group.get("job_config") or self.resolver.job_definition(job_value) or {}
            job_display = job_config.get("display_name", job_value)
            cluster_var = f"cluster_id_{_slug(job_value)}"
            schedule_info = job_config.get("schedule") or {}
            cron_expression = self._format_cron(schedule_info.get("cron"))

            job = self._build_load_job(
                job_value=job_value,
                job_display=job_display,
                entities=entities,
                cluster_var=cluster_var,
            )
            if not job:
                continue

            job["schedule"] = (
                {"cron_expression": cron_expression, "timezone_id": 'Europe/Amsterdam'}
                if cron_expression
                else None
            )
            job["output_path"] = Path("jobs", f"load_{_slug(job_value)}.yml")
            load_jobs.append(job)

        load_all = None
        if load_jobs:
            tasks = []
            previous = None
            for job in load_jobs:
                task_key = job["job_key"]
                tasks.append(
                    {
                        "task_key": task_key,
                        "job_ref": task_key,
                        "depends_on": [previous] if previous else [],
                    }
                )
                previous = task_key

            cron_expression = next(
                (job["schedule"]["cron_expression"] for job in load_jobs if job.get("schedule")),
                None,
            )

            load_all = {
                "job_key": "Load_All_Tables",
                "job_name": "Load All Tables",
                "schedule": (
                    {"cron_expression": cron_expression, "timezone_id": 'Europe/Amsterdam'}
                    if cron_expression
                    else None
                ),
                "output_path": Path("jobs", "load_all_tables.yml"),
                "tasks": tasks,
            }

        return {
            "load_all": load_all,
            "load_jobs": load_jobs,
        }

    def _build_load_job(
        self,
        *,
        job_value: str,
        job_display: str,
        entities: list[EntityJobInfo],
        cluster_var: str,
    ) -> dict[str, Any] | None:
        """Build the task graph for a specific job value, including raw prerequisites."""
        entity_task_keys: dict[int, str] = {}
        for entity in entities:
            key_parts = [
                entity.zone_name,
                entity.product_dir,
                *entity.module_dirs,
                entity.name,
            ]
            entity_task_keys[entity.entity_id] = self._task_key(key_parts)

        raw_tasks: list[dict[str, Any]] = []
        raw_task_lookup: dict[int, list[str]] = defaultdict(list)
        seen_raw_keys: set[str] = set()

        for entity in entities:
            if entity.zone_name != "stage":
                continue
            for raw_source in sorted(entity.raw_sources, key=lambda src: (src.get("table_name") or entity.name).lower()):
                table_name = raw_source.get("table_name") or entity.name
                raw_key = self._task_key(["raw", entity.name, table_name])
                if raw_key in seen_raw_keys:
                    raw_task_lookup[entity.entity_id].append(raw_key)
                    continue
                seen_raw_keys.add(raw_key)
                raw_tasks.append(
                    {
                        "task_key": raw_key,
                        "notebook_path": self._raw_notebook_path(entity, table_name),
                        "depends_on": ["Generate_Load_UUID"],
                    }
                )
                raw_task_lookup[entity.entity_id].append(raw_key)

        ordered_entities = self._topological_sort(entities)

        entity_tasks: list[dict[str, Any]] = []
        complete_dependencies: list[str] = []

        for entity in ordered_entities:
            task_key = entity_task_keys[entity.entity_id]
            dependency_keys = [
                entity_task_keys[dep]
                for dep in sorted(entity.dependencies)
                if dep in entity_task_keys
            ]
            depends_on = self._unique(
                ["Generate_Load_UUID", *raw_task_lookup.get(entity.entity_id, []), *dependency_keys]
            )

            entity_tasks.append(
                {
                    "task_key": task_key,
                    "notebook_path": entity.dml_notebook,
                    "depends_on": depends_on,
                }
            )
            complete_dependencies.append(task_key)

        if not (entity_tasks or raw_tasks):
            return None

        return {
            "job_key": self._job_key(["Load", job_value]),
            "job_name": f"Load {job_display}",
            "job_value": job_value,
            "cluster_var": cluster_var,
            "raw_tasks": raw_tasks,
            "entity_tasks": entity_tasks,
            "complete_dependencies": complete_dependencies,
        }

    # --------------------------------------------------------------- utilities
    def _notebook_path(self, zone_folder: str, category: str, subfolders: tuple[str, ...], name: str) -> str:
        """Return the workspace-relative path for an entity notebook (without the workspace prefix)."""
        stem = Path(name).stem if name else ""
        parts = [zone_folder, category, *subfolders, stem]
        return "/".join(part for part in parts if part)

    def _raw_notebook_path(self, entity: EntityJobInfo, table_name: str) -> str:
        """Return the relative path for a raw ingestion notebook."""
        stem = Path(table_name).stem if table_name else ""
        parts = [self.raw_zone_folder, "dml", *entity.subfolders, stem]
        return "/".join(part for part in parts if part)

    def _job_key(self, parts: list[str]) -> str:
        """Compose a deterministic job key from the provided fragments."""
        return "_".join(_safe_name(part) for part in parts if part)

    def _module_job_key(
        self,
        prefix: str,
        zone_name: str,
        product_dir: str,
        module_dirs: tuple[str, ...],
        job_value: str | None = None,
    ) -> str:
        """Return a modular job key including zone/product/module identifiers."""
        parts = [prefix]
        if job_value:
            parts.append(job_value)
        parts.append(zone_name)
        parts.append(product_dir)
        if module_dirs:
            parts.extend(module_dirs)
        else:
            parts.append("General")
        return self._job_key(parts)

    def _task_key(self, parts: list[str]) -> str:
        """Compute a unique task key derived from meaningful path fragments."""
        tokens = [_slug(part) for part in parts if part]
        return "_".join(tokens) if tokens else "task"

    def _format_cron(self, cron_value: Any) -> str | None:
        """Translate a two-part cron expression into Quartz format when needed."""
        if not cron_value:
            return None
        cron = str(cron_value).strip()
        if not cron:
            return None
        parts = cron.split()
        if len(parts) == 2:
            minute, hour = parts
            return f"0 {minute} {hour} * * ?"
        return cron

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        """Return the values without duplicates while preserving encounter order."""
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _topological_sort(self, entities: list[EntityJobInfo]) -> list[EntityJobInfo]:
        """Order entities so dependencies run first; fall back to alphabetical order if cyclic."""
        if len(entities) <= 1:
            return entities

        entity_map = {entity.entity_id: entity for entity in entities}
        indegree = {entity.entity_id: 0 for entity in entities}
        adjacency = {entity.entity_id: set() for entity in entities}

        for entity in entities:
            for dep in entity.dependencies:
                if dep in adjacency:
                    adjacency[dep].add(entity.entity_id)
                    indegree[entity.entity_id] += 1

        ready = [entity_map[eid] for eid, degree in indegree.items() if degree == 0]
        ready.sort(key=lambda entity: (entity.zone_name, entity.display_name.lower()))

        ordered: list[EntityJobInfo] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            neighbours = sorted(
                adjacency[current.entity_id],
                key=lambda eid: (entity_map[eid].zone_name, entity_map[eid].display_name.lower()),
            )
            for neighbour in neighbours:
                indegree[neighbour] -= 1
                if indegree[neighbour] == 0:
                    ready.append(entity_map[neighbour])
                    ready.sort(key=lambda item: (item.zone_name, item.display_name.lower()))

        if len(ordered) != len(entities):
            return sorted(entities, key=lambda entity: (entity.zone_name, entity.display_name.lower()))
        return ordered
