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


@register_payload("ddl_notebook.py.jinja2")
def generate_ddl_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """
    Build DDL payloads for every model entity plus raw notebooks for external sources.

    This function orchestrates metadata lookups via MetadataResolver and hands a concise
    data object to the shared template.
    """

    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    raw_zone = resolver.zone_by_name("raw")
    if raw_zone is None:
        logger.warning("Raw zone metadata not found. Raw DDL notebooks will be skipped.")

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

        payloads.append(
            BasePayload(
                data={
                    "kind": "standard",
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
                    *(locator.folders[1:]),
                    f"{locator.entityName or entity.name}.py",
                ),
            )
        )

        if raw_zone is None:
            continue

        # Emit a raw notebook per external source (if any).
        raw_zone_folder = resolver.zone_folder_name(raw_zone)
        for source, data_source_info in resolver.iter_external_sources(entity):
            raw_name = build_raw_source_name(source)
            raw_columns = resolver.build_raw_columns(entity, source)
            raw_imports = collect_imports(raw_columns)

            payloads.append(
                BasePayload(
                    data={
                        "kind": "raw",
                        "zone": raw_zone.name,
                        "zone_display": raw_zone.display_name,
                        "data_source": getattr(source, "dataSource", ""),
                        "data_source_display": (data_source_info or {}).get("displayName", getattr(source, "dataSource", "")),
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
                        *(locator.folders[1:]),
                        f"{raw_name}.py",
                    ),
                )
            )

    return payloads
