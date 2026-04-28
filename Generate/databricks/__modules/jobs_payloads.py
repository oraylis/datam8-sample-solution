from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from datam8.generate import BasePayload, IPayload
from datam8.model import EntityWrapper, Model
from datam8_model.model import ModelEntity
from datam8_model.zone import Zone

from payload_common import (
    ExternalSource,
    cluster_for_job,
    default_cluster_variable,
    get_external_source_wrappers,
    get_external_zone,
    get_model_backed_zones,
    get_model_entity_wrappers,
    get_zone_for_folder,
    job_property,
    schedule_for_job,
    task_key,
    zone_folder_name,
    zone_target_name,
)


def group_entities_by_zone_and_module(
    model: Model,
) -> dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]]:
    """Group model entities by zone folder, data product, and data module."""
    groups: dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in get_model_entity_wrappers(model):
        first_folder = wrapper.locator.folders[0] if wrapper.locator.folders else ""
        zone = get_zone_for_folder(model, first_folder) or model.get_zone_for_entity(wrapper)
        product = wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default"
        module = wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default"
        groups[(zone_folder_name(zone), product, module)].append(wrapper)
    return groups


def create_key(zone: EntityWrapper[Zone], *parts: str) -> str:
    """Create a Databricks create-job resource key."""
    suffix = "_".join(part for part in parts if part)
    zone_name = zone_target_name(zone)
    if suffix:
        return f"Create_{zone_name}_{suffix}"
    return f"Create_{zone_name}_tables"


def create_name(zone: EntityWrapper[Zone], *parts: str) -> str:
    """Create a human-readable Databricks create-job name."""
    suffix = " ".join(part for part in parts if part)
    zone_name = zone_target_name(zone)
    if suffix:
        return f"Create {zone_name} {suffix}"
    return f"Create {zone_name}"


def notebook_path(
    zone: EntityWrapper[Zone],
    kind: str,
    wrapper: EntityWrapper[ModelEntity],
    *,
    name: str | None = None,
) -> str:
    """Build the workspace-relative notebook path used by Databricks jobs."""
    notebook_name = name or wrapper.locator.entityName or wrapper.entity.name
    return Path(
        zone_folder_name(zone),
        kind,
        *wrapper.locator.folders[1:],
        notebook_name,
    ).as_posix()


def clusters(cluster_variable: str) -> list[dict[str, str]]:
    """Return the job cluster list expected by the job templates."""
    return [{"job_cluster_key": cluster_variable}] if cluster_variable else []


def create_module_job_payloads(model: Model) -> list[IPayload]:
    """Create one DDL job payload per zone/product/module group."""
    payloads: list[IPayload] = []
    default_cluster = default_cluster_variable(model)
    entities_by_zone_and_module = group_entities_by_zone_and_module(model)

    for (zone_folder, product, module), wrappers in entities_by_zone_and_module.items():
        zone = get_zone_for_folder(model, zone_folder)
        if zone is None:
            continue
        job_key = create_key(zone, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": create_name(zone, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": [
                        {
                            "task_key": task_key(
                                zone_target_name(zone),
                                product,
                                module,
                                wrapper.locator.entityName or wrapper.entity.name,
                            ).lower(),
                            "notebook_path": notebook_path(zone, "ddl", wrapper),
                        }
                        for wrapper in wrappers
                    ],
                },
                output_path=Path("jobs", zone_target_name(zone), product, module, f"{job_key}.yml"),
            )
        )

    external_zone = get_external_zone(model)
    external_groups: dict[
        tuple[str, str], list[tuple[EntityWrapper[ModelEntity], ExternalSource]]
    ] = defaultdict(list)
    for wrapper in get_external_source_wrappers(model):
        for item in wrapper.entity.sources or []:
            if not getattr(item, "dataSource", None):
                continue
            source = ExternalSource(model, wrapper, item)
            product = wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default"
            module = wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default"
            external_groups[(product, module)].append((wrapper, source))

    for (product, module), entries in external_groups.items():
        job_key = create_key(external_zone, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": create_name(external_zone, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": [
                        {
                            "task_key": task_key(
                                zone_target_name(external_zone),
                                product,
                                module,
                                source.table_name,
                            ).lower(),
                            "notebook_path": notebook_path(
                                external_zone, "ddl", wrapper, name=source.table_name
                            ),
                        }
                        for wrapper, source in entries
                    ],
                },
                output_path=Path(
                    "jobs", zone_target_name(external_zone), product, module, f"{job_key}.yml"
                ),
            )
        )
    return payloads


def create_zone_job_payloads(model: Model) -> list[IPayload]:
    """Create one DDL orchestration job payload per Databricks zone."""
    payloads: list[IPayload] = []
    entities_by_zone_and_module = group_entities_by_zone_and_module(model)

    for zone in [get_external_zone(model), *get_model_backed_zones(model)]:
        zone_folder = zone_folder_name(zone)
        module_jobs = [
            create_key(zone, product, module)
            for folder, product, module in entities_by_zone_and_module
            if folder == zone_folder
        ]

        if not zone.entity.localFolderName:
            module_jobs = sorted(
                {
                    create_key(
                        zone,
                        wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default",
                        wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default",
                    )
                    for wrapper in get_external_source_wrappers(model)
                    if any(getattr(source, "dataSource", None) for source in wrapper.entity.sources or [])
                }
            )

        payloads.append(
            BasePayload(
                data={
                    "job_key": create_key(zone),
                    "job_name": create_name(zone),
                    "tasks": [
                        {
                            "task_key": job_key,
                            "is_notebook_task": False,
                            "job_ref": job_key,
                            "depends_on": [],
                        }
                        for job_key in module_jobs
                    ],
                },
                output_path=Path("jobs", zone_target_name(zone), f"Create_{zone_target_name(zone)}.yml"),
            )
        )
    return payloads


def create_all_job_payloads(model: Model) -> list[IPayload]:
    """Create the top-level DDL orchestration job payload."""
    zone_jobs = [create_key(zone) for zone in [get_external_zone(model), *get_model_backed_zones(model)]]
    return [
        BasePayload(
            data={
                "job_key": "Create_All_Tables",
                "job_name": "Create All Tables",
                "tasks": [
                    {
                        "task_key": job_key,
                        "is_notebook_task": False,
                        "job_ref": job_key,
                        "depends_on": [],
                        "resolved_cluster_ref": None,
                        "resolved_cluster_var": None,
                    }
                    for job_key in zone_jobs
                ],
            },
            output_path=Path("jobs", "create_all_tables.yml"),
        )
    ]


def create_load_group_payloads(model: Model) -> list[IPayload]:
    """Create one load job payload per configured job property value."""
    grouped: dict[str, list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in get_model_entity_wrappers(model):
        grouped[job_property(wrapper, model)].append(wrapper)

    payloads: list[IPayload] = []
    for job_name, wrappers in grouped.items():
        cluster_variable = cluster_for_job(model, job_name)
        external_zone = get_external_zone(model)
        external_tasks: list[dict[str, Any]] = []
        entity_tasks: list[dict[str, Any]] = []
        complete_dependencies: list[str] = []

        for wrapper in wrappers:
            previous_tasks: list[str] = ["Start_Load"]
            for item in wrapper.entity.sources or []:
                if not getattr(item, "dataSource", None):
                    continue
                source = ExternalSource(model, wrapper, item)
                task = task_key(zone_target_name(external_zone), source.table_name, source.table_name).lower()
                external_tasks.append(
                    {
                        "task_key": task,
                        "depends_on": previous_tasks,
                        "notebook_path": notebook_path(
                            external_zone, "dml", wrapper, name=source.table_name
                        ),
                        "libraries": [],
                        "resolved_job_cluster_key": cluster_variable,
                    }
                )
                previous_tasks = [task]

            entity_task_key = task_key("load", *wrapper.locator.folders, wrapper.entity.name).lower()
            entity_tasks.append(
                {
                    "task_key": entity_task_key,
                    "depends_on": previous_tasks,
                    "notebook_path": notebook_path(
                        get_zone_for_folder(model, wrapper.locator.folders[0])
                        or model.get_zone_for_entity(wrapper),
                        "dml",
                        wrapper,
                    ),
                    "resolved_job_cluster_key": cluster_variable,
                }
            )
            complete_dependencies.append(entity_task_key)

        payloads.append(
            BasePayload(
                data={
                    "job_key": f"Load_{job_name}",
                    "job_name": f"Load {job_name}",
                    "job_clusters": clusters(cluster_variable),
                    "default_job_cluster_key": cluster_variable,
                    "schedule": schedule_for_job(model, job_name),
                    "external_tasks": external_tasks,
                    "entity_tasks": entity_tasks,
                    "complete_dependencies": complete_dependencies,
                },
                output_path=Path("jobs", f"load_{job_name}.yml"),
            )
        )
    return payloads


def create_load_all_payloads(model: Model) -> list[IPayload]:
    """Create the top-level load orchestration job payload."""
    job_names = sorted({job_property(wrapper, model) for wrapper in get_model_entity_wrappers(model)})
    return [
        BasePayload(
            data={
                "job_key": "Load_All_Tables",
                "job_name": "Load All Tables",
                "schedule": None,
                "tasks": [
                    {
                        "task_key": f"Load_{job_name}",
                        "job_ref": f"Load_{job_name}",
                        "depends_on": [],
                    }
                    for job_name in job_names
                ],
            },
            output_path=Path("jobs", "load_all_tables.yml"),
        )
    ]
