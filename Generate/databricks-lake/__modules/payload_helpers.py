"""Shared helper functions for Databricks payload shaping.

The helpers in this module are payload-oriented transformation utilities used
by `payload.py` to prepare template input dictionaries.
"""

from __future__ import annotations

from typing import Any

from metadata_utils import MetadataResolver


def _resolve_product_module_context(
    resolver: MetadataResolver,
    locator: Any,
) -> tuple[Any | None, Any | None, str, str]:
    """Resolve product/module folder metadata and derive fallback-safe names."""
    return resolver.product_module_context(locator)


def _build_technical_columns(
    resolver: MetadataResolver,
    *,
    has_external_source: bool,
) -> list[dict[str, Any]]:
    """Build standard technical columns used in modeled DDL tables."""
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
        technical_columns.extend(
            [
                resolver.build_column_from_canonical(
                    name="__InsertTimestampRawUTC",
                    canonical="datetime",
                    nullable=False,
                    comment="Raw load timestamp (UTC)",
                    data_type_model=None,
                ),
                resolver.build_column_from_canonical(
                    name="__SourceTable",
                    canonical="string",
                    nullable=False,
                    comment="Origin reference for the record",
                    data_type_model=None,
                ),
            ]
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
    return technical_columns


def _build_scd2_tracking_columns(resolver: MetadataResolver) -> list[dict[str, Any]]:
    """Build additional tracking columns for SCD2 tables."""
    return [
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


def _build_external_table_tag_inputs(
    *,
    resolver: MetadataResolver,
    product_info: Any | None,
    module_info: Any | None,
    entity_properties: dict[str, Any],
    source_properties: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build two tag maps: one for Delta properties and one for rendered table tags."""
    base_table_tags: dict[str, Any] = {}
    if product_info:
        base_table_tags.update(
            {
                key: value
                for key, value in product_info.properties.items()
                if resolver.property_supports_folder_scope(key)
            }
        )
    if module_info:
        base_table_tags.update(
            {
                key: value
                for key, value in module_info.properties.items()
                if resolver.property_supports_folder_scope(key)
            }
        )

    table_properties_input = dict(base_table_tags)
    table_properties_input.update(entity_properties)
    table_properties_input.update(source_properties)

    table_display_tags = dict(base_table_tags)
    table_display_tags.update(source_properties)
    return table_properties_input, table_display_tags


def _build_external_sources(
    resolver: MetadataResolver,
    entity: Any,
    external_sources: list[dict[str, Any]],
    source_zone: str,
) -> list[dict[str, Any]]:
    """Create external-source descriptors consumed by modeled DML template rendering."""
    stage_sources: list[dict[str, Any]] = []
    for external_source in external_sources:
        stage_sources.append(
            {
                "key": f"External_{external_source['external_full_table']}",
                "data_source": external_source["data_source"],
                "external_full_table": external_source["external_full_table"],
                "source_zone": source_zone,
                "select_expressions": resolver.stage_select_expressions(entity, external_source),
                "properties": external_source["properties"],
            }
        )
    return stage_sources


def _schema_columns(
    *,
    attribute_names: list[str],
    include_external_timestamp: bool,
    include_source_table: bool,
    include_business_function: bool,
) -> list[str]:
    """Build schema column order for DML write/select operations."""
    schema_columns = [
        "__InsertTimestampUTC",
        "__UpdateTimestampUTC",
    ]
    if include_business_function:
        schema_columns.append("__BusinessFunction")
    if include_source_table:
        schema_columns.append("__SourceTable")
    if include_external_timestamp:
        schema_columns.append("__InsertTimestampRawUTC")
    schema_columns.extend(attribute_names)
    return schema_columns


def _external_mapping_projection(
    mapping_entries: list[dict[str, Any]],
    *,
    resolver: MetadataResolver,
    data_source_name: str,
) -> dict[str, Any]:
    """Derive mapping-derived lists used by external extraction templates."""
    select_columns = [
        {
            "target": entry.get("target"),
            "source": entry.get("source"),
        }
        for entry in mapping_entries
        if entry.get("target") and entry.get("source")
    ]

    column_renames: list[dict[str, str]] = []
    target_columns: list[str] = []
    delta_column_details: list[dict[str, Any]] = []
    for entry in mapping_entries:
        source_name = entry.get("source")
        target_name = entry.get("target")
        entry_props = entry.get("properties", {}) or {}
        is_delta_column = str(entry_props.get("extract_column", "") or "").strip().lower() == "delta"
        if target_name:
            target_columns.append(target_name)
        if source_name and target_name and source_name != target_name:
            column_renames.append({"source": source_name, "target": target_name})
        if is_delta_column and source_name:
            source_type = (entry.get("source_data_type") or {}).get("type")
            canonical_type = None
            if source_type:
                canonical_type = resolver.map_source_type_to_canonical(data_source_name, source_type) or source_type
            delta_column_details.append(
                {
                    "sourceName": source_name,
                    "canonicalDataType": canonical_type,
                }
            )

    return {
        "select_columns": select_columns,
        "column_renames": column_renames,
        "target_columns": target_columns,
        "delta_column_details": delta_column_details,
    }
