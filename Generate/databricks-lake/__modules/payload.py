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
    _build_external_table_tag_inputs,
    _build_external_sources,
    _build_scd2_tracking_columns,
    _build_technical_columns,
    _external_mapping_projection,
    _resolve_product_module_context,
    _schema_columns,
)

logger = start_logger(__name__)


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
    include_external_timestamp: bool,
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
    if include_external_timestamp:
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


def _connector_wheel_workspace_path(connector_id: str | None) -> str | None:
    """Resolve workspace wheel path for a connector id based on bundled utils wheels."""
    if not connector_id:
        return None
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(connector_id).strip().lower()).strip("_")
    if not normalized:
        return None

    connectors_dir = Path("Output", "databricks-lake", "connectors")
    pattern = f"datam8_plugin_{normalized}-*.whl"
    matches = sorted(connectors_dir.glob(pattern))
    if not matches:
        return None

    # Choose latest wheel deterministically by filename.
    wheel_name = matches[-1].name
    return f"${{workspace.root_path}}/files/connectors/{wheel_name}"


def _attach_external_task_connector_wheels(data: dict[str, Any]) -> None:
    """Attach connector wheel libraries to external-source tasks based on their data source connector."""
    external_tasks = data.get("external_tasks") or []
    for task in external_tasks:
        wheel_path = _connector_wheel_workspace_path(task.get("connector_id"))
        if not wheel_path:
            continue
        task["libraries"] = [{"whl": wheel_path}]


@register_payload("ddl_notebook.py.jinja2")
def generate_ddl_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-external) entities."""
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

        if not resolver.is_model_backed_zone(zone_meta):
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

        product_info, module_info, data_product_name, data_module_name = _resolve_product_module_context(
            resolver,
            locator,
        )
        identifiers = resolver.modeled_table_identifiers(locator, entity.name)

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
        table_tags = merge_table_tags(entity, product_info, module_info, resolver=resolver)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity, resolver=resolver)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        payloads.append(
            BasePayload(
                data={
                    "zone": zone_meta.name,
                    "zone_display": zone_meta.display_name,
                    "data_product": data_product_name,
                    "data_module": data_module_name,
                    "table_name": entity.name,
                    "full_table_name": identifiers["full_table_name"],
                    "table_comment": entity.description or "",
                    "columns": columns,
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
                    *resolver.output_folder_segments(locator),
                    f"{locator.entityName or entity.name}.py",
                ),
            )
        )

    return payloads


@register_payload("ddl_notebook_external.py.jinja2")
def generate_external_ddl_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit external-source DDL notebooks for every discovered external source."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    external_zone = resolver.default_external_zone()
    if external_zone is None:
        logger.warning("No external zone without localFolderName found. External DDL notebooks will be skipped.")
        return payloads

    external_zone_folder = resolver.zone_folder_name(external_zone)

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue
        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None or not resolver.is_target_zone(zone_meta):
            continue

        column_tags = collect_column_tags(entity, resolver=resolver, include_attribute_tags=False)
        refactored_columns = collect_refactored_columns(entity)
        product_info, module_info, _, _ = _resolve_product_module_context(
            resolver,
            locator,
        )

        for source, data_source_info in resolver.iter_external_sources(entity):
            identifiers = resolver.external_table_identifiers(locator, source)
            data_product_name = identifiers["data_product"]
            data_module_name = identifiers["data_module"]
            external_name = identifiers["table_name"]
            full_table_name = identifiers["full_table_name"]
            external_columns = resolver.build_external_columns(entity, source)
            external_imports = collect_imports(external_columns)
            source_alias = getattr(source, "sourceAlias", None) or external_name
            source_properties = resolver.source_properties(source)
            entity_properties = resolver.entity_properties(entity)

            table_properties_input, table_display_tags = _build_external_table_tag_inputs(
                resolver=resolver,
                product_info=product_info,
                module_info=module_info,
                entity_properties=entity_properties,
                source_properties=source_properties,
            )

            table_properties = build_delta_table_properties(table_properties_input)
            table_tags_output = format_table_tag_values(table_display_tags)

            payloads.append(
                BasePayload(
                    data={
                        "zone": external_zone.name,
                        "zone_display": external_zone.display_name,
                        "data_source": getattr(source, "dataSource", ""),
                        "data_source_display": getattr(data_source_info, "displayName", None)
                        or getattr(source, "dataSource", ""),
                        "data_product": data_product_name,
                        "data_module": data_module_name,
                        "table_name": external_name,
                        "source_name": source_alias,
                        "table_comment": entity.description or "",
                        "full_table_name": full_table_name,
                        "columns": external_columns,
                        "imports": external_imports,
                        "partitions": ["__Year", "__Month", "__Day", "__InsertTimestampUTC"],
                        "table_tags_repr": repr(table_tags_output),
                        "table_properties": table_properties,
                        "column_tags": column_tags,
                        "refactored_columns": refactored_columns,
                    },
                    output_path=Path(
                        "notebooks",
                        external_zone_folder,
                        "ddl",
                        *resolver.output_folder_segments(locator),
                        f"{external_name}.py",
                    ),
                )
            )

    return payloads


@register_payload("dml_notebook.py.jinja2", order=2)
def generate_dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Generate DML notebooks for zones backed by local model folders."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    locator_payload_key = "dml_transformations"
    external_zone = resolver.default_external_zone()
    source_zone_name = external_zone.name if external_zone else "external"

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if not resolver.is_model_backed_zone(zone_meta):
            logger.debug("Skipping unsupported zone '%s' for Databricks DML: %s", zone_meta.name, locator)
            continue

        product_info, module_info, data_product_name, data_module_name = _resolve_product_module_context(
            resolver,
            locator,
        )
        identifiers = resolver.modeled_table_identifiers(locator, entity.name)
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

        external_sources = resolver.external_sources(locator, entity)
        stage_sources = _build_external_sources(resolver, entity, external_sources, source_zone_name)

        transformations = resolver.collect_transformations(locator, entity)
        cache_key = (locator_payload_key, tuple(locator.folders), locator.entityName)
        cache.set(cache_key, transformations)

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
            source_mode = "external_delta"

        write_mode = resolver.write_mode(locator, entity, default="overwrite")
        spark_write_mode = {"overwrite": "overwrite", "append": "append"}.get(write_mode, "overwrite")
        merge_conditions = [f"tgt.`{col}` <=> src.`{col}`" for col in business_keys]
        merge_condition_flat = " AND ".join(merge_conditions) if merge_conditions else ""
        include_external_timestamp = source_mode == "external_delta"
        include_source_table = source_mode == "external_delta"
        include_business_function = not has_external_source
        schema_columns = _schema_columns(
            attribute_names=attribute_names,
            include_external_timestamp=include_external_timestamp,
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
            include_external_timestamp,
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
        external_merge_config = merge_config if merge_enabled and stage_sources else None
        final_merge_config = merge_config if merge_enabled and transformations else None

        data = {
            "zone": zone_meta.name,
            "zone_display": zone_meta.display_name,
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": entity.name,
            "full_table_name": identifiers["full_table_name"],
            "history": history_config,
            "write_mode": write_mode,
            "spark_write_mode": spark_write_mode,
            "source_mode": source_mode,
            "external_sources": stage_sources,
            "transformations": transformations,
            "final_function_key": transformations[-1]["key"] if transformations else None,
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
            "external_merge_config": external_merge_config,
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
                    *resolver.output_folder_segments(locator),
                    f"{locator.entityName or entity.name}.py",
                ),
            )
        )

    return payloads


@register_payload("dml_notebook_external.py.jinja2", order=2)
def generate_external_dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Generate DML notebooks for external-source ingestion zones."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    external_zone = resolver.default_external_zone()
    if external_zone is None:
        logger.warning("No external zone without localFolderName found. External DML notebooks will be skipped.")
        return payloads

    external_zone_folder = resolver.zone_folder_name(external_zone)

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        if not locator.folders:
            continue
        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None or not resolver.is_target_zone(zone_meta):
            continue

        write_mode = "append"

        for external_source in resolver.external_sources(locator, entity):
            external_name = external_source["table_name"]
            full_table_name = external_source["full_table_name"]
            data_source_name = external_source["data_source"]
            source_alias = external_source.get("source_alias") or external_name
            properties = external_source.get("properties", {})
            data_source_entry = resolver.data_sources.get(str(data_source_name).strip().lower())
            driver = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
            if getattr(data_source_entry, "type", None) == "SynapseDataSource":
                driver = "com.databricks.spark.sqldw"

            extract_mode = properties.get("extract_mode")
            if extract_mode == "overwrite":
                write_mode = "overwrite"
            else:
                write_mode = "append"

            mapping_entries = external_source.get("mapping_entries", [])
            mapping_projection = _external_mapping_projection(
                mapping_entries,
                resolver=resolver,
                data_source_name=data_source_name,
            )
            data_source_type = external_source.get("source_type") or getattr(data_source_entry, "type", None)
            connector_id = external_source.get("connector_id")
            source_location = external_source.get("source_location")
            source_location = (
                source_location.strip()
                if isinstance(source_location, str) and source_location.strip()
                else str(source_alias).strip()
            )
            is_query = source_location.upper().startswith("SELECT")

            data = {
                "zone": external_zone.name,
                "zone_display": external_zone.display_name,
                "data_source": data_source_name,
                "data_source_display": getattr(data_source_entry, "displayName", None) or data_source_name,
                "data_source_type": data_source_type,
                "use_connector": bool(connector_id),
                "connector_id": connector_id,
                "data_source_extended_properties": external_source.get("data_source_extended_properties") or {},
                "source_name": source_alias,
                "full_table_name": full_table_name,
                "write_mode": write_mode,
                "source_location": source_location,
                "is_query": is_query,
                "extract_mode": extract_mode,
                "driver": driver,
                "connection_secret_key": f"datasource-{data_source_name}-password",
                "mapping": external_source.get("mapping"),
                "mapping_entries": mapping_entries,
                "select_columns": mapping_projection["select_columns"],
                "target_columns": mapping_projection["target_columns"],
                "column_renames": mapping_projection["column_renames"],
                "delta_column_details": mapping_projection["delta_column_details"] or None,
                "delta_column": external_source.get("delta_column"),
                "source_delta_column": external_source.get("source_delta_column"),
            }

            payloads.append(
                BasePayload(
                    data=data,
                    output_path=Path(
                        "notebooks",
                        external_zone_folder,
                        "dml",
                        *resolver.output_folder_segments(locator),
                        f"{external_name}.py",
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
        if zone_meta is None or not resolver.is_model_backed_zone(zone_meta):
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
                        *resolver.output_folder_segments(locator),
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
    for zone in resolver.zones():
        if not resolver.is_target_zone(zone):
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
        variable_name = cluster.get("variable_name")
        if not variable_name:
            continue
        custom_tags: dict[str, str] = {}
        display_name = cluster.get("display_name")
        if display_name:
            custom_tags["friendly_name"] = repr(display_name)
        workload_type = cluster.get("workload_type")
        if workload_type:
            custom_tags["workload_type"] = repr(workload_type)

        cluster_entries.append(
            {
                "variable_name": variable_name,
                "description": f"Cluster settings for {cluster.get('name', variable_name)}",
                "spark_version": cluster.get("spark_version", "13.3.x-scala2.12"),
                "node_type": cluster.get("node_type", "Standard_D4ds_v5"),
                "num_workers": cluster.get("num_workers"),
                "autotermination_minutes": cluster.get("autotermination_minutes", 60),
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
        planner = JobsPlanner(model, resolver)
        plan = planner.build()
        cache.set(cache_key, plan)
        return plan


def _prepare_job_data(job: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Create template payload data while stripping non-template fields."""
    data = {k: v for k, v in job.items() if k != "output_path"}
    data.update(extra)
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
    """Emit one create job per zone, each chaining its module jobs."""
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("create_zones", []):
        data = _prepare_job_data(job)
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("jobs/create_module.yml.jinja2")
def generate_jobs_create_modules(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit concrete create jobs with notebook tasks for every module group."""
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    resolver = MetadataResolver(model)
    default_cluster = resolver.default_cluster_variable_name()
    for job in plan.get("create_modules", []):
        data = _prepare_job_data(job)
        if not data.get("tasks"):
            continue
        if not data.get("cluster_variable"):
            data["cluster_variable"] = default_cluster
        _assign_job_clusters(data, [data.get("cluster_variable")])
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("jobs/load_all.yml.jinja2")
def generate_jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit a single orchestration job that chains all load job groups."""
    plan = _get_jobs_plan(model, cache)
    job = plan.get("load_all")
    if not job:
        return []
    data = _prepare_job_data(job)
    return [BasePayload(data=data, output_path=job["output_path"])]


@register_payload("jobs/load_job_group.yml.jinja2")
def generate_jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit load jobs grouped by configured `jobs` property values."""
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("load_jobs", []):
        data = _prepare_job_data(job)
        _attach_external_task_connector_wheels(data)
        _assign_job_clusters(data, [data.get("cluster_variable")])
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads
