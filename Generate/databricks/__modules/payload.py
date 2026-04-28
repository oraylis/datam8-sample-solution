"""
Module to prepare payload to be rendered by DataM8.

* each payload function is processed in a separate thread
* each payload instance of a function is rendered in a async manor
* a payloads need to implement the IPayload protocol which just requires two functions
    - get_data() -> object // object available as `data` in template
    - get_output_path() -> Path // path where the rendered template gets saved to
* payloads can be split across multiple files and import via their filename/path within the
    `__modules` directory
* the cache can be used to carry over generated value or similar across payloads
    - it would technically also be possible to create a dummy payload that returns an empty list
        and simply adds some values to the cache

Some notes/explanations to lean into the way the payloads/templates are rendered and make debugging
simpler.

* payloads only "gath" entities to be rendered and do some slight initialization
* payloads contain references to the model, wrapper and any additional entity to allow for further
    lookups
* most logic is implemented on the payload itself as a function or property, so that it gets
    executed within the asynchronous call
* a search locator used in `get_many` and `get_many_where` needs to end on with a "/", otherwise
    DataM8 will look for an entity with that exact locator
* use match statements for structural pattern matching to avoid inreadable chains of if-elif-else
    blocks
* prefer returning basic types or objects of classes defined in the payload itself, to narrow
    potential errors to the payload itself and not errors thrown by DataM8 itself or be affected
    by changes within DataM8 or its model
* retrieving an entity by its locator via `get()` is faster than using `get_where()` with a filter
* all functions return an EntityWrapper instance, with an entity attribute containing the content of
    the corresponding json file

"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datam8 import logging
from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import EntityWrapper, Model
from datam8.utils.cache import Cache
from datam8_model.attribute import Attribute, HistoryType
from datam8_model.data_type import DataType, DataTypeDefinition
from datam8_model.folder import Folder
from datam8_model.model import ExternalModelSource, ModelEntity
from datam8_model.property import PropertyReference
from datam8_model.zone import Zone

logger = logging.getLogger(__name__)

TARGET = "databricks"
EXTERNAL_PARTITIONS = ["__Year", "__Month", "__Day", "__InsertTimestampUTC"]
DATA_TYPE_ALIASES = {
    "integer": "int",
    "bigint": "long",
    "timestamp": "datetime",
}


def create_full_table_name(wrapper: EntityWrapper[ModelEntity]) -> str:
    name_parts = [f for f in wrapper.locator.folders][1:]
    name_parts.append(wrapper.entity.name)
    return "_".join(name_parts)


def create_resource_slug_from_name(name: str) -> str:
    resource_slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if len(resource_slug) == 0:
        return "default"
    return resource_slug


def create_task_key(*parts: str) -> str:
    value = "_".join(part for part in parts if part)
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "task"


def zone_target_name(zone: EntityWrapper[Zone]) -> str:
    return zone.entity.targetName or zone.entity.name


def zone_folder_name(zone: EntityWrapper[Zone]) -> str:
    return zone.entity.localFolderName or zone.entity.name


def zone_targets_databricks(zone: EntityWrapper[Zone]) -> bool:
    return any(
        ref.property == "target" and ref.value == TARGET for ref in zone.entity.properties or []
    )


def model_backed_zones(model: Model) -> list[EntityWrapper[Zone]]:
    return [
        zone
        for zone in model.zones.values()
        if zone_targets_databricks(zone) and zone.entity.localFolderName
    ]


def external_zone(model: Model) -> EntityWrapper[Zone]:
    for zone in model.zones.values():
        if zone_targets_databricks(zone) and not zone.entity.localFolderName:
            return zone
    raise ValueError(
        "No external Databricks zone found. Configure a Databricks zone without localFolderName."
    )


def zone_for_folder(model: Model, folder: str) -> EntityWrapper[Zone] | None:
    for zone in model.zones.values():
        if zone.entity.localFolderName == folder and zone_targets_databricks(zone):
            return zone
    return None


def model_entity_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    wrappers: list[EntityWrapper[ModelEntity]] = []
    for zone in model_backed_zones(model):
        wrappers.extend(model.modelEntities.get_many(f"{zone.entity.localFolderName}/"))
    return wrappers


def entity_product(wrapper: EntityWrapper[ModelEntity]) -> str:
    if len(wrapper.locator.folders) > 1:
        return wrapper.locator.folders[1]
    return "default"


def entity_module(wrapper: EntityWrapper[ModelEntity]) -> str:
    if len(wrapper.locator.folders) > 2:
        return wrapper.locator.folders[2]
    return "default"


def output_folders(wrapper: EntityWrapper[ModelEntity]) -> tuple[str, ...]:
    return tuple(wrapper.locator.folders[1:])


def property_values_by_name(
    refs: Iterable[PropertyReference] | None, property_name: str
) -> list[str]:
    return [ref.value for ref in refs or [] if ref.property == property_name]


def property_dict(refs: Iterable[Any] | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for ref in refs or []:
        name = getattr(ref, "property", None)
        if name:
            values[name] = getattr(ref, "value", None)
    return values


def wrapper_property_values(wrapper: EntityWrapper[Any], property_name: str) -> list[str]:
    return [pv.name for pv in wrapper.properties.values() if pv.property == property_name]


def first_wrapper_property(wrapper: EntityWrapper[Any], property_name: str) -> str | None:
    values = wrapper_property_values(wrapper, property_name)
    return values[0] if values else None


def attribute_property_equals(attribute: Attribute, property_name: str, value: str) -> bool:
    return any(
        ref.property.lower() == property_name.lower() and ref.value.lower() == value.lower()
        for ref in attribute.properties or []
    )


def build_history(entity: ModelEntity) -> dict[str, list[str]]:
    business_keys = [attr.name for attr in entity.attributes if attr.isBusinessKey]
    scd0: list[str] = []
    scd1: list[str] = []
    scd2: list[str] = []
    for attr in entity.attributes:
        match attr.history:
            case HistoryType.SCD0:
                scd0.append(attr.name)
            case HistoryType.SCD2:
                scd2.append(attr.name)
            case _:
                scd1.append(attr.name)
    return {
        "business_keys": business_keys,
        "scd0": scd0,
        "scd1": scd1,
        "scd2": scd2,
    }


def assignment_literal(column: str, expression: str) -> dict[str, str]:
    return {"column": column, "expression": repr(expression)}


def scd0_helper_name(column: str) -> str:
    sanitized = re.sub(r"\W+", "_", column or "").strip("_") or "value"
    return f"__scd0__{sanitized}"


def build_insert_assignments(
    attribute_names: Sequence[str],
    *,
    include_external_timestamp: bool,
    include_source_table: bool,
    include_business_function: bool,
) -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    technical_columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
    if include_business_function:
        technical_columns.append("__BusinessFunction")
    if include_source_table:
        technical_columns.append("__SourceTable")
    if include_external_timestamp:
        technical_columns.append("__InsertTimestampRawUTC")

    for column in technical_columns:
        assignments.append(assignment_literal(column, f"src.{column}"))
    for name in attribute_names:
        assignments.append(assignment_literal(name, f"src.`{name}`"))
    return assignments


def schema_columns(
    attribute_names: Sequence[str],
    *,
    include_external_timestamp: bool,
    include_source_table: bool,
    include_business_function: bool,
) -> list[str]:
    columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
    if include_business_function:
        columns.append("__BusinessFunction")
    if include_source_table:
        columns.append("__SourceTable")
    if include_external_timestamp:
        columns.append("__InsertTimestampRawUTC")
    columns.extend(attribute_names)
    return columns


def surrogate_key_columns(entity: ModelEntity) -> list[str]:
    return [
        attr.name
        for attr in entity.attributes
        if attribute_property_equals(attr, "attribute_type", "sk")
    ]


def read_transform_script(wrapper: EntityWrapper[ModelEntity], script_name: str) -> str:
    script_path = wrapper.source_file.parent / wrapper.entity.name / script_name
    if not script_path.exists():
        script_path = wrapper.source_file.parent / script_name
    return script_path.read_text(encoding="utf-8")


def collect_transformations(wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
    transformations: list[dict[str, Any]] = []
    for transform in wrapper.entity.transformations or []:
        function = getattr(transform, "function", None)
        script_name = getattr(function, "source", None) if function is not None else None
        if not script_name:
            continue
        script_stem = Path(script_name).stem
        key = script_stem
        script_module = f"{wrapper.entity.name}_functions/{script_stem}"
        transformations.append(
            {
                "key": key,
                "name": transform.name,
                "merge_type": "replace",
                "frequency": first_wrapper_property(wrapper, "frequency") or "no_restriction",
                "sources": [],
                "script_name": script_name,
                "script_module": script_module,
                "script_content": read_transform_script(wrapper, script_name),
            }
        )
    return transformations


def get_data_source(model: Model, name: str) -> Any:
    return model.dataSources.get(name).entity


def get_data_source_type(model: Model, name: str) -> Any:
    return model.dataSourceTypes.get(name).entity


def source_properties(source: ExternalModelSource) -> dict[str, str]:
    return {ref.property: ref.value for ref in source.properties or []}


def external_table_name(wrapper: EntityWrapper[ModelEntity], source: ExternalModelSource) -> str:
    return source.sourceAlias or wrapper.entity.name


def external_full_table_name(wrapper: EntityWrapper[ModelEntity], source: ExternalModelSource) -> str:
    return "_".join([entity_product(wrapper), entity_module(wrapper), external_table_name(wrapper, source)])


def data_type_mappings(model: Model, data_source_name: str) -> dict[str, str]:
    data_source = get_data_source(model, data_source_name)
    data_source_type = get_data_source_type(model, data_source.type)
    mappings = {m.sourceType: m.targetType for m in data_source_type.dataTypeMapping or []}
    mappings.update({m.sourceType: m.targetType for m in data_source.dataTypeMapping or []})
    return mappings


def external_mapping_projection(
    model: Model, wrapper: EntityWrapper[ModelEntity], source: ExternalModelSource
) -> dict[str, list[Any]]:
    mappings = source.mapping or []
    type_mappings = data_type_mappings(model, source.dataSource)
    select_columns: list[str] = []
    target_columns: list[str] = []
    column_renames: list[dict[str, str]] = []
    delta_column_details: list[dict[str, str]] = []

    mappings_by_target = {mapping.targetName: mapping for mapping in mappings}
    for attr in wrapper.entity.attributes:
        if expr := (getattr(attr, "calculation", None) or getattr(attr, "expression", None)):
            select_columns.append(f"{expr} AS `{attr.name}`")
            target_columns.append(attr.name)
            continue
        mapping = mappings_by_target.get(attr.name)
        if mapping is None:
            continue
        target_name = mapping.targetName
        select_columns.append(f"`{target_name}`")
        target_columns.append(target_name)
        source_name = mapping.sourceName
        if source_name != target_name:
            column_renames.append({"source": source_name, "target": target_name})
    for mapping in mappings:
        props = {ref.property: ref.value for ref in mapping.properties or []}
        if props.get("extract_mode") == "delta":
            data_type = mapping.sourceDataType.type if mapping.sourceDataType else ""
            delta_column_details.append(
                {
                    "source": source_name,
                    "target": target_name,
                    "type": type_mappings.get(data_type, data_type),
                }
            )

    return {
        "select_columns": select_columns,
        "target_columns": target_columns,
        "column_renames": column_renames,
        "delta_column_details": delta_column_details,
    }


def external_sources(model: Model, wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
    zone = external_zone(model)
    source_zone = zone_target_name(zone)
    sources: list[dict[str, Any]] = []
    for source in wrapper.entity.sources or []:
        if not getattr(source, "dataSource", None):
            continue
        projection = external_mapping_projection(model, wrapper, source)
        table_name = external_table_name(wrapper, source)
        full_table_name = external_full_table_name(wrapper, source)
        select_expressions = [
            *projection["select_columns"],
            f"'{table_name}' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "__InsertTimestampUTC AS __InsertTimestampRawUTC",
        ]
        data_source = get_data_source(model, source.dataSource)
        sources.append(
            {
                "key": create_task_key(source_zone, full_table_name),
                "source_zone": source_zone,
                "external_table": table_name,
                "external_full_table": full_table_name,
                "table_name": table_name,
                "full_table_name": full_table_name,
                "data_product": entity_product(wrapper),
                "data_module": entity_module(wrapper),
                "data_source": source.dataSource,
                "data_source_display": data_source.displayName or source.dataSource,
                "data_source_type": data_source.type,
                "data_source_extended_properties": data_source.extendedProperties or {},
                "source_alias": source.sourceAlias or table_name,
                "source_name": source.sourceAlias or table_name,
                "source_location": source.sourceLocation or table_name,
                "properties": source_properties(source),
                "extract_mode": source_properties(source).get("extract_mode"),
                "mapping": source.mapping,
                "mapping_entries": source.mapping or [],
                "select_expressions": select_expressions,
                **projection,
            }
        )
    return sources


def calculated_columns(entity: ModelEntity) -> list[dict[str, str]]:
    columns: list[dict[str, str]] = []
    for attr in entity.attributes:
        expr = getattr(attr, "calculation", None) or getattr(attr, "expression", None)
        if expr:
            columns.append({"name": attr.name, "expression_literal": repr(expr)})
    return columns


def dimension_lookups(model: Model, wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
    lookups: list[dict[str, Any]] = []
    for rel in wrapper.entity.relationships or []:
        remote = model.modelEntities.get_by_id(rel.targetLocation)
        sid_columns = surrogate_key_columns(remote.entity)
        lookups.append(
            {
                "dimension_zone": zone_target_name(model.get_zone_for_entity(remote)),
                "dimension_full_table_name": create_full_table_name(remote),
                "dimension_alias": create_task_key(remote.entity.name).lower(),
                "dimension_sid_column": sid_columns[0] if sid_columns else remote.entity.attributes[0].name,
                "sid_column": rel.attributes[0].sourceName if rel.attributes else "",
                "join_columns": [
                    {
                        "fact_column": attr.sourceName,
                        "dimension_column": attr.targetName,
                    }
                    for attr in rel.attributes
                ],
            }
        )
    return lookups


def build_merge_config(
    entity: ModelEntity,
    history: dict[str, list[str]],
    attribute_names: list[str],
    *,
    write_mode: str,
    include_external_timestamp: bool,
    include_source_table: bool,
    include_business_function: bool,
) -> dict[str, Any]:
    business_keys = history["business_keys"]
    scd0_columns = history["scd0"]
    scd1_columns = [name for name in history["scd1"] if name not in business_keys]
    scd2_columns = [name for name in history["scd2"] if name not in business_keys]
    sk_columns = set(surrogate_key_columns(entity))
    assignment_names = attribute_names
    if write_mode == "merge" and sk_columns:
        assignment_names = [name for name in attribute_names if name not in sk_columns]
        scd1_columns = [name for name in scd1_columns if name not in sk_columns]
        scd2_columns = [name for name in scd2_columns if name not in sk_columns]

    scd0_helpers = [{"column": column, "helper": scd0_helper_name(column)} for column in scd0_columns]
    return {
        "enabled": write_mode == "merge" and bool(business_keys),
        "has_scd2_history": bool(scd2_columns),
        "business_keys": business_keys,
        "scd0_helper_lookup": {entry["column"]: entry["helper"] for entry in scd0_helpers},
        "scd0_helper_columns": scd0_helpers,
        "scd2_non_business_columns": scd2_columns,
        "scd1_update_assignments": [
            assignment_literal(name, f"src.`{name}`") for name in scd1_columns
        ]
        + ([assignment_literal("__UpdateTimestampUTC", "src.__UpdateTimestampUTC")] if scd1_columns else []),
        "scd1_change_condition": " OR ".join(
            f"NOT (tgt.`{column}` <=> src.`{column}`)" for column in scd1_columns
        ),
        "insert_assignments": build_insert_assignments(
            assignment_names,
            include_external_timestamp=include_external_timestamp,
            include_source_table=include_source_table,
            include_business_function=include_business_function,
        ),
        "merge_condition": " AND ".join(f"tgt.`{col}` <=> src.`{col}`" for col in business_keys),
    }


def default_cluster_variable(model: Model) -> str:
    for pv in model.propertyValues.get_many("cluster/"):
        if pv.entity.default:
            return f"cluster_{create_resource_slug_from_name(pv.entity.name)}"
    clusters = model.propertyValues.get_many("cluster/")
    return f"cluster_{create_resource_slug_from_name(clusters[0].entity.name)}" if clusters else ""


def job_property(wrapper: EntityWrapper[Any]) -> str:
    return first_wrapper_property(wrapper, "jobs") or "daily"


def schedule_for_job(model: Model, job_name: str) -> dict[str, str] | None:
    job = model.propertyValues.get(f"jobs/{job_name}").entity
    schedules = property_values_by_name(job.properties, "schedules")
    if not schedules:
        return None
    schedule = model.propertyValues.get(f"schedules/{schedules[0]}").entity
    return {
        "cron_expression": getattr(schedule, "quartz_cron_expression", "49 0 1 * * ?"),
        "timezone_id": "UTC",
    }


def cluster_for_job(model: Model, job_name: str) -> str:
    job = model.propertyValues.get(f"jobs/{job_name}").entity
    clusters = property_values_by_name(job.properties, "cluster")
    if clusters:
        return f"cluster_{create_resource_slug_from_name(clusters[0])}"
    return default_cluster_variable(model)


@register_payload("ddl_notebook.jinja2")
def ddl_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    return [DdlPayload(wrapper, model) for wrapper in model_entity_wrappers(model)]


@register_payload("ddl_notebook.jinja2")
def ddl_external_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    external_source_zone = model_backed_zones(model)[0]
    return [
        DdlExternalPayload(wrapper, model, source)
        for wrapper in model.modelEntities.get_many(
            f"{external_source_zone.entity.localFolderName}/"
        )
        for source in wrapper.entity.sources or []
        if getattr(source, "dataSource", None)
    ]


@register_payload("schema.yml.jinja2")
def dab_schemas(model: Model, cache: Cache) -> Sequence[IPayload]:
    return [
        BasePayload(
            data=[
                {
                    "resource_key": f"schema_{create_resource_slug_from_name(zone_target_name(zone))}",
                    "name": zone_target_name(zone),
                    "comment": zone.entity.displayName,
                }
                for zone in model.zones.values()
                if zone_targets_databricks(zone)
            ],
            output_path=Path("schemas", "schema.yml"),
        )
    ]


@register_payload("clusters.yml.jinja2")
def dab_cluster(model: Model, cache: Cache) -> Sequence[IPayload]:
    clusters = [wrapper.entity for wrapper in model.propertyValues.get_many("cluster/")]
    if len(clusters) == 0:
        return []
    return [
        BasePayload(
            data=[
                {
                    "name": cluster.name,
                    "display_name": cluster.displayName or cluster.name,
                    "node_type": getattr(cluster, "node_type", "Standard_D4ds_v5"),
                    "num_workers": getattr(cluster, "num_workers", None),
                    "workload_type": getattr(cluster, "workload_type", "job"),
                    "spark_version": getattr(cluster, "spark_version", "16.4.x-scala2.12"),
                    "autotermination_minutes": getattr(cluster, "autotermination_minutes", 60),
                    "data_security_mode": getattr(
                        cluster, "data_security_mode", "DATA_SECURITY_MODE_DEDICATED"
                    ),
                    "runtime_engine": getattr(cluster, "runtime_engine", "STANDARD"),
                    "variable_name": f"cluster_{create_resource_slug_from_name(cluster.name)}",
                    "is_default": cluster.default or False,
                    "custom_tags": {},
                }
                for cluster in clusters
            ],
            output_path=Path("clusters", "clusters.yml"),
        )
    ]


@register_payload("dml_notebook.jinja2", order=2)
def dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    source_zone_name = zone_target_name(external_zone(model))
    for wrapper in model_entity_wrappers(model):
        zone = model.get_zone_for_entity(wrapper)
        entity = wrapper.entity
        history = build_history(entity)
        attribute_names = [attr.name for attr in entity.attributes]
        transformations = collect_transformations(wrapper)
        cache.set(f"dml_transformations::{wrapper.locator}", transformations)
        stage_sources = external_sources(model, wrapper)
        source_mode = "none"
        if transformations:
            source_mode = "transformation"
        elif stage_sources:
            source_mode = "external_delta"
        has_external_source = bool(stage_sources)
        include_external_timestamp = source_mode == "external_delta"
        include_source_table = source_mode == "external_delta"
        include_business_function = not has_external_source
        write_mode = first_wrapper_property(wrapper, "write_mode") or "overwrite"
        schema_column_names = schema_columns(
            attribute_names,
            include_external_timestamp=include_external_timestamp,
            include_source_table=include_source_table,
            include_business_function=include_business_function,
        )
        sk_columns = set(surrogate_key_columns(entity))
        merge_config = build_merge_config(
            entity,
            history,
            attribute_names,
            write_mode=write_mode,
            include_external_timestamp=include_external_timestamp,
            include_source_table=include_source_table,
            include_business_function=include_business_function,
        )
        payloads.append(
            BasePayload(
                data={
                    "zone": zone_target_name(zone),
                    "zone_display": zone.entity.displayName,
                    "data_product": entity_product(wrapper),
                    "data_module": entity_module(wrapper),
                    "table_name": entity.name,
                    "full_table_name": create_full_table_name(wrapper),
                    "history": history,
                    "write_mode": write_mode,
                    "spark_write_mode": {"overwrite": "overwrite", "append": "append"}.get(
                        write_mode, "overwrite"
                    ),
                    "source_mode": source_mode,
                    "external_sources": [
                        {
                            **source,
                            "source_zone": source_zone_name,
                        }
                        for source in stage_sources
                    ],
                    "transformations": transformations,
                    "final_function_key": transformations[-1]["key"] if transformations else None,
                    "business_keys": history["business_keys"],
                    "non_business_columns": [
                        name for name in attribute_names if name not in history["business_keys"]
                    ],
                    "attribute_columns": attribute_names,
                    "schema_columns": schema_column_names,
                    "write_schema_columns": [
                        column for column in schema_column_names if column not in sk_columns
                    ],
                    "merge_conditions_flat": merge_config["merge_condition"],
                    "source_references": [],
                    "has_lookup_dimensions": False,
                    "dimension_lookups": [],
                    "insert_assignments": merge_config["insert_assignments"],
                    "scd0_columns": history["scd0"],
                    "scd0_helper_columns": merge_config["scd0_helper_columns"],
                    "scd0_helper_lookup": merge_config["scd0_helper_lookup"],
                    "scd1_columns": history["scd1"],
                    "scd1_non_business_columns": [
                        name for name in history["scd1"] if name not in history["business_keys"]
                    ],
                    "scd2_columns": history["scd2"],
                    "scd2_non_business_columns": merge_config["scd2_non_business_columns"],
                    "has_scd2_history": bool(history["scd2"]),
                    "external_merge_config": merge_config if merge_config["enabled"] and stage_sources else None,
                    "final_merge_config": merge_config if merge_config["enabled"] and transformations else None,
                    "calculated_columns": calculated_columns(entity),
                },
                output_path=Path(
                    "notebooks",
                    zone_folder_name(zone),
                    "dml",
                    *output_folders(wrapper),
                    f"{wrapper.locator.entityName or entity.name}.py",
                ),
            )
        )
    return payloads


@register_payload("dml_external_notebook.jinja2", order=2)
def dml_external_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    zone = external_zone(model)
    external_source_zone = model_backed_zones(model)[0]
    for wrapper in model.modelEntities.get_many(f"{external_source_zone.entity.localFolderName}/"):
        for source in wrapper.entity.sources or []:
            if not getattr(source, "dataSource", None):
                continue
            external = external_sources(model, wrapper)
            current = next(
                item for item in external if item["table_name"] == external_table_name(wrapper, source)
            )
            props = current["properties"]
            data_source_entry = get_data_source(model, current["data_source"])
            extract_mode = props.get("extract_mode")
            current.update(
                {
                    "zone": zone_target_name(zone),
                    "zone_display": zone.entity.displayName,
                    "data_source_display": data_source_entry.displayName or current["data_source"],
                    "write_mode": "overwrite" if extract_mode == "overwrite" else "append",
                    "use_connector": bool(getattr(data_source_entry, "connector", None)),
                    "connector_id": getattr(data_source_entry, "connector", None),
                    "is_query": str(extract_mode or "").lower() == "query",
                    "query_plan": {
                        "is_query": str(extract_mode or "").lower() == "query",
                        "has_delta_filter": str(extract_mode or "").lower() == "delta",
                        "timestamp_delta": False,
                        "delta_columns_csv": ", ".join(
                            item["source"] for item in current["delta_column_details"]
                        ),
                    },
                    "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
                    "connection_secret_key": f"datasource-{current['data_source']}-password",
                    "delta_column": (
                        current["delta_column_details"][0]["target"]
                        if current["delta_column_details"]
                        else None
                    ),
                    "source_delta_column": (
                        current["delta_column_details"][0]["source"]
                        if current["delta_column_details"]
                        else None
                    ),
                }
            )
            payloads.append(
                BasePayload(
                    data=current,
                    output_path=Path(
                        "notebooks",
                        zone_folder_name(zone),
                        "dml",
                        *output_folders(wrapper),
                        f"{current['table_name']}.py",
                    ),
                )
            )
    return payloads


@register_payload("dml_function.jinja2", order=2)
def dml_function_scripts(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for wrapper in model_entity_wrappers(model):
        zone = model.get_zone_for_entity(wrapper)
        try:
            transformations = cache.get(f"dml_transformations::{wrapper.locator}")
        except KeyError:
            transformations = collect_transformations(wrapper)
        for transform in transformations:
            payloads.append(
                BasePayload(
                    data={"content": transform["script_content"]},
                    output_path=Path(
                        "notebooks",
                        zone_folder_name(zone),
                        "dml",
                        *output_folders(wrapper),
                        f"{wrapper.locator.entityName}_functions",
                        transform["script_name"],
                    ),
                )
            )
    return payloads


class DdlColumn:
    def __init__(self, attr: Attribute, model: Model) -> None:
        self.attribute = attr
        self.model = model

    @property
    def type_definition(self) -> DataTypeDefinition:
        type_name = DATA_TYPE_ALIASES.get(self.attribute.dataType.type, self.attribute.dataType.type)
        return self.model.dataTypes.get(type_name).entity

    @property
    def target_type(self) -> str:
        target_type = self.type_definition.targets[TARGET]
        match [
            self.attribute.dataType.precision,
            self.attribute.dataType.scale,
            self.attribute.dataType.charLen,
        ]:
            case [int() as precision, None, None]:
                target_type += f"({precision})"
            case [int() as precision, int() as scale, None]:
                target_type += f"({precision}, {scale})"
            case [None, None, int() as char_length]:
                target_type += f"({char_length})"
            case [None, None, None]:
                pass
            case _:
                logger.warning("Invalid combination of precision, scale and charLen")
        return target_type

    @property
    def spark_data_type_expression(self) -> str:
        return f"{self.target_type}".upper()

    @property
    def spark_nullable(self) -> str:
        return " NULL" if self.attribute.dataType.nullable else " NOT NULL"

    @property
    def spark_comment(self) -> str:
        if self.attribute.description is None:
            return ""
        return f" COMMENT '{self.attribute.description}'"

    @property
    def is_surrogate_key(self) -> bool:
        return attribute_property_equals(self.attribute, "attribute_type", "sk")

    @property
    def spark_identity(self) -> str:
        return " GENERATED ALWAYS AS IDENTITY" if self.is_surrogate_key else ""

    @property
    def name(self) -> str:
        return self.attribute.name

    @property
    def spark_type_expr(self) -> str:
        return f'DataType.fromDDL("{self.spark_data_type_expression}")'

    @property
    def struct_nullable(self) -> bool:
        return self.attribute.dataType.nullable

    @property
    def metadata_repr(self) -> str:
        metadata: dict[str, Any] = {}
        if self.attribute.description:
            metadata["comment"] = self.attribute.description
        if self.attribute.isBusinessKey:
            metadata["business_key"] = True
        return repr(metadata) if metadata else ""

    @property
    def sql_definition(self) -> str:
        nullable = "" if self.attribute.dataType.nullable else " NOT NULL"
        return f"`{self.name}` {self.spark_data_type_expression}{nullable}{self.spark_comment}"


@dataclasses.dataclass
class RenderedDdlColumn:
    name: str
    spark_data_type_expression: str
    nullable: bool
    comment: str | None = None
    business_key: bool = False

    @property
    def spark_type_expr(self) -> str:
        return f'DataType.fromDDL("{self.spark_data_type_expression}")'

    @property
    def struct_nullable(self) -> bool:
        return self.nullable

    @property
    def metadata_repr(self) -> str:
        metadata: dict[str, Any] = {}
        if self.comment:
            metadata["comment"] = self.comment
        if self.business_key:
            metadata["business_key"] = True
        return repr(metadata) if metadata else ""

    @property
    def sql_definition(self) -> str:
        nullable = "" if self.nullable else " NOT NULL"
        comment = f" COMMENT '{self.comment}'" if self.comment else ""
        return f"`{self.name}` {self.spark_data_type_expression}{nullable}{comment}"


def technical_columns_for_entity(entity: ModelEntity) -> list[RenderedDdlColumn]:
    columns = [
        RenderedDdlColumn("__InsertTimestampUTC", "TIMESTAMP", False, "Load timestamp (UTC)"),
        RenderedDdlColumn("__UpdateTimestampUTC", "TIMESTAMP", False, "Last update timestamp (UTC)"),
    ]
    has_external_source = any(getattr(source, "dataSource", None) for source in entity.sources or [])
    has_transformation = bool(entity.transformations)
    if has_transformation and not has_external_source:
        columns.append(RenderedDdlColumn("__BusinessFunction", "STRING", False, "Business function identifier"))
    if has_external_source:
        columns.append(
            RenderedDdlColumn(
                "__InsertTimestampRawUTC", "TIMESTAMP", False, "External load timestamp (UTC)"
            )
        )
        columns.append(RenderedDdlColumn("__SourceTable", "STRING", False, "Origin reference for the record"))
    return columns


def scd2_tracking_columns() -> list[RenderedDdlColumn]:
    return [
        RenderedDdlColumn("__ValidFrom", "TIMESTAMP", False, "SCD2 start date"),
        RenderedDdlColumn("__ValidTo", "TIMESTAMP", False, "SCD2 end date"),
        RenderedDdlColumn("__IsCurrent", "BOOLEAN", False, "SCD2 current flag"),
    ]


def create_table_sql(
    *,
    catalog_name: str,
    zone_name: str,
    full_table_name: str,
    columns: Sequence[DdlColumn | RenderedDdlColumn],
    table_comment: str,
    partitions: Sequence[str],
    table_properties: dict[str, Any],
) -> str:
    lines = [
        f"CREATE TABLE IF NOT EXISTS {catalog_name}.{zone_name}.{full_table_name} (",
    ]
    for index, column in enumerate(columns):
        comma = "," if index < len(columns) - 1 else ""
        lines.append(f"  {column.sql_definition}{comma}")
    lines.append(")")
    lines.append("USING DELTA")
    if table_comment:
        lines.append(f"COMMENT '{table_comment}'")
    if partitions:
        quoted = ", ".join(f"`{partition}`" for partition in partitions)
        lines.append(f"CLUSTER BY ({quoted})")
    if table_properties:
        props = ", ".join(f"'{key}'='{value}'" for key, value in table_properties.items())
        lines.append(f"TBLPROPERTIES ({props});")
    else:
        lines[-1] = f"{lines[-1]};"
    return "\n".join(lines)


class DdlExternalColumn(DdlColumn):
    @property
    def type_definition(self) -> DataTypeDefinition:
        return DataTypeDefinition(
            name=self.attribute.dataType.type,
            targets={TARGET: self.attribute.dataType.type},
        )

    @property
    def target_type(self) -> str:
        type_name = DATA_TYPE_ALIASES.get(self.attribute.dataType.type, self.attribute.dataType.type)
        type_name = {"short": "smallint", "datetime": "timestamp"}.get(type_name, type_name)
        return type_name.upper()


class DdlPayload(BasePayload):
    imports: list[str] = ["StructType", "StructField", "DataType"]
    is_external = False

    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        self.model = model
        self.wrapper = wrapper
        self.locator = wrapper.locator
        self.entity = wrapper.entity
        self.zone_wrapper = model.get_zone_for_entity(wrapper)
        self.first_folder: EntityWrapper[Folder] = model.folders.get(
            "/".join(self.locator.folders[0:2])
        )

    @property
    def zone_name(self) -> str:
        return zone_target_name(self.zone_wrapper)

    @property
    def zone(self) -> str:
        return self.zone_name

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
            "ddl",
            *output_folders(self.wrapper),
            f"{self.entity.name or self.locator.entityName}.py",
        )

    @property
    def data_product(self) -> str:
        return entity_product(self.wrapper)

    @property
    def data_module(self) -> str:
        return entity_module(self.wrapper)

    @property
    def full_table_name(self) -> str:
        return create_full_table_name(self.wrapper)

    @property
    def table_comment(self) -> str:
        return self.entity.description or ""

    @property
    def table_name(self) -> str:
        return self.entity.name

    @property
    def columns(self) -> Sequence[DdlColumn | RenderedDdlColumn]:
        columns: list[DdlColumn | RenderedDdlColumn] = [
            *technical_columns_for_entity(self.entity),
            *[DdlColumn(attr, self.model) for attr in self.entity.attributes],
        ]
        if self.has_scd2_history:
            columns.extend(scd2_tracking_columns())
        return columns

    @property
    def has_scd2_history(self) -> bool:
        return any([attr.history == HistoryType.SCD2 for attr in self.entity.attributes])

    @property
    def partitions(self) -> list[str]:
        return [attribute.name for attribute in self.entity.attributes if attribute.isBusinessKey]

    @property
    def table_properties(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            match [pv.property, pv.name]:
                case ["table_properties", "column_mapping"]:
                    discovered["delta.columnMapping.mode"] = "name"
                case ["table_properties", "type_widening"]:
                    discovered["delta.enableTypeWidening"] = "true"
                case ["data_retention", str() as name]:
                    interval_value = name.replace("_", " ")
                    if not interval_value.lower().startswith("interval"):
                        interval_value = f"interval {interval_value}"
                    discovered["delta.logRetentionDuration"] = interval_value
                    discovered["delta.deletedFileRetentionDuration"] = interval_value
                case _:
                    pass
        order = [
            "delta.columnMapping.mode",
            "delta.enableTypeWidening",
            "delta.logRetentionDuration",
            "delta.deletedFileRetentionDuration",
        ]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def table_tags(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            if pv.property == "table_properties":
                discovered.setdefault("table_properties", []).append(pv.name)
            elif pv.property in {"business_area", "jobs", "write_mode", "data_retention"}:
                discovered[pv.property] = pv.name
        order = ["business_area", "jobs", "table_properties", "write_mode", "data_retention"]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def table_tags_repr(self) -> str:
        return repr(self.table_tags)

    @property
    def has_table_tags(self) -> bool:
        return bool(self.table_tags)

    @property
    def column_tags(self) -> list[dict[str, str]]:
        tags_by_column: dict[str, dict[str, str]] = {}
        for attr in self.entity.attributes:
            if attr.properties:
                tags_by_column.setdefault(attr.name, {}).update(
                    {ref.property: ref.value for ref in attr.properties}
                )
        for source in self.entity.sources or []:
            for mapping in source.mapping or []:
                if mapping.properties:
                    tags_by_column.setdefault(mapping.targetName, {}).update(
                        {ref.property: ref.value for ref in mapping.properties}
                    )
        return [
            {"column": attr.name, "tags_repr": repr(tags_by_column[attr.name])}
            for attr in self.entity.attributes
            if attr.name in tags_by_column
        ]

    @property
    def refactored_columns(self) -> list[dict[str, str | Sequence[str]]]:
        return [
            {"name": attr.name, "aliases": attr.refactorNames}
            for attr in self.entity.attributes
            if attr.refactorNames is not None and len(attr.refactorNames) > 0
        ]

    @property
    def create_table_sql(self) -> str:
        return create_table_sql(
            catalog_name="{catalog_name}",
            zone_name="{zone}",
            full_table_name=self.full_table_name,
            columns=self.columns,
            table_comment=self.table_comment,
            partitions=self.partitions,
            table_properties=self.table_properties,
        )

    @property
    def foreign_keys(self) -> list[DdlForeignKey]:
        constraints: list[DdlForeignKey] = []
        for rel in self.entity.relationships:
            remote_entity = self.model.modelEntities.get_by_id(rel.targetLocation)
            constraints.append(
                DdlForeignKey(
                    table=self.full_table_name,
                    columns=[a.sourceName for a in rel.attributes],
                    remote_columns=[a.targetName for a in rel.attributes],
                    remote_table=create_full_table_name(remote_entity),
                    remote_zone=zone_target_name(self.model.get_zone_for_entity(remote_entity)),
                )
            )
        return constraints

    @property
    def primary_key_attributes(self) -> list[Attribute]:
        return [attr for attr in self.entity.attributes if attr.isBusinessKey]


class DdlExternalPayload(DdlPayload):
    partitions = EXTERNAL_PARTITIONS
    is_external = True

    def __init__(
        self, wrapper: EntityWrapper[ModelEntity], model: Model, source: ExternalModelSource
    ) -> None:
        super().__init__(wrapper, model)
        self.source = source
        self.zone_wrapper = external_zone(model)
        self.base_columns = [
            DdlExternalColumn(
                Attribute(
                    ordinalNumber=1000,
                    name=col,
                    dataType=DataType(type=type_, nullable=False),
                    dateAdded=datetime.now(UTC),
                    attributeType="",
                ),
                self.model,
            )
            for col, type_ in [
                ("__Year", "short"),
                ("__Month", "short"),
                ("__Day", "short"),
                ("__InsertTimestampUTC", "datetime"),
            ]
        ]

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
            "ddl",
            *output_folders(self.wrapper),
            f"{external_table_name(self.wrapper, self.source)}.py",
        )

    @property
    def full_table_name(self) -> str:
        return external_full_table_name(self.wrapper, self.source)

    @property
    def data_source(self) -> str:
        return self.source.dataSource or ""

    @property
    def data_source_display(self) -> str:
        data_source = get_data_source(self.model, self.data_source)
        return data_source.displayName or self.data_source

    @property
    def source_name(self) -> str:
        return self.source.sourceAlias or self.full_table_name

    @property
    def table_tags(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            if pv.property == "table_properties":
                discovered.setdefault("table_properties", []).append(pv.name)
            elif pv.property in {"business_area", "jobs"}:
                discovered[pv.property] = pv.name
        order = ["business_area", "jobs", "table_properties"]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def column_tags(self) -> list[dict[str, str]]:
        tags_by_column: dict[str, dict[str, str]] = {}
        source_alias = self.source.sourceAlias
        source_location = self.source.sourceLocation
        entity_json = {}
        candidate_files = [
            self.wrapper.source_file,
            Path(__file__).resolve().parents[3]
            / "Model"
            / Path(*self.locator.folders)
            / f"{self.locator.entityName or self.entity.name}.json",
        ]
        for candidate_file in candidate_files:
            try:
                entity_json = json.loads(candidate_file.read_text(encoding="utf-8"))
                break
            except OSError:
                continue
        for source in entity_json.get("sources", []):
            if source.get("sourceAlias") != source_alias and source.get("sourceLocation") != source_location:
                continue
            for mapping in source.get("mapping", []):
                properties = mapping.get("properties") or []
                if properties:
                    tags_by_column.setdefault(mapping["targetName"], {}).update(
                        {ref["property"]: ref["value"] for ref in properties}
                    )
        for mapping in self.source.mapping or []:
            props = property_dict(getattr(mapping, "properties", None))
            if props:
                tags_by_column.setdefault(mapping.targetName, {}).update(props)
        return [
            {"column": mapping.targetName, "tags_repr": repr(tags_by_column[mapping.targetName])}
            for mapping in self.source.mapping or []
            if mapping.targetName in tags_by_column
        ]

    @property
    def columns(self) -> list[DdlExternalColumn]:
        assert self.source.mapping, "External source should have source mappings"
        type_mappings = data_type_mappings(self.model, self.source.dataSource)
        column_types: dict[str, DataType] = {}
        for source_column in self.source.mapping:
            if source_column.sourceDataType is None:
                raise Exception(f"Could not get source type of {source_column} in {self.entity.name}")
            column_types[source_column.sourceName] = source_column.sourceDataType
            if source_column.sourceDataType.type in type_mappings:
                column_types[source_column.sourceName].type = type_mappings[
                    source_column.sourceDataType.type
                ]
        return self.base_columns + [
            DdlExternalColumn(
                Attribute(
                    ordinalNumber=1,
                    attributeType="",
                    name=source_column_mapping.targetName,
                    dataType=column_types[source_column_mapping.sourceName],
                    dateAdded=datetime.now(UTC),
                ),
                self.model,
            )
            for source_column_mapping in self.source.mapping
        ]


@dataclasses.dataclass
class DdlForeignKey:
    table: str
    columns: list[str]
    remote_columns: list[str]
    remote_table: str
    remote_zone: str


def entities_by_zone_and_module(model: Model) -> dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]]:
    groups: dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in model_entity_wrappers(model):
        zone = model.get_zone_for_entity(wrapper)
        groups[(zone_folder_name(zone), entity_product(wrapper), entity_module(wrapper))].append(wrapper)
    return groups


def job_zone_slug(zone: EntityWrapper[Zone]) -> str:
    if zone.entity.localFolderName:
        return f"{zone.entity.localFolderName.split('-', 1)[0]}-{zone.entity.name}"
    return zone.entity.name


def create_job_key(zone: EntityWrapper[Zone], *parts: str) -> str:
    suffix = "_".join(part for part in parts if part)
    if suffix:
        return f"Create_{zone.entity.name}_{suffix}"
    return f"Create_{zone.entity.name}_tables"


def create_job_name(zone: EntityWrapper[Zone], *parts: str) -> str:
    suffix = " ".join(part for part in parts if part)
    if suffix:
        return f"Create {zone.entity.displayName} {suffix}"
    return f"Create {zone.entity.displayName}"


def notebook_job_path(
    zone: EntityWrapper[Zone],
    kind: str,
    wrapper: EntityWrapper[ModelEntity],
    *,
    name: str | None = None,
) -> str:
    notebook_name = name or wrapper.locator.entityName or wrapper.entity.name
    return Path(zone_folder_name(zone), kind, *output_folders(wrapper), notebook_name).as_posix()


def job_clusters(cluster_variable: str) -> list[dict[str, str]]:
    return [{"job_cluster_key": cluster_variable}] if cluster_variable else []


@register_payload("jobs/create_module.yml.jinja2")
def jobs_create_modules(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    default_cluster = default_cluster_variable(model)
    for (zone_folder, product, module), wrappers in entities_by_zone_and_module(model).items():
        zone = zone_for_folder(model, zone_folder)
        if zone is None:
            continue
        tasks = [
            {
                "task_key": create_task_key(
                    zone.entity.name, product, module, wrapper.locator.entityName or wrapper.entity.name
                ).lower(),
                "notebook_path": notebook_job_path(zone, "ddl", wrapper),
            }
            for wrapper in wrappers
        ]
        job_key = create_job_key(zone, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": create_job_name(zone, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": job_clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": tasks,
                },
                output_path=Path("jobs", job_zone_slug(zone), product, module, f"{job_key}.yml"),
            )
        )

    external_zone_wrapper = external_zone(model)
    external_source_zone = model_backed_zones(model)[0]
    external_groups: dict[
        tuple[str, str], list[tuple[EntityWrapper[ModelEntity], dict[str, Any]]]
    ] = defaultdict(list)
    for wrapper in model.modelEntities.get_many(f"{external_source_zone.entity.localFolderName}/"):
        for source in external_sources(model, wrapper):
            external_groups[(entity_product(wrapper), entity_module(wrapper))].append(
                (wrapper, source)
            )
    for (product, module), entries in external_groups.items():
        job_key = create_job_key(external_zone_wrapper, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": create_job_name(external_zone_wrapper, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": job_clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": [
                        {
                            "task_key": create_task_key(
                                external_zone_wrapper.entity.name,
                                product,
                                module,
                                source["table_name"],
                            ).lower(),
                            "notebook_path": notebook_job_path(
                                external_zone_wrapper, "ddl", wrapper, name=source["table_name"]
                            ),
                        }
                        for wrapper, source in entries
                    ],
                },
                output_path=Path(
                    "jobs", job_zone_slug(external_zone_wrapper), product, module, f"{job_key}.yml"
                ),
            )
        )
    return payloads


@register_payload("jobs/create_zone.yml.jinja2")
def jobs_create_zones(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for zone in [external_zone(model), *model_backed_zones(model)]:
        zone_folder = zone_folder_name(zone)
        module_jobs = [
            create_job_key(zone, product, module)
            for folder, product, module in entities_by_zone_and_module(model)
            if folder == zone_folder
        ]
        if not zone.entity.localFolderName:
            external_source_zone = model_backed_zones(model)[0]
            module_jobs = sorted(
                {
                    create_job_key(zone, entity_product(wrapper), entity_module(wrapper))
                    for wrapper in model.modelEntities.get_many(
                        f"{external_source_zone.entity.localFolderName}/"
                    )
                    if external_sources(model, wrapper)
                }
            )
        payloads.append(
            BasePayload(
                data={
                    "job_key": create_job_key(zone),
                    "job_name": create_job_name(zone),
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
                output_path=Path("jobs", job_zone_slug(zone), f"Create_{zone.entity.name}.yml"),
            )
        )
    return payloads


@register_payload("jobs/create_all.yml.jinja2")
def jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    zone_jobs = [create_job_key(zone) for zone in [external_zone(model), *model_backed_zones(model)]]
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


@register_payload("jobs/load_job_group.yml.jinja2")
def jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    grouped: dict[str, list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in model_entity_wrappers(model):
        grouped[job_property(wrapper)].append(wrapper)

    payloads: list[IPayload] = []
    for job_name, wrappers in grouped.items():
        cluster_variable = cluster_for_job(model, job_name)
        external_zone_wrapper = external_zone(model)
        external_tasks: list[dict[str, Any]] = []
        entity_tasks: list[dict[str, Any]] = []
        complete_dependencies: list[str] = []
        for wrapper in wrappers:
            previous_tasks: list[str] = ["Start_Load"]
            for source in external_sources(model, wrapper):
                task_key = create_task_key(
                    external_zone_wrapper.entity.name, source["table_name"], source["table_name"]
                ).lower()
                external_tasks.append(
                    {
                        "task_key": task_key,
                        "depends_on": previous_tasks,
                        "notebook_path": notebook_job_path(
                            external_zone_wrapper, "dml", wrapper, name=source["table_name"]
                        ),
                        "libraries": [],
                        "resolved_job_cluster_key": cluster_variable,
                    }
                )
                previous_tasks = [task_key]
            entity_task_key = create_task_key("load", *wrapper.locator.folders, wrapper.entity.name).lower()
            entity_tasks.append(
                {
                    "task_key": entity_task_key,
                    "depends_on": previous_tasks,
                    "notebook_path": notebook_job_path(model.get_zone_for_entity(wrapper), "dml", wrapper),
                    "resolved_job_cluster_key": cluster_variable,
                }
            )
            complete_dependencies.append(entity_task_key)
        payloads.append(
            BasePayload(
                data={
                    "job_key": f"Load_{job_name}",
                    "job_name": f"Load {job_name}",
                    "job_clusters": job_clusters(cluster_variable),
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


@register_payload("jobs/load_all.yml.jinja2")
def jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    job_names = sorted({job_property(wrapper) for wrapper in model_entity_wrappers(model)})
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
