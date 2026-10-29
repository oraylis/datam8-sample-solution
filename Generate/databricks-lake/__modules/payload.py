"""Payload builders for Databricks lake templates.

The module keeps Jinja payload contracts stable while shaping model metadata into
template-friendly dictionaries. Helper functions below intentionally centralize
reused metadata assembly so DDL/DML payloads stay consistent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import Model
from datam8.utils import start_logger
from datam8.utils.cache import Cache

from metadata_utils import (
    MetadataResolver,
    attribute_property_equals,
    build_business_key_partitions,
    build_delta_table_properties,
    collect_column_tags,
    collect_imports,
    collect_refactored_columns,
    format_table_tag_values,
    merge_table_tags,
)
from jobs_helpers import JobsPlanner
from payload_helpers import (
    _build_raw_table_tag_inputs,
    _build_scd2_tracking_columns,
    _build_stage_sources,
    _build_technical_columns,
    build_create_table_sql,
    _raw_mapping_projection,
    _resolve_product_module_context,
    _schema_columns,
)

logger = start_logger(__name__)

MODELLED_ZONES = {"stage", "core", "curated"}
JOB_ZONES = MODELLED_ZONES | {"raw"}


def _assignment_literal(column: str, expression: str) -> dict[str, str]:
    """Represent a merge assignment with a ready-to-use Python literal."""
    return {"column": column, "expression": repr(expression)}


def _scd0_helper_name(column: str) -> str:
    """Generate a deterministic helper column name for SCD0 preservation."""
    sanitized = re.sub(r"\W+", "_", column or "").strip("_")
    if not sanitized:
        sanitized = "value"
    return f"__scd0__{sanitized}"


def _build_insert_assignments(
    attribute_names: Sequence[str],
    include_raw_timestamp: bool,
    include_source_table: bool,
    include_business_function: bool = False,
) -> list[dict[str, str]]:
    """Create default insert assignments for merge statements."""
    assignments: list[dict[str, str]] = []
    technical_columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
    if include_business_function:
        technical_columns.append("__BusinessFunction")
    if include_source_table:
        technical_columns.append("__SourceTable")
    if include_raw_timestamp:
        technical_columns.append("__InsertTimestampRawUTC")

    for column in technical_columns:
        assignments.append(_assignment_literal(column, f"src.{column}"))

    for name in attribute_names:
        assignments.append(_assignment_literal(name, f"src.`{name}`"))

    return assignments


def _surrogate_key_columns(entity: Any) -> list[str]:
    """Return attribute names flagged as surrogate keys via attribute_type property."""
    columns: list[str] = []
    for attribute in getattr(entity, "attributes", []) or []:
        if attribute_property_equals(attribute, "attribute_type", "sk"):
            columns.append(attribute.name)
    return columns


@register_payload("ddl_notebook.py.jinja2")
def generate_ddl_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-raw) entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name not in MODELLED_ZONES:
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

        product_info, module_info, data_product_name, data_module_name = _resolve_product_module_context(
            resolver,
            locator,
        )

        # Assemble shared metadata for the standard notebook.
        foreign_key_columns = resolver.foreign_key_columns(entity)
        modeled_columns = resolver.build_standard_columns(
            entity,
            foreign_key_columns=foreign_key_columns,
        )
        entity_sources = getattr(entity, "sources", []) or []
        has_external_source = any(getattr(source, "dataSource", None) for source in entity_sources)
        technical_columns = _build_technical_columns(
            resolver,
            has_external_source=has_external_source,
        )
        columns = technical_columns + modeled_columns
        history_config = resolver.history_configuration(entity)
        scd2_tracking_columns: list[dict[str, Any]] = []
        if history_config.get("scd2"):
            scd2_tracking_columns = _build_scd2_tracking_columns(resolver)
            columns.extend(scd2_tracking_columns)
        imports = collect_imports(columns)
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        full_table_name = f"{data_product_name}_{data_module_name}_{entity.name}"
        table_comment = entity.description or ""
        create_sql = build_create_table_sql(
            zone=zone_meta.name,
            full_table_name=full_table_name,
            columns=columns,
            partitions=partitions,
            table_comment=table_comment,
            table_properties=table_properties,
        )
        payloads.append(
            BasePayload(
                data={
                    "zone": zone_meta.name,
                    "zone_display": zone_meta.display_name,
                    "data_product": data_product_name,
                    "data_module": data_module_name,
                    "table_name": entity.name,
                    "full_table_name": full_table_name,
                    "table_comment": table_comment,
                    "columns": columns,
                    "create_sql": create_sql,
                    "has_scd2_history": bool(history_config.get("scd2")),
                    "imports": imports,
                    "partitions": partitions,
                    "table_tags_repr": repr(table_tags_output),
                    "table_properties": table_properties,
                    "column_tags": column_tags,
                    "refactored_columns": refactored_columns,
                },
                output_path=Path(
                    "notebooks",
                    zone_folder_name,
                    "ddl",
                    *tuple(locator.folders[1:]),
                    f"{locator.entityName or entity.name}.py",
                ),
            )
        )

    return payloads


@register_payload("ddl_notebook_raw.py.jinja2")
def generate_raw_ddl_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit raw DDL notebooks for every external source discovered on entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    raw_zone = resolver.zone_by_name("raw")
    if raw_zone is None:
        logger.warning("Raw zone metadata not found. Raw DDL notebooks will be skipped.")
        return payloads

    raw_zone_folder = resolver.zone_folder_name(raw_zone)

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        column_tags = collect_column_tags(entity, include_attribute_tags=False)
        refactored_columns = collect_refactored_columns(entity)
        product_info, module_info, data_product_name, data_module_name = _resolve_product_module_context(
            resolver,
            locator,
        )

        for source, data_source_info in resolver.iter_external_sources(entity):
            identifiers = resolver.raw_table_identifiers(locator, source)
            raw_name = identifiers["table_name"]
            full_table_name = identifiers["full_table_name"]
            raw_columns = resolver.build_raw_columns(entity, source)
            raw_imports = collect_imports(raw_columns)
            source_alias = getattr(source, "sourceAlias", None) or raw_name
            source_properties = resolver.source_properties(source)
            entity_properties = resolver.entity_properties(entity)

            table_properties_input, table_display_tags = _build_raw_table_tag_inputs(
                product_info=product_info,
                module_info=module_info,
                entity_properties=entity_properties,
                source_properties=source_properties,
            )

            table_properties = build_delta_table_properties(table_properties_input)
            table_tags_output = format_table_tag_values(table_display_tags)
            table_comment = entity.description or ""
            create_sql = build_create_table_sql(
                zone=raw_zone.name,
                full_table_name=full_table_name,
                columns=raw_columns,
                partitions=["__Year", "__Month", "__Day", "__InsertTimestampUTC"],
                table_comment=table_comment,
                table_properties=table_properties,
            )

            payloads.append(
                BasePayload(
                    data={
                        "zone": raw_zone.name,
                        "zone_display": raw_zone.display_name,
                        "data_source": getattr(source, "dataSource", ""),
                        "data_source_display": getattr(data_source_info, "displayName", None)
                        or getattr(source, "dataSource", ""),
                        "data_product": data_product_name,
                        "data_module": data_module_name,
                        "table_name": raw_name,
                        "source_name": source_alias,
                        "table_comment": table_comment,
                        "full_table_name": full_table_name,
                        "columns": raw_columns,
                        "create_sql": create_sql,
                        "imports": raw_imports,
                        "partitions": ["__Year", "__Month", "__Day", "__InsertTimestampUTC"],
                        "table_tags_repr": repr(table_tags_output),
                        "table_properties": table_properties,
                        "column_tags": column_tags,
                        "refactored_columns": refactored_columns,
                    },
                    output_path=Path(
                        "notebooks",
                        raw_zone_folder,
                        "ddl",
                        *tuple(locator.folders[1:]),
                        f"{raw_name}.py",
                    ),
                )
            )

    return payloads


@register_payload("dml_notebook.py.jinja2", order=2)
def generate_dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Generate DML notebooks for modeled (non-raw) entities (stage/core/curated)."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    locator_payload_key = "dml_transformations"

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name == "raw":
            continue

        if zone_meta.name not in MODELLED_ZONES:
            logger.debug("Skipping unsupported zone '%s' for Databricks DML: %s", zone_meta.name, locator)
            continue

        product_info, module_info, data_product_name, data_module_name = _resolve_product_module_context(
            resolver,
            locator,
        )
        zone_folder_name = resolver.zone_folder_name(zone_meta)

        history_config = resolver.history_configuration(entity)
        attribute_names = resolver.attribute_names(entity)
        entity_sources = getattr(entity, "sources", []) or []
        has_external_source = any(getattr(source, "dataSource", None) for source in entity_sources)
        business_keys = history_config["business_keys"]
        non_business_columns = [name for name in attribute_names if name not in business_keys]
        scd0_columns = history_config["scd0"]
        scd1_columns = history_config["scd1"]
        scd2_columns = history_config["scd2"]
        scd1_non_business = [name for name in scd1_columns if name not in business_keys]
        scd2_non_business = [name for name in scd2_columns if name not in business_keys]
        surrogate_key_columns = _surrogate_key_columns(entity)
        surrogate_key_column_set = set(surrogate_key_columns)

        raw_sources = resolver.raw_sources(locator, entity)
        stage_sources = _build_stage_sources(
            resolver,
            entity,
            raw_sources,
            cast_to_model=has_external_source,
        )

        transformations = resolver.collect_transformations(locator, entity)
        cache_key = (locator_payload_key, tuple(locator.folders), locator.entityName)
        cache.set(cache_key, transformations)

        execution_transformations = transformations
        model_sources = []
        if not transformations and not stage_sources:
            model_sources = resolver.model_source_projection(entity)
            if len(model_sources) > 1:
                raise ValueError(
                    f"Entity {entity.name} has multiple modeled sources but no transformation; "
                    "define an explicit function to combine them."
                )
            if model_sources:
                execution_transformations = [
                    {
                        "key": "__model_source_projection",
                        "name": "Modeled source projection",
                        "kind": "model_source",
                        "source_projection": model_sources[0],
                    }
                ]

        lookup_dimensions_enabled = resolver.has_lookup_dimensions(entity)
        dimension_lookups = (
            resolver.dimension_lookups_for_fact(locator, entity)
            if lookup_dimensions_enabled
            else []
        )
        calculated_columns = resolver.calculated_columns(entity)

        source_mode = "none"
        if transformations:
            source_mode = "transformation"
        elif stage_sources:
            source_mode = "raw_delta"
        elif model_sources:
            source_mode = "transformation"

        write_mode = resolver.write_mode(entity, product_info, module_info, default="overwrite")
        spark_write_mode = {"overwrite": "overwrite", "append": "append"}.get(write_mode, "overwrite")
        merge_conditions = [f"tgt.`{col}` <=> src.`{col}`" for col in business_keys]
        merge_condition_flat = " AND ".join(merge_conditions) if merge_conditions else ""
        include_raw_timestamp = source_mode == "raw_delta"
        include_source_table = source_mode == "raw_delta"
        include_business_function = not has_external_source
        schema_columns = _schema_columns(
            attribute_names=attribute_names,
            include_raw_timestamp=include_raw_timestamp,
            include_source_table=include_source_table,
            include_business_function=include_business_function,
        )
        write_schema_columns = [
            column for column in schema_columns if column not in surrogate_key_column_set
        ]
        assignment_attribute_names = attribute_names
        scd1_merge_columns = scd1_non_business
        scd2_merge_columns = scd2_non_business
        if write_mode == "merge" and surrogate_key_column_set:
            assignment_attribute_names = [
                name for name in attribute_names if name not in surrogate_key_column_set
            ]
            scd1_merge_columns = [
                name for name in scd1_non_business if name not in surrogate_key_column_set
            ]
            scd2_merge_columns = [
                name for name in scd2_non_business if name not in surrogate_key_column_set
            ]
        insert_assignments = _build_insert_assignments(
            assignment_attribute_names,
            include_raw_timestamp,
            include_source_table,
            include_business_function=include_business_function,
        )
        scd1_update_assignments = [
            _assignment_literal(name, f"src.`{name}`") for name in scd1_merge_columns
        ]
        if scd1_update_assignments:
            scd1_update_assignments.append(_assignment_literal("__UpdateTimestampUTC", "src.__UpdateTimestampUTC"))
        scd1_change_condition_sql = " OR ".join(
            f"NOT (tgt.`{column}` <=> src.`{column}`)" for column in scd1_merge_columns
        )
        scd0_helper_columns = [
            {"column": column, "helper": _scd0_helper_name(column)} for column in scd0_columns
        ]
        scd0_helper_lookup = {entry["column"]: entry["helper"] for entry in scd0_helper_columns}

        merge_enabled = write_mode == "merge" and bool(business_keys)
        merge_config = {
            "enabled": merge_enabled,
            "has_scd2_history": bool(scd2_columns),
            "business_keys": business_keys,
            "scd0_helper_lookup": scd0_helper_lookup,
            "scd0_helper_columns": scd0_helper_columns,
            "scd2_non_business_columns": scd2_merge_columns,
            "scd1_update_assignments": scd1_update_assignments,
            "scd1_change_condition": scd1_change_condition_sql,
            "insert_assignments": insert_assignments,
            "merge_condition": merge_condition_flat,
        }
        raw_merge_config = merge_config if merge_enabled and stage_sources else None
        final_merge_config = merge_config if merge_enabled and (transformations or model_sources) else None

        data = {
            "zone": zone_meta.name,
            "zone_display": zone_meta.display_name,
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": entity.name,
            "full_table_name": f"{data_product_name}_{data_module_name}_{entity.name}",
            "history": history_config,
            "write_mode": write_mode,
            "spark_write_mode": spark_write_mode,
            "source_mode": source_mode,
            "raw_sources": stage_sources,
            "transformations": execution_transformations,
            "model_sources": model_sources,
            "final_function_key": execution_transformations[-1]["key"] if execution_transformations else None,
            "business_keys": business_keys,
            "non_business_columns": non_business_columns,
            "attribute_columns": attribute_names,
            "schema_columns": schema_columns,
            "write_schema_columns": write_schema_columns,
            "merge_conditions_flat": merge_condition_flat,
            "source_references": resolver.entity_source_references(entity),
            "has_lookup_dimensions": bool(dimension_lookups),
            "dimension_lookups": dimension_lookups,
            "insert_assignments": insert_assignments,
            "scd0_columns": scd0_columns,
            "scd0_helper_columns": scd0_helper_columns,
            "scd0_helper_lookup": scd0_helper_lookup,
            "scd1_columns": scd1_columns,
            "scd1_non_business_columns": scd1_non_business,
            "scd2_columns": scd2_columns,
            "scd2_non_business_columns": scd2_non_business,
            "has_scd2_history": bool(scd2_columns),
            "raw_merge_config": raw_merge_config,
            "final_merge_config": final_merge_config,
            "calculated_columns": calculated_columns,
        }

        payloads.append(
            BasePayload(
                data=data,
                output_path=Path(
                    "notebooks",
                    zone_folder_name,
                    "dml",
                    *tuple(locator.folders[1:]),
                    f"{locator.entityName or entity.name}.py",
                ),
            )
        )

    return payloads


@register_payload("dml_notebook_raw.py.jinja2", order=2)
def generate_raw_dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Generate DML notebooks for raw entities / external sources."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    raw_zone = resolver.zone_by_name("raw")
    if raw_zone is None:
        logger.warning("Raw zone metadata not found. Raw DML notebooks will be skipped.")
        return payloads

    raw_zone_folder = resolver.zone_folder_name(raw_zone)

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        if not locator.folders:
            continue

        write_mode = "append"

        for raw_source in resolver.raw_sources(locator, entity):
            raw_name = raw_source["table_name"]
            full_table_name = raw_source["full_table_name"]
            data_source_name = raw_source["data_source"]
            source_alias = raw_source.get("source_alias") or raw_name
            properties = raw_source.get("properties", {})
            data_source_entry = resolver.data_sources.get(data_source_name)
            extract_mode = properties.get("extract_mode")
            if extract_mode in {"overwrite", "full", "query"}:
                write_mode = "overwrite"
            else:
                write_mode = "append"

            mapping_entries = raw_source.get("mapping_entries", [])
            if extract_mode == "delta" and (not raw_source.get("delta_column") or not raw_source.get("source_delta_column")):
                raise ValueError(f"{full_table_name}: delta extraction requires a mapped extract_column=delta cursor")
            mapping_projection = _raw_mapping_projection(
                mapping_entries,
                resolver=resolver,
                data_source_name=data_source_name,
            )
            source_type = next((item.entity for item in model.dataSourceTypes.values() if item.entity.name == data_source_entry.type), None)
            plugin = getattr(source_type, "pluginId", None)
            if plugin not in {"sqlserver", "oracle", "mysql", "postgresql", "http_api"}:
                raise ValueError(f"Unsupported UC source plugin for {data_source_name}: {plugin}")
            extended = data_source_entry.extendedProperties or {}
            connection_name = extended.get("unityCatalogConnection", plugin)
            remote_database = extended.get("service_name") if plugin == "oracle" else extended.get("database")
            if plugin != "http_api" and not remote_database:
                raise ValueError(f"Data source {data_source_name} requires a database/service binding")
            external = next(source for source in entity.sources if getattr(source, "dataSource", None) == data_source_name and str(source.sourceLocation) == str(raw_source["source_location"]))
            raw_columns = resolver.build_raw_columns(entity, external)
            by_name = {column["name"]: column["delta_type"] for column in raw_columns if not column["name"].startswith("__")}
            http_columns = [{"name": entry["source"], "type": by_name[entry["target"]], "nullable": True} for entry in mapping_entries if entry.get("source") and entry.get("target") in by_name]


            data = {
                "zone": raw_zone.name,
                "zone_display": raw_zone.display_name,
                "data_source": data_source_name,
                "data_source_display": getattr(data_source_entry, "displayName", None) or data_source_name,
                "source_name": source_alias,
                "full_table_name": full_table_name,
                "write_mode": write_mode,
                "source_location": raw_source.get("source_location"),
                "connection_name": connection_name,
                "plugin": plugin,
                "remote_query_database": remote_database or "",
                "http_columns_repr": repr(http_columns),
                "target_types": by_name,
                "extract_mode": extract_mode,
                "target_columns": mapping_projection["target_columns"],
                "column_renames": mapping_projection["column_renames"],
                "delta_column": raw_source.get("delta_column"),
                "source_delta_column": raw_source.get("source_delta_column"),
            }

            payloads.append(
                BasePayload(
                    data=data,
                    output_path=Path(
                        "notebooks",
                        raw_zone_folder,
                        "dml",
                        *tuple(locator.folders[1:]),
                        f"{raw_name}.py",
                    ),
                )
            )

    return payloads


@register_payload("dml_function.py.jinja2", order=2)
def generate_dml_function_scripts(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Copy transformation function scripts into the notebook output."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    locator_payload_key = "dml_transformations"

    for locator, wrapper in model.modelEntities.items():
        if not locator.folders:
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None or zone_meta.name not in MODELLED_ZONES:
            continue

        cache_key = (locator_payload_key, tuple(locator.folders), locator.entityName)
        try:
            transformations = cache.get(cache_key)
        except KeyError:
            transformations = None
        if transformations is None:
            transformations = resolver.collect_transformations(locator, wrapper.entity)

        if not transformations:
            continue

        zone_folder_name = resolver.zone_folder_name(zone_meta)

        for transformation in transformations:
            payloads.append(
                BasePayload(
                    data={"content": transformation["script_content"]},
                    output_path=Path(
                        "notebooks",
                        zone_folder_name,
                        "dml",
                        *tuple(locator.folders[1:]),
                        f"{locator.entityName}_functions",
                        transformation["script_name"],
                    ),
                )
            )

    return payloads


@register_payload("schema.yml.jinja2")
def generate_schema_resources(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit Databricks bundle schema definitions for every configured zone."""
    resolver = MetadataResolver(model)
    schemas = []
    allowed_zone_names = JOB_ZONES
    for zone in resolver.zones():
        if zone.name.lower() not in allowed_zone_names:
            continue
        target_name = zone.target_name or zone.name
        resource_slug = re.sub(r"[^A-Za-z0-9]+", "_", target_name or zone.name).strip("_").lower()
        if not resource_slug:
            resource_slug = "default"
        resource_key = f"schema_{resource_slug}"
        schemas.append(
            {
                "resource_key": resource_key,
                "schema_name": target_name,
                "comment": zone.display_name or "",
            }
        )

    if not schemas:
        return []

    data = {"schemas": schemas}
    return [
        BasePayload(
            data=data,
            output_path=Path("schemas", "schema.yml"),
        )
    ]



@register_payload("clusters/clusters.yml.jinja2")
def generate_cluster_resources(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit dedicated cluster resources for bundle deployment."""
    resolver = MetadataResolver(model)
    clusters = resolver.cluster_definitions()
    if not clusters:
        return []

    cluster_entries: list[dict[str, Any]] = []
    for cluster in clusters:
        if cluster.get("serverless"):
            continue
        variable_name = cluster.get("variable_name")
        if not variable_name:
            continue
        custom_tags: dict[str, str] = {}
        display_name = cluster.get("display_name")
        if display_name:
            custom_tags["friendly_name"] = display_name
        workload_type = cluster.get("workload_type")
        if workload_type:
            custom_tags["workload_type"] = workload_type

        cluster_entries.append(
            {
                "variable_name": variable_name,
                "description": f"Cluster settings for {cluster.get('name', variable_name)}",
                "spark_version": cluster.get("spark_version", "13.3.x-scala2.12"),
                "node_type": cluster.get("node_type", "Standard_D4ds_v5"),
                "driver_node_type": cluster.get("driver_node_type"),
                "num_workers": cluster.get("num_workers"),
                "data_security_mode": cluster.get("data_security_mode", "STANDARD"),
                "runtime_engine": cluster.get("runtime_engine", "STANDARD"),
                "custom_tags": custom_tags or None,
            }
        )

    if not cluster_entries:
        return []

    return [
        BasePayload(
            data={"clusters": cluster_entries},
            output_path=Path("clusters", "clusters.yml"),
        )
    ]


def _get_jobs_plan(model: Model, cache: Cache) -> dict[str, Any]:
    """Resolve and cache the Databricks job plan built from model metadata."""
    cache_key = ("databricks_jobs_plan",)
    try:
        return cache.get(cache_key)
    except KeyError:
        resolver = MetadataResolver(model)
        planner = JobsPlanner(model, resolver, modelled_zones=JOB_ZONES)
        plan = planner.build()
        cache.set(cache_key, plan)
        return plan


def _prepare_job_data(job: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Create template payload data while stripping non-template fields."""
    data = {k: v for k, v in job.items() if k != "output_path"}
    data.update(extra)
    data.setdefault("job_clusters", [])
    data.setdefault("default_job_cluster_key", None)
    return data


def _assign_job_clusters(data: dict[str, Any], cluster_vars: Iterable[str]) -> None:
    """Populate job cluster descriptors based on the requested variable names."""
    unique_keys: list[str] = []
    for var in cluster_vars:
        if not var:
            continue
        if var not in unique_keys:
            unique_keys.append(var)
    if not unique_keys:
        return
    clusters = [{"job_cluster_key": key} for key in unique_keys]
    data["job_clusters"] = clusters
    data["default_job_cluster_key"] = clusters[0]["job_cluster_key"]


@register_payload("jobs/create_all.yml.jinja2")
def generate_jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit a single orchestration job that chains all create-zone jobs."""
    plan = _get_jobs_plan(model, cache)
    job = plan.get("create_all")
    if not job:
        return []
    data = _prepare_job_data(job)
    return [BasePayload(data=data, output_path=job["output_path"])]


@register_payload("jobs/create_zone.yml.jinja2")
def generate_jobs_create_zones(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit one create job per zone with independent entity DDL tasks."""
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    resolver = MetadataResolver(model)
    create_all = resolver.job_definition("create_all") or {}
    create_cluster = create_all.get("cluster") or {}
    default_cluster = None if create_cluster.get("serverless") else create_cluster.get("variable_name")
    if not create_cluster:
        default_cluster = resolver.default_cluster_variable_name()
    for job in plan.get("create_zones", []):
        data = _prepare_job_data(job)
        if not data.get("cluster_variable"):
            data["cluster_variable"] = default_cluster
        data["serverless"] = bool(create_cluster.get("serverless"))
        data["environment_version"] = create_cluster.get("environment_version", "6")
        _assign_job_clusters(data, [data.get("cluster_variable")])
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("jobs/load_job_group.yml.jinja2")
def generate_jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit load jobs grouped by configured `jobs` property values."""
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("load_jobs", []):
        data = _prepare_job_data(job)
        _assign_job_clusters(data, [data.get("cluster_variable")])
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("runtime_file.jinja2")
def shared_source_runtime(model: Model, cache: Cache) -> Sequence[IPayload]:
    source = Path(__file__).resolve().parents[2] / "shared" / "uc_sources.py"
    return [BasePayload(data={"content": source.read_text(encoding="utf-8")}, output_path=Path("runtime", "uc_sources.py"))]


@register_payload("runtime_file.jinja2", order=5)
def generation_manifest(model: Model, cache: Cache) -> Sequence[IPayload]:
    import json
    resolver = MetadataResolver(model)
    names = {}
    wrappers = []
    for locator, wrapper in model.modelEntities.items():
        if not locator.folders:
            continue
        zone = resolver.zone_from_folder(locator.folders[0])
        if zone is None or zone.name not in MODELLED_ZONES:
            continue
        name = "_".join([*locator.folders[1:], wrapper.entity.name]).lower()
        names[wrapper.entity.id] = zone.name + "." + name
        wrappers.append((locator, wrapper))
    datasets = {}
    for locator, wrapper in wrappers:
        entity = wrapper.entity
        key = names[entity.id]
        zone, name = key.split(".", 1)
        model_job = resolver.resolve_property(locator, entity, "jobs")
        columns = [{"name": col["name"], "type": col["delta_type"], "nullable": col["delta_nullable"]} for col in resolver.build_standard_columns(entity)]
        datasets[key] = {"key": key, "zone": zone, "name": name, "kind": "delta_table", "entity_name": entity.name, "model_job": model_job, "columns": columns,
                         "keys": [item.name for item in entity.attributes if item.isBusinessKey],
                         "scd2": resolver.history_configuration(entity)["scd2"],
                         "surrogates": [item.name for item in entity.attributes if attribute_property_equals(item, "attribute_type", "SK")],
                         "relationships": [{"dataset": names[item.targetLocation], "attributes": [{"source": pair.sourceName, "target": pair.targetName} for pair in item.attributes]} for item in entity.relationships or [] if item.targetLocation in names], "helper": None}
        for external, _ in resolver.iter_external_sources(entity):
            raw = resolver.raw_table_identifiers(locator, external)
            raw_key = "raw." + raw["full_table_name"].lower()
            data_source = resolver.data_sources[external.dataSource]
            source_type = next(item.entity for item in model.dataSourceTypes.values() if item.entity.name == data_source.type)
            plugin = source_type.pluginId
            settings = data_source.extendedProperties or {}
            extract_mode = next((reference.value for reference in external.properties or [] if reference.property == "extract_mode"), "full")
            external_spec = {"source": data_source.name, "plugin": plugin, "connection_suffix": settings.get("unityCatalogConnection", plugin), "location": external.sourceLocation, "database": settings.get("database"), "service_name": settings.get("service_name"), "extract_mode": extract_mode}
            cursors = [mapping for mapping in external.mapping or [] if any(ref.property == "extract_column" and ref.value == "delta" for ref in mapping.properties or [])]
            if extract_mode == "delta":
                if len(cursors) != 1:
                    raise ValueError(f"{raw_key}: delta extraction requires exactly one mapped cursor")
                external_spec.update(cursor_column=cursors[0].sourceName, target_cursor_column=cursors[0].targetName)
            if raw_key in datasets and datasets[raw_key].get("model_job") != model_job:
                raise ValueError(f"{raw_key}: external raw data is assigned to multiple model jobs; model the source in one job and reference its modeled dataset from other jobs")
            datasets[raw_key] = {"key": raw_key, "zone": "raw", "name": raw["full_table_name"].lower(), "kind": "delta_table", "model_job": model_job, "external": external_spec,
                                 "columns": [{"name": col["name"], "type": col["delta_type"], "nullable": col["delta_nullable"]} for col in resolver.build_raw_columns(entity, external) if not col["name"].startswith("__")],
                                 "keys": [], "scd2": [], "surrogates": [], "relationships": [], "helper": None}
    jobs_plan = _get_jobs_plan(model, cache)
    create_job = jobs_plan.get("create_all")
    load_jobs = jobs_plan.get("load_jobs", [])
    execution_plan = {
        "create": {"job": create_job["job_key"], "depends_on": []} if create_job else None,
        "load": [
            {"job": job["job_key"], "model_job": job["job_value"], "depends_on": job["upstream_job_dependencies"]}
            for job in load_jobs
        ],
    }
    manifest = {"target": "databricks", "lifecycle": [phase for phase, value in execution_plan.items() if value], "execution_plan": execution_plan, "datasets": list(datasets.values())}
    return [BasePayload(data={"content": json.dumps(manifest, indent=2) + "\n"}, output_path=Path("manifest.json"))]
