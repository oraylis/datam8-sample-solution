from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
import re

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache

from metadata_utils import (
    MetadataResolver,
    build_business_key_partitions,
    build_delta_table_properties,
    collect_column_tags,
    collect_imports,
    collect_refactored_columns,
    format_table_tag_values,
    merge_table_tags,
)
from jobs_helpers import JobsPlanner

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


def _build_insert_assignments(attribute_names: Sequence[str], include_raw_timestamp: bool) -> list[dict[str, str]]:
    """Create default insert assignments for merge statements."""
    assignments: list[dict[str, str]] = []
    technical_columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
    if include_raw_timestamp:
        technical_columns.append("__InsertTimestampRawUTC")

    for column in technical_columns:
        assignments.append(_assignment_literal(column, f"src.{column}"))

    for name in attribute_names:
        assignments.append(_assignment_literal(name, f"src.`{name}`"))

    return assignments


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

        # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        modeled_columns = resolver.build_standard_columns(entity)
        entity_sources = getattr(entity, "sources", []) or []
        has_external_source = any(getattr(source, "dataSource", None) for source in entity_sources)
        technical_columns: list[dict[str, Any]] = [
            resolver.build_column_from_canonical(
                name="__InsertTimestampUTC",
                canonical="datetime",
                nullable=False,
                comment="Load timestamp (UTC)",
                data_type_model=None,
            ),
            resolver.build_column_from_canonical(
                name="__UpdateTimestampUTC",
                canonical="datetime",
                nullable=False,
                comment="Last update timestamp (UTC)",
                data_type_model=None,
            ),
        ]
        if has_external_source:
            technical_columns.append(
                resolver.build_column_from_canonical(
                    name="__InsertTimestampRawUTC",
                    canonical="datetime",
                    nullable=False,
                    comment="Raw load timestamp (UTC)",
                    data_type_model=None,
                )
            )
        else:
            technical_columns.append(
                resolver.build_column_from_canonical(
                    name="__BusinessFunction",
                    canonical="string",
                    nullable=False,
                    comment="Business function marker",
                    data_type_model=None,
                )
            )
        columns = technical_columns + modeled_columns
        history_config = resolver.history_configuration(entity)
        scd2_tracking_columns: list[dict[str, Any]] = []
        if history_config.get("scd2"):
            scd2_tracking_columns = [
                resolver.build_column_from_canonical(
                    name="__ValidFrom",
                    canonical="datetime",
                    nullable=False,
                    comment="SCD2 start date",
                    data_type_model=None,
                ),
                resolver.build_column_from_canonical(
                    name="__ValidTo",
                    canonical="datetime",
                    nullable=False,
                    comment="SCD2 end date",
                    data_type_model=None,
                ),
                resolver.build_column_from_canonical(
                    name="__IsCurrent",
                    canonical="boolean",
                    nullable=False,
                    comment="SCD2 current flag",
                    data_type_model=None,
                ),
            ]
            columns.extend(scd2_tracking_columns)
        imports = collect_imports(columns)
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
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
                    "full_table_name": f"{data_product_name}_{data_module_name}_{entity.name}",
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
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None
        data_product_name = (
            product_info.name
            if product_info
            else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        )
        data_module_name = (
            module_info.name
            if module_info
            else (locator.folders[2] if len(locator.folders) >= 3 else "General")
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

            base_table_tags: dict[str, Any] = {}
            if product_info:
                base_table_tags.update(product_info.properties)
            if module_info:
                base_table_tags.update(module_info.properties)

            table_properties_input = dict(base_table_tags)
            table_properties_input.update(entity_properties)
            if source_properties:
                table_properties_input.update(source_properties)

            table_display_tags = dict(base_table_tags)
            if source_properties:
                table_display_tags.update(source_properties)

            table_properties = build_delta_table_properties(table_properties_input)
            table_tags_output = format_table_tag_values(table_display_tags)

            payloads.append(
                BasePayload(
                    data={
                        "zone": raw_zone.name,
                        "zone_display": raw_zone.display_name,
                        "data_source": getattr(source, "dataSource", ""),
                        "data_source_display": (data_source_info or {}).get(
                            "displayName", getattr(source, "dataSource", "")
                        ),
                        "data_product": data_product_name,
                        "data_module": data_module_name,
                        "table_name": raw_name,
                        "source_name": source_alias,
                        "table_comment": entity.description or "",
                        "full_table_name": full_table_name,
                        "columns": raw_columns,
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

        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")
        zone_folder_name = resolver.zone_folder_name(zone_meta)

        history_config = resolver.history_configuration(entity)
        attribute_names = resolver.attribute_names(entity)
        business_keys = history_config["business_keys"]
        non_business_columns = [name for name in attribute_names if name not in business_keys]
        scd0_columns = history_config["scd0"]
        scd1_columns = history_config["scd1"]
        scd2_columns = history_config["scd2"]
        scd1_non_business = [name for name in scd1_columns if name not in business_keys]
        scd2_non_business = [name for name in scd2_columns if name not in business_keys]

        raw_sources = resolver.raw_sources(locator, entity)
        stage_sources = []
        for raw_source in raw_sources:
            select_exprs = resolver.stage_select_expressions(entity, raw_source)
            stage_sources.append(
                {
                    "key": f"Raw_{raw_source['raw_full_table']}",
                    "data_source": raw_source["data_source"],
                    "raw_full_table": raw_source["raw_full_table"],
                    "source_zone": "raw",
                    "select_expressions": select_exprs,
                    "properties": raw_source["properties"],
                }
            )

        transformations = resolver.collect_transformations(locator, entity)
        cache_key = (locator_payload_key, tuple(locator.folders), locator.entityName)
        cache.set(cache_key, transformations)

        lookup_dimensions_enabled = resolver.has_lookup_dimensions(entity)
        dimension_lookups = (
            resolver.dimension_lookups_for_fact(locator, entity)
            if lookup_dimensions_enabled
            else []
        )

        source_mode = "none"
        if transformations:
            source_mode = "transformation"
        elif stage_sources:
            source_mode = "raw_delta"

        write_mode = resolver.write_mode(entity, product_info, module_info, default="overwrite")
        spark_write_mode = {"overwrite": "overwrite", "append": "append"}.get(write_mode, "overwrite")
        merge_conditions = [f"tgt.`{col}` <=> src.`{col}`" for col in business_keys]
        merge_condition_flat = " AND ".join(merge_conditions) if merge_conditions else ""
        include_raw_timestamp = source_mode == "raw_delta"
        insert_assignments = _build_insert_assignments(attribute_names, include_raw_timestamp)
        scd1_update_assignments = [
            _assignment_literal(name, f"src.`{name}`") for name in scd1_non_business
        ]
        if scd1_update_assignments:
            scd1_update_assignments.append(_assignment_literal("__UpdateTimestampUTC", "src.__UpdateTimestampUTC"))
        scd1_change_condition_sql = " OR ".join(
            f"NOT (tgt.`{column}` <=> src.`{column}`)" for column in scd1_non_business
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
            "scd2_non_business_columns": scd2_non_business,
            "scd1_update_assignments": scd1_update_assignments,
            "scd1_change_condition": scd1_change_condition_sql,
            "insert_assignments": insert_assignments,
            "merge_condition": merge_condition_flat,
        }
        raw_merge_config = merge_config if merge_enabled and stage_sources else None
        final_merge_config = merge_config if merge_enabled and transformations else None

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
            "transformations": transformations,
            "final_function_key": transformations[-1]["key"] if transformations else None,
            "business_keys": business_keys,
            "non_business_columns": non_business_columns,
            "attribute_columns": attribute_names,
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
            data_source_entry = resolver.data_sources.get(data_source_name, {})
            driver = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
            if data_source_entry.get("type") == "SynapseDataSource":
                driver = "com.databricks.spark.sqldw"

            extract_mode = properties.get("extract_mode")
            if extract_mode == "overwrite":
                write_mode = "overwrite"
            else:
                write_mode = "append"

            mapping_entries = raw_source.get("mapping_entries", [])
            select_columns = [
                {
                    "target": entry.get("target"),
                    "source": entry.get("source"),
                }
                for entry in mapping_entries
                if entry.get("target") and entry.get("source")
            ]

            data = {
                "zone": raw_zone.name,
                "zone_display": raw_zone.display_name,
                "data_source": data_source_name,
                "data_source_display": data_source_entry.get("displayName", data_source_name),
                "source_name": source_alias,
                "full_table_name": full_table_name,
                "write_mode": write_mode,
                "source_location": raw_source.get("source_location"),
                "extract_mode": extract_mode,
                "driver": driver,
                "connection_secret": f"datasource-{data_source_name}-connectionstring",
                "mapping": raw_source.get("mapping"),
                "mapping_entries": mapping_entries,
                "select_columns": select_columns,
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



def _get_jobs_plan(model: Model, cache: Cache) -> dict[str, Any]:
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
    data = {k: v for k, v in job.items() if k != "output_path"}
    data.update(extra)
    return data


@register_payload("jobs/create_all.yml.jinja2")
def generate_jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    plan = _get_jobs_plan(model, cache)
    job = plan.get("create_all")
    if not job:
        return []
    data = _prepare_job_data(job, cluster_var="cluster_id")
    return [BasePayload(data=data, output_path=job["output_path"])]


@register_payload("jobs/create_zone.yml.jinja2")
def generate_jobs_create_zones(model: Model, cache: Cache) -> Sequence[IPayload]:
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("create_zones", []):
        data = _prepare_job_data(job, cluster_var="cluster_id")
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("jobs/create_module.yml.jinja2")
def generate_jobs_create_modules(model: Model, cache: Cache) -> Sequence[IPayload]:
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("create_modules", []):
        data = _prepare_job_data(
            job,
            cluster_var="cluster_id",
        )
        if not data.get("tasks"):
            continue
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads


@register_payload("jobs/load_all.yml.jinja2")
def generate_jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    plan = _get_jobs_plan(model, cache)
    job = plan.get("load_all")
    if not job:
        return []
    data = _prepare_job_data(job, cluster_var="cluster_id")
    return [BasePayload(data=data, output_path=job["output_path"])]


@register_payload("jobs/load_job_group.yml.jinja2")
def generate_jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    plan = _get_jobs_plan(model, cache)
    payloads: list[IPayload] = []
    for job in plan.get("load_jobs", []):
        data = _prepare_job_data(job)
        payloads.append(BasePayload(data=data, output_path=job["output_path"]))
    return payloads
