from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from datam8.generate import BasePayload
from datam8.model import EntityWrapper, Model
from datam8_model.model import ModelEntity
from datam8_model.property import PropertyReference
from datam8_model.zone import Zone

TARGET = "databricks"


def create_resource_slug_from_name(name: str) -> str:
    """Return a Databricks resource-safe slug for a display name."""
    resource_slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if len(resource_slug) == 0:
        return "default"
    return resource_slug


def task_key(*parts: str) -> str:
    """Create a stable Databricks task key from readable name parts."""
    value = "_".join(part for part in parts if part)
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "task"


def zone_target_name(zone: EntityWrapper[Zone]) -> str:
    """Return the schema name used for a Databricks zone."""
    return zone.entity.targetName or zone.entity.name


def zone_folder_name(zone: EntityWrapper[Zone]) -> str:
    """Return the output folder name used for notebooks in a zone."""
    return zone.entity.localFolderName or zone.entity.targetName or zone.entity.name


def zone_display_name(zone: EntityWrapper[Zone]) -> str:
    """Return the human-readable zone name."""
    return zone.entity.displayName


def zone_targets_databricks(zone: EntityWrapper[Zone]) -> bool:
    """Check whether a zone is configured for the Databricks target."""
    return any(ref.property == "target" and ref.value == TARGET for ref in zone.entity.properties or [])


def get_model_backed_zones(model: Model) -> list[EntityWrapper[Zone]]:
    """Return Databricks zones that have a folder in the model tree."""
    return [
        zone
        for zone in model.zones.values()
        if zone_targets_databricks(zone) and zone.entity.localFolderName
    ]


def get_external_zone(model: Model) -> EntityWrapper[Zone]:
    """Return the Databricks zone used for extracted external source tables."""
    for zone in model.zones.values():
        if zone_targets_databricks(zone) and not zone.entity.localFolderName:
            return zone
    raise ValueError(
        "No external Databricks zone found. Configure a Databricks zone without localFolderName."
    )


def get_zone_for_folder(model: Model, folder: str) -> EntityWrapper[Zone] | None:
    """Find the Databricks zone that owns a top-level model folder."""
    for zone in model.zones.values():
        if zone.entity.localFolderName == folder and zone_targets_databricks(zone):
            return zone
    return None


def _locator_path(locator: Any) -> str:
    """Convert a DataM8 locator to a simple slash-separated path."""
    folders = list(getattr(locator, "folders", []) or [])
    entity_name = getattr(locator, "entityName", None)
    return "/".join([*folders, entity_name] if entity_name else folders)


def get_many(collection: Any, locator_prefix: str) -> list[Any]:
    """Return wrappers below a locator prefix for both collection APIs and dicts."""
    if hasattr(collection, "get_many"):
        return collection.get_many(locator_prefix)

    prefix = locator_prefix.strip("/")
    return [
        wrapper
        for locator, wrapper in collection.items()
        if _locator_path(locator).startswith(prefix)
    ]


def get_one(collection: Any, locator_path: str) -> Any:
    """Return one wrapper by locator path for both collection APIs and dicts."""
    if hasattr(collection, "get"):
        wrapper = collection.get(locator_path)
        if wrapper is not None:
            return wrapper

    path = locator_path.strip("/")
    for locator, wrapper in collection.items():
        if _locator_path(locator) == path:
            return wrapper
    raise KeyError(locator_path)


def get_model_entity_by_id(model: Model, entity_id: Any) -> EntityWrapper[ModelEntity]:
    """Find a model entity by id without depending on a specific collection implementation."""
    if hasattr(model.modelEntities, "get_by_id"):
        return model.modelEntities.get_by_id(entity_id)

    for wrapper in model.modelEntities.values():
        if getattr(wrapper.entity, "id", None) == entity_id:
            return wrapper
    raise KeyError(entity_id)


def get_property_refs(
    model: Model, wrapper: EntityWrapper[ModelEntity]
) -> list[PropertyReference]:
    """Return entity properties plus inherited folder properties."""
    refs = list(wrapper.entity.properties or [])
    folders = list(wrapper.locator.folders)
    for index in range(len(folders), 0, -1):
        try:
            folder = get_one(model.folders, "/".join(folders[:index]))
        except KeyError:
            continue
        refs.extend(folder.entity.properties or [])
    return refs


def get_model_entity_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    """Return all model entities below Databricks model-backed zones."""
    wrappers: list[EntityWrapper[ModelEntity]] = []
    for zone in get_model_backed_zones(model):
        wrappers.extend(get_many(model.modelEntities, f"{zone.entity.localFolderName}/"))
    return wrappers


def get_external_source_zone(model: Model) -> EntityWrapper[Zone]:
    """Return the model-backed zone used to discover external sources."""
    zones = get_model_backed_zones(model)
    if not zones:
        raise ValueError("No model-backed Databricks zone found for external source discovery.")
    return zones[0]


def get_external_source_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    """Return wrappers that may contain external source definitions."""
    # External extraction notebooks are generated from the first model-backed source zone.
    source_zone = get_external_source_zone(model)
    return get_many(model.modelEntities, f"{source_zone.entity.localFolderName}/")


def property_values_by_name(refs: Iterable[PropertyReference] | None, property_name: str) -> list[str]:
    """Collect property reference values for a property name."""
    return [ref.value for ref in refs or [] if ref.property == property_name]


def collect_transformations(wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
    """Read transformation script metadata and file content for one entity."""
    transformations: list[dict[str, Any]] = []
    frequency = next(
        (ref.value for ref in wrapper.entity.properties or [] if ref.property == "frequency"),
        "no_restriction",
    )
    for transform in wrapper.entity.transformations or []:
        function = getattr(transform, "function", None)
        script_name = getattr(function, "source", None) if function is not None else None
        if not script_name:
            continue
        script_stem = Path(script_name).stem
        script_path = wrapper.source_file.parent / wrapper.entity.name / script_name
        if not script_path.exists():
            script_path = wrapper.source_file.parent / script_name
        transformations.append(
            {
                "key": script_stem,
                "name": transform.name,
                "merge_type": "replace",
                "frequency": frequency,
                "sources": [],
                "script_name": script_name,
                "script_module": f"{wrapper.entity.name}_functions/{script_stem}",
                "script_content": script_path.read_text(encoding="utf-8"),
            }
        )
    return transformations


def default_cluster_variable(model: Model) -> str:
    """Return the Databricks variable name for the default job cluster."""
    for pv in get_many(model.propertyValues, "cluster/"):
        if pv.entity.default:
            return f"cluster_{create_resource_slug_from_name(pv.entity.name)}"
    clusters = get_many(model.propertyValues, "cluster/")
    return f"cluster_{create_resource_slug_from_name(clusters[0].entity.name)}" if clusters else ""


def job_property(wrapper: EntityWrapper[Any], model: Model | None = None) -> str:
    """Return the load job name assigned to an entity."""
    if model is not None:
        refs = get_property_refs(model, wrapper)
    else:
        refs = list(wrapper.entity.properties or [])
    return next((ref.value for ref in refs if ref.property == "jobs"), "daily")


def schedule_for_job(model: Model, job_name: str) -> dict[str, str] | None:
    """Return the Databricks schedule dictionary for a job property value."""
    job = get_one(model.propertyValues, f"jobs/{job_name}").entity
    schedules = property_values_by_name(job.properties, "schedules")
    if not schedules:
        return None
    schedule = get_one(model.propertyValues, f"schedules/{schedules[0]}").entity
    return {
        "cron_expression": getattr(schedule, "quartz_cron_expression", "49 0 1 * * ?"),
        "timezone_id": "UTC",
    }


def cluster_for_job(model: Model, job_name: str) -> str:
    """Return the cluster variable configured for a job property value."""
    job = get_one(model.propertyValues, f"jobs/{job_name}").entity
    clusters = property_values_by_name(job.properties, "cluster")
    if clusters:
        return f"cluster_{create_resource_slug_from_name(clusters[0])}"
    return default_cluster_variable(model)


class ModelEntityPayload(BasePayload):
    """Base payload for templates that render one model entity."""

    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        self.wrapper = wrapper
        self.model = model
        self.entity = wrapper.entity
        first_folder = wrapper.locator.folders[0] if wrapper.locator.folders else ""
        # Databricks notebook folders follow the model's first folder, not only the target property.
        self.zone_wrapper = get_zone_for_folder(model, first_folder) or model.get_zone_for_entity(wrapper)

    def get_data(self) -> object:
        return self

    @property
    def zone_name(self) -> str:
        return zone_target_name(self.zone_wrapper)

    @property
    def zone(self) -> str:
        return self.zone_name

    @property
    def zone_display(self) -> str:
        return zone_display_name(self.zone_wrapper)

    @property
    def data_product(self) -> str:
        return self.wrapper.locator.folders[1] if len(self.wrapper.locator.folders) > 1 else "default"

    @property
    def data_module(self) -> str:
        return self.wrapper.locator.folders[2] if len(self.wrapper.locator.folders) > 2 else "default"

    @property
    def table_name(self) -> str:
        return self.entity.name

    @property
    def full_table_name(self) -> str:
        return "_".join([*self.wrapper.locator.folders[1:], self.table_name])

    def wrapper_property(self, property_name: str, default: str | None = None) -> str | None:
        return next(
            (ref.value for ref in get_property_refs(self.model, self.wrapper) if ref.property == property_name),
            default,
        )

    @property
    def surrogate_key_columns(self) -> list[str]:
        return [
            attr.name
            for attr in self.entity.attributes
            if any(
                ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
                for ref in attr.properties or []
            )
        ]
