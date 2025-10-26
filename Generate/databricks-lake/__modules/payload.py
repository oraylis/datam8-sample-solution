from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache

from metadata_utils import (
    MetadataResolver,
    build_business_key_partitions,
    build_raw_source_name,
    collect_column_tags,
    collect_imports,
    collect_refactored_columns,
    merge_table_tags,
)

logger = start_logger(__name__)

TECHNICAL_COLUMNS = ["__InsertTimestampUTC", "__UpdateTimestampUTC", "__InsertTimestampRawUTC"]


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

        # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        columns = resolver.build_standard_columns(entity)
        imports = collect_imports(columns)
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        subfolders = tuple(locator.folders[1:]) + ("ddl",)

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
                    "imports": imports,
                    "partitions": partitions,
                    "table_tags_repr": repr(table_tags),
                    "column_tags": column_tags,
                    "refactored_columns": refactored_columns,
                },
                output_path=Path(
                    "notebooks",
                    zone_folder_name,
                    *subfolders,
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

        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)

        for source, data_source_info in resolver.iter_external_sources(entity):
            raw_name = build_raw_source_name(source)
            raw_columns = resolver.build_raw_columns(entity, source)
            raw_imports = collect_imports(raw_columns)
            subfolders = tuple(locator.folders[1:]) + ("ddl",)

            payloads.append(
                BasePayload(
                    data={
                        "zone": raw_zone.name,
                        "zone_display": raw_zone.display_name,
                        "data_source": getattr(source, "dataSource", ""),
                        "data_source_display": (data_source_info or {}).get(
                            "displayName", getattr(source, "dataSource", "")
                        ),
                        "source_name": raw_name,
                        "table_comment": entity.description or "",
                        "full_table_name": f"{getattr(source, 'dataSource', '')}_{raw_name}".strip("_"),
                        "columns": raw_columns,
                        "imports": raw_imports,
                        "partitions": ["__Year", "__Month", "__Day", "__InsertTimestampUTC"],
                        "table_tags_repr": repr({}),
                        "column_tags": column_tags,
                        "refactored_columns": refactored_columns,
                    },
                    output_path=Path(
                        "notebooks",
                        raw_zone_folder,
                        *subfolders,
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
            # Raw handled by dedicated payload.
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

        raw_sources = resolver.raw_sources(entity)
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
        insert_columns = TECHNICAL_COLUMNS + [f"`{name}`" for name in attribute_names]
        insert_values = [f"src.{col}" for col in TECHNICAL_COLUMNS] + [f"src.`{name}`" for name in attribute_names]
        update_assignments = [f"tgt.`{name}` = src.`{name}`" for name in non_business_columns]
        update_assignments_with_timestamp = update_assignments + ["tgt.__UpdateTimestampUTC = src.__UpdateTimestampUTC"]
        merge_condition_sql = "\n  AND ".join(merge_conditions) if merge_conditions else ""
        merge_condition_flat = " AND ".join(merge_conditions) if merge_conditions else ""
        insert_columns_sql = ",\n  ".join(insert_columns)
        insert_values_sql = ",\n  ".join(insert_values)
        update_assignments_sql = ",\n  ".join(update_assignments_with_timestamp)

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
            "insert_columns_sql": insert_columns_sql,
            "insert_values_sql": insert_values_sql,
            "merge_conditions_sql": merge_condition_sql,
            "merge_conditions_flat": merge_condition_flat,
            "update_assignments_sql": update_assignments_sql,
            "source_references": resolver.entity_source_references(entity),
            "has_lookup_dimensions": bool(dimension_lookups),
            "dimension_lookups": dimension_lookups,
        }

        payloads.append(
            BasePayload(
                data=data,
                output_path=Path(
                    "notebooks",
                    zone_folder_name,
                    *(tuple(locator.folders[1:]) + ("dml",)),
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

        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None
        write_mode = "append"

        raw_source_lookup = {
            info["raw_full_table"]: info for info in resolver.raw_sources(entity)
        }

        for source, data_source_info in resolver.iter_external_sources(entity):
            raw_name = build_raw_source_name(source)
            raw_full_table = f"{getattr(source, 'dataSource', '')}_{raw_name}".strip("_")
            raw_info = raw_source_lookup.get(raw_full_table, {})
            properties = raw_info.get("properties", {})
            data_source_entry = resolver.data_sources.get(getattr(source, "dataSource", ""), {})
            driver = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
            if data_source_entry.get("type") == "SynapseDataSource":
                driver = "com.databricks.spark.sqldw"

            data = {
                "zone": raw_zone.name,
                "zone_display": raw_zone.display_name,
                "data_source": getattr(source, "dataSource", ""),
                "data_source_display": (data_source_info or {}).get("displayName", getattr(source, "dataSource", "")),
                "source_name": raw_name,
                "full_table_name": raw_full_table,
                "write_mode": write_mode,
                "source_location": getattr(source, "sourceLocation", None),
                "extract_mode": properties.get("extract_mode"),
                "driver": driver,
                "connection_secret": f"datasource-{getattr(source, 'dataSource', '')}-connectionstring",
            }

            payloads.append(
                BasePayload(
                    data=data,
                    output_path=Path(
                        "notebooks",
                        raw_zone_folder,
                        *(tuple(locator.folders[1:]) + ("dml",)),
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
        if zone_meta is None or zone_meta.name == "raw":
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
                        *(tuple(locator.folders[1:]) + ("dml",)),
                        f"{locator.entityName}_functions",
                        transformation["script_name"],
                    ),
                )
            )

    return payloads
