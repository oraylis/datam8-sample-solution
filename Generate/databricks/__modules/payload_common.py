from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from datam8.generate import BasePayload
from datam8.model import EntityWrapper, Model
from datam8_model.model import ExternalModelSource, ModelEntity
from datam8_model.property import PropertyReference
from datam8_model.zone import Zone

TARGET = "databricks"


def create_resource_slug_from_name(name: str) -> str:
    """Convert any readable name into a safe technical Databricks resource name.

    Beginners can think of this as turning labels such as "Daily Load" into
    stable identifiers such as "daily_load" that Databricks YAML can use.
    """
    resource_slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if len(resource_slug) == 0:
        return "default"
    return resource_slug


def task_key(*parts: str) -> str:
    """Build one Databricks task key from several readable name parts.

    A task key is the technical name Databricks uses when one job task depends
    on another one.
    """
    value = "_".join(part for part in parts if part)
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "task"


def zone_target_name(zone: EntityWrapper[Zone]) -> str:
    """Return the Databricks schema name for a zone.

    If the zone has an explicit target name, that name wins. Otherwise the
    regular zone name is used.
    """
    return zone.entity.targetName or zone.entity.name


def zone_folder_name(zone: EntityWrapper[Zone]) -> str:
    """Return the folder name where generated notebooks for this zone are saved."""
    return zone.entity.localFolderName or zone.entity.targetName or zone.entity.name


def zone_display_name(zone: EntityWrapper[Zone]) -> str:
    """Return the human-readable name shown in comments or labels."""
    return zone.entity.displayName


def zone_targets_databricks(zone: EntityWrapper[Zone]) -> bool:
    """Check whether this zone should produce Databricks artifacts."""
    return any(ref.property == "target" and ref.value == TARGET for ref in zone.entity.properties or [])


def get_model_backed_zones(model: Model) -> list[EntityWrapper[Zone]]:
    """Return Databricks zones that are backed by folders in the model tree.

    These zones produce the normal modeled DDL and DML notebooks.
    """
    return [
        zone
        for zone in model.zones.values()
        if zone_targets_databricks(zone) and zone.entity.localFolderName
    ]


def get_external_zone(model: Model) -> EntityWrapper[Zone]:
    """Return the Databricks zone used for raw tables extracted from external systems."""
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
    """Convert a DataM8 locator object into a simple slash-separated path."""
    folders = list(getattr(locator, "folders", []) or [])
    entity_name = getattr(locator, "entityName", None)
    return "/".join([*folders, entity_name] if entity_name else folders)


def get_many(collection: Any, locator_prefix: str) -> list[Any]:
    """Return all wrappers below a locator prefix.

    DataM8 collections and plain dictionaries expose slightly different APIs.
    This helper hides that difference from the rest of the generator.
    """
    if hasattr(collection, "get_many"):
        return collection.get_many(locator_prefix)

    prefix = locator_prefix.strip("/")
    return [
        wrapper
        for locator, wrapper in collection.items()
        if _locator_path(locator).startswith(prefix)
    ]


def get_one(collection: Any, locator_path: str) -> Any:
    """Return exactly one wrapper by locator path.

    The helper works with both DataM8 collections and fallback dictionaries.
    """
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
    """Find one model entity by id without relying on one collection implementation."""
    if hasattr(model.modelEntities, "get_by_id"):
        return model.modelEntities.get_by_id(entity_id)

    for wrapper in model.modelEntities.values():
        if getattr(wrapper.entity, "id", None) == entity_id:
            return wrapper
    raise KeyError(entity_id)


def get_property_refs(
    model: Model, wrapper: EntityWrapper[ModelEntity]
) -> list[PropertyReference]:
    """Return properties directly on an entity plus properties inherited from folders."""
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
    """Return all model entities that belong to Databricks model-backed zones."""
    wrappers: list[EntityWrapper[ModelEntity]] = []
    for zone in get_model_backed_zones(model):
        wrappers.extend(get_many(model.modelEntities, f"{zone.entity.localFolderName}/"))
    return wrappers


def get_first_model_backed_zone_for_external_sources(model: Model) -> EntityWrapper[Zone]:
    """Return the first model-backed Databricks zone used to discover external sources."""
    # External source extraction is currently discovered from the first Databricks model-backed
    # zone. If multiple source zones become valid later, replace this with explicit filtering.
    zones = get_model_backed_zones(model)
    if not zones:
        raise ValueError("No model-backed Databricks zone found for external source discovery.")
    return zones[0]


def get_external_source_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    """Return model entities that may define external source extractions."""
    source_zone = get_first_model_backed_zone_for_external_sources(model)
    return get_many(model.modelEntities, f"{source_zone.entity.localFolderName}/")


def property_values_by_name(refs: Iterable[PropertyReference] | None, property_name: str) -> list[str]:
    """Collect all values for one property name from a list of property references."""
    return [ref.value for ref in refs or [] if ref.property == property_name]


def collect_transformations(wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
    """Read transformation script metadata and Python file content for one entity.

    The DML notebook imports these generated function files later, so the
    payload needs both the script name and the script text.
    """
    transformations: list[dict[str, Any]] = []
    # Keep wrapper-level property resolution for frequency to preserve previous behavior.
    try:
        frequency = next(
            (pv.name for pv in wrapper.properties.values() if pv.property == "frequency"),
            "no_restriction",
        )
    except Exception:
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
    """Return the Databricks Asset Bundle variable name for the default job cluster."""
    for pv in get_many(model.propertyValues, "cluster/"):
        if pv.entity.default:
            return f"cluster_{create_resource_slug_from_name(pv.entity.name)}"
    return ""


def job_property(wrapper: EntityWrapper[Any], model: Model | None = None) -> str:
    """Return the load job group assigned to an entity.

    When no `jobs` property exists, the entity is assigned to the `daily` job.
    """
    if model is not None:
        refs = get_property_refs(model, wrapper)
    else:
        refs = list(wrapper.entity.properties or [])
    return next((ref.value for ref in refs if ref.property == "jobs"), "daily")


def schedule_for_job(model: Model, job_name: str) -> dict[str, str] | None:
    """Return the Databricks schedule for one load job, or `None` for manual jobs."""
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
    """Return the Databricks cluster variable configured for one load job."""
    job = get_one(model.propertyValues, f"jobs/{job_name}").entity
    clusters = property_values_by_name(job.properties, "cluster")
    if clusters:
        return f"cluster_{create_resource_slug_from_name(clusters[0])}"
    return default_cluster_variable(model)


class ModelEntityPayload(BasePayload):
    """Base payload for templates that render one model entity.

    This class stores the wrapped model entity and exposes common values such
    as zone, data product, module, and table names. Other payload classes inherit
    from it so templates can use a consistent vocabulary.
    """

    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        """Store the entity wrapper and resolve the Databricks zone for it."""
        self.wrapper = wrapper
        self.model = model
        self.entity = wrapper.entity
        first_folder = wrapper.locator.folders[0] if wrapper.locator.folders else ""
        # Databricks notebook folders follow the model's first folder, not only the target property.
        self.zone_wrapper = get_zone_for_folder(model, first_folder) or model.get_zone_for_entity(wrapper)

    def get_data(self) -> object:
        """Return this object as the template data object."""
        return self

    @property
    def zone_name(self) -> str:
        """Return the Databricks schema name for this entity."""
        return zone_target_name(self.zone_wrapper)

    @property
    def zone(self) -> str:
        """Return the Databricks schema name using the template's legacy field name."""
        return self.zone_name

    @property
    def zone_display(self) -> str:
        """Return the readable zone name."""
        return zone_display_name(self.zone_wrapper)

    @property
    def data_product(self) -> str:
        """Return the data product folder name, or `default` when it is missing."""
        return self.wrapper.locator.folders[1] if len(self.wrapper.locator.folders) > 1 else "default"

    @property
    def data_module(self) -> str:
        """Return the data module folder name, or `default` when it is missing."""
        return self.wrapper.locator.folders[2] if len(self.wrapper.locator.folders) > 2 else "default"

    @property
    def table_name(self) -> str:
        """Return the model entity name used as the table name."""
        return self.entity.name

    @property
    def full_table_name(self) -> str:
        """Return the generated table name including product and module prefixes."""
        return "_".join([*self.wrapper.locator.folders[1:], self.table_name])

    def wrapper_property(self, property_name: str, default: str | None = None) -> str | None:
        """Read one resolved property value from the entity or its folders."""
        return next(
            (ref.value for ref in get_property_refs(self.model, self.wrapper) if ref.property == property_name),
            default,
        )

    @property
    def surrogate_key_columns(self) -> list[str]:
        """Return attributes marked as surrogate keys by `attribute_type=sk`."""
        return [
            attr.name
            for attr in self.entity.attributes
            if any(
                ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
                for ref in attr.properties or []
            )
        ]


class ExternalSource:
    """Template-facing view of one external source definition.

    An external source is a table, query, or object outside the modeled
    Databricks layers. This wrapper translates source metadata into names,
    mappings, filters, and select expressions that templates can render.
    """

    def __init__(
        self,
        model: Model,
        wrapper: EntityWrapper[ModelEntity],
        source: ExternalModelSource,
    ) -> None:
        """Store source metadata and resolve the configured DataM8 data source."""
        self.model = model
        self.wrapper = wrapper
        self.source = source
        self.source_zone = zone_target_name(get_external_zone(model))
        self.data_source_entry = get_one(model.dataSources, source.dataSource).entity

    @property
    def table_name(self) -> str:
        """Return the landing table name for this external source."""
        return self.source.sourceAlias or self.wrapper.entity.name

    @property
    def full_table_name(self) -> str:
        """Return the full landing table name including product and module prefixes."""
        return "_".join([self.data_product, self.data_module, self.table_name])

    @property
    def key(self) -> str:
        """Return a stable task key for this external source."""
        return task_key(self.source_zone, self.full_table_name)

    @property
    def external_table(self) -> str:
        """Return the short external table name expected by older templates."""
        return self.table_name

    @property
    def external_full_table(self) -> str:
        """Return the full external table name expected by older templates."""
        return self.full_table_name

    @property
    def source_full_table_name(self) -> str:
        """Return the full source table name used in source-aware templates."""
        return self.full_table_name

    @property
    def display_name(self) -> str:
        """Return a readable name for job tasks and comments."""
        return self.external_full_table

    @property
    def data_product(self) -> str:
        """Return the data product folder name for the owning entity."""
        return self.wrapper.locator.folders[1] if len(self.wrapper.locator.folders) > 1 else "default"

    @property
    def data_module(self) -> str:
        """Return the data module folder name for the owning entity."""
        return self.wrapper.locator.folders[2] if len(self.wrapper.locator.folders) > 2 else "default"

    @property
    def data_source(self) -> str:
        """Return the configured DataM8 data source key."""
        return self.source.dataSource

    @property
    def data_source_display(self) -> str:
        """Return the readable data source name."""
        return self.data_source_entry.displayName or self.data_source

    @property
    def data_source_type(self) -> str:
        """Return the configured data source type key."""
        return self.data_source_entry.type

    @property
    def data_source_extended_properties(self) -> dict[str, Any]:
        """Return custom data source settings from the metadata model."""
        return self.data_source_entry.extendedProperties or {}

    @property
    def source_alias(self) -> str:
        """Return the source alias, falling back to the landing table name."""
        return self.source.sourceAlias or self.table_name

    @property
    def source_name(self) -> str:
        """Return the source name used by extraction templates."""
        return self.source.sourceAlias or self.table_name

    @property
    def source_location(self) -> str:
        """Return the physical source location, falling back to the table name."""
        return self.source.sourceLocation or self.table_name

    @property
    def target_max_filter(self) -> str | None:
        """Return a filter for target max-value lookups; external sources do not need one."""
        return None

    @property
    def source_delta_column(self) -> str:
        """Return the technical source timestamp used for external delta tracking."""
        return "__InsertTimestampUTC"

    @property
    def properties(self) -> dict[str, str]:
        """Return external source properties as a simple name-to-value dictionary."""
        return {ref.property: ref.value for ref in self.source.properties or []}

    @property
    def extract_mode(self) -> str | None:
        """Return the configured extraction mode, such as `delta` or `overwrite`."""
        return self.properties.get("extract_mode")

    @property
    def mapping(self) -> list[Any] | None:
        """Return the raw source-to-target mapping entries from the model."""
        return self.source.mapping

    @property
    def mapping_entries(self) -> list[Any]:
        """Return source-to-target mapping entries as a list."""
        return list(self.source.mapping or [])

    @property
    def type_mappings(self) -> dict[str, str]:
        """Return source-type to Databricks-type mappings for this data source."""
        data_source_type = get_one(self.model.dataSourceTypes, self.data_source_entry.type).entity
        mappings = {m.sourceType: m.targetType for m in data_source_type.dataTypeMapping or []}
        mappings.update({m.sourceType: m.targetType for m in self.data_source_entry.dataTypeMapping or []})
        return mappings

    @property
    def select_columns(self) -> list[str]:
        """Return SQL select expressions for mapped business columns."""
        columns: list[str] = []
        mappings_by_target = {mapping.targetName: mapping for mapping in self.mapping_entries}
        for attr in self.wrapper.entity.attributes:
            if expr := (getattr(attr, "calculation", None) or getattr(attr, "expression", None)):
                columns.append(f"{expr} AS `{attr.name}`")
                continue
            mapping = mappings_by_target.get(attr.name)
            if mapping is not None:
                target_type = self._target_databricks_type(attr)
                columns.append(
                    f"try_cast(`{mapping.targetName}` as {target_type}) AS `{attr.name}`"
                )
        return columns

    def _target_databricks_type(self, attr: Any) -> str:
        """Resolve the Databricks target type for one model attribute."""
        attr_type = getattr(getattr(attr, "dataType", None), "type", None)
        if not attr_type:
            return "string"
        for data_type in self.model.dataTypes.values():
            if data_type.entity.name == attr_type:
                return data_type.entity.targets.get(TARGET, attr_type)
        return str(attr_type)

    @property
    def target_columns(self) -> list[str]:
        """Return target business column names that the extract writes."""
        columns: list[str] = []
        mappings_by_target = {mapping.targetName: mapping for mapping in self.mapping_entries}
        for attr in self.wrapper.entity.attributes:
            if getattr(attr, "calculation", None) or getattr(attr, "expression", None):
                columns.append(attr.name)
                continue
            mapping = mappings_by_target.get(attr.name)
            if mapping is not None:
                columns.append(mapping.targetName)
        return columns

    @property
    def column_renames(self) -> list[dict[str, str]]:
        """Return mappings where the source and target column names differ."""
        return [
            {"source": mapping.sourceName, "target": mapping.targetName}
            for mapping in self.mapping_entries
            if mapping.sourceName != mapping.targetName
        ]

    @property
    def delta_column_details(self) -> list[dict[str, str]]:
        """Return details for mapped columns marked as delta extraction columns."""
        details: list[dict[str, str]] = []
        for mapping in self.mapping_entries:
            props = {ref.property: ref.value for ref in mapping.properties or []}
            if props.get("extract_mode") != "delta":
                continue
            data_type = mapping.sourceDataType.type if mapping.sourceDataType else ""
            details.append(
                {
                    "source": mapping.sourceName,
                    "target": mapping.targetName,
                    "type": self.type_mappings.get(data_type, data_type),
                }
            )
        return details

    @property
    def select_expressions(self) -> list[str]:
        """Return business select list; technical columns are added in template."""
        return [*self.select_columns]


class InternalSource:
    """Template-facing view of one internal source definition.

    An internal source points to another model entity. This wrapper resolves
    that reference and prepares the column mapping used to read from it.
    """

    def __init__(
        self,
        model: Model,
        wrapper: EntityWrapper[ModelEntity],
        source: Any,
    ) -> None:
        """Store internal source metadata and resolve the referenced source entity."""
        self.model = model
        self.wrapper = wrapper
        self.source = source
        self.source_wrapper = self._resolve_source_wrapper()

    def _resolve_source_wrapper(self) -> EntityWrapper[ModelEntity]:
        """Resolve the configured source reference to the referenced model entity."""
        source_location = getattr(self.source, "sourceLocation", None)
        if isinstance(source_location, int):
            return get_model_entity_by_id(self.model, source_location)
        if isinstance(source_location, str):
            normalized = source_location.strip("/")
            if normalized:
                return get_one(self.model.modelEntities, normalized)
        raise ValueError(
            f"Unsupported internal source reference '{source_location}' for entity "
            f"'{self.wrapper.entity.name}'."
        )

    @property
    def source_zone(self) -> str:
        """Return the Databricks schema name of the referenced source entity."""
        zone_wrapper = self.model.get_zone_for_entity(self.source_wrapper)
        return zone_target_name(zone_wrapper)

    @property
    def source_table_name(self) -> str:
        """Return the short table name of the referenced source entity."""
        return self.source_wrapper.entity.name

    @property
    def source_full_table_name(self) -> str:
        """Return the generated full table name of the referenced source entity."""
        folders = self.source_wrapper.locator.folders
        table_name = self.source_wrapper.locator.entityName or self.source_wrapper.entity.name
        return "_".join([*folders[1:], table_name])

    @property
    def display_name(self) -> str:
        """Return a readable source name for generated tasks and comments."""
        return self.source_full_table_name

    @property
    def key(self) -> str:
        """Return a stable task key for this internal source."""
        return task_key(self.source_zone, self.source_full_table_name)

    @property
    def source_name(self) -> str:
        """Return the configured source alias, falling back to the source table name."""
        return getattr(self.source, "sourceAlias", None) or self.source_table_name

    @property
    def target_max_filter(self) -> str:
        """Return the filter used when looking up max values for this source."""
        return f"__SourceTable = '{self.source_name}'"

    @property
    def source_properties(self) -> dict[str, str]:
        """Return internal source properties as a simple name-to-value dictionary."""
        return {ref.property: ref.value for ref in getattr(self.source, "properties", None) or []}

    @property
    def extract_mode(self) -> str | None:
        """Return the normalized extraction mode for this internal source."""
        value = self.source_properties.get("extract_mode")
        if value is None:
            return None
        return str(value).strip().lower()

    @property
    def mapping_entries(self) -> list[dict[str, Any]]:
        """Return cleaned source-to-target mappings for this internal source."""
        entries: list[dict[str, Any]] = []
        for mapping in self.source.mapping or []:
            source_name = getattr(mapping, "sourceName", None)
            target_name = getattr(mapping, "targetName", None)
            if not source_name or not target_name:
                continue
            mapping_properties = {ref.property: ref.value for ref in mapping.properties or []}
            entries.append(
                {
                    "source": source_name,
                    "target": target_name,
                    "is_delta": str(mapping_properties.get("extract_mode", "")).lower() == "delta",
                }
            )
        return entries

    @property
    def column_renames(self) -> list[dict[str, str]]:
        """Return mappings where the source and target column names differ."""
        return [
            {"source": entry["source"], "target": entry["target"]}
            for entry in self.mapping_entries
            if entry["source"] != entry["target"]
        ]

    @property
    def has_mapping(self) -> bool:
        """Return whether this internal source defines any column mappings."""
        return len(self.mapping_entries) > 0

    @property
    def source_delta_column(self) -> str | None:
        """Return the source column used for delta loading, if one exists."""
        delta_entry = next((entry for entry in self.mapping_entries if entry["is_delta"]), None)
        if delta_entry:
            return delta_entry["source"]
        if self.extract_mode == "delta":
            return "__UpdateTimestampUTC"
        return None

    def _target_databricks_type(self, attr: Any) -> str:
        """Resolve the Databricks target type for one model attribute."""
        attr_type = getattr(getattr(attr, "dataType", None), "type", None)
        if not attr_type:
            return "string"
        for data_type in self.model.dataTypes.values():
            if data_type.entity.name == attr_type:
                return data_type.entity.targets.get(TARGET, attr_type)
        return str(attr_type)

    @property
    def select_expressions(self) -> list[str]:
        """Return business select list; technical columns are added in template."""
        mapping_by_target = {entry["target"]: entry["source"] for entry in self.mapping_entries}
        expressions: list[str] = []
        for attr in self.wrapper.entity.attributes:
            expression = getattr(attr, "calculation", None) or getattr(attr, "expression", None)
            if expression:
                expressions.append(f"{expression} AS `{attr.name}`")
                continue
            source_name = mapping_by_target.get(attr.name, attr.name)
            target_type = self._target_databricks_type(attr)
            expressions.append(f"try_cast(`{source_name}` as {target_type}) AS `{attr.name}`")

        return expressions
