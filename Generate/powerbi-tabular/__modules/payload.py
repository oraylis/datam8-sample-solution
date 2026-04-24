"""Payload builders for Power BI tabular (TMDL) generation.

The module collects consumer-layer entities and resolves relationships into
stable dataclass-based payloads for deterministic template rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import Locator, Model
from datam8.utils import start_logger
from datam8.utils.cache import Cache

logger = start_logger(__name__)

TARGET_NAME = "powerbi"
TARGET_PROPERTY_NAME = "target"
DEFAULT_DATABASE_NAME = "_Datam8 Sample Dataset"
DEFAULT_MODEL_NAME = "Model"


@dataclass
class ColumnDefinition:
    name: str
    data_type: str
    source_column: str | None = None
    is_hidden: bool = False
    is_key: bool = False
    summarize_by: str | None = None
    format_string: str | None = None
    is_available_in_mdx: bool | None = None

    def normalized_key(self) -> str:
        reference = self.source_column or self.name
        return _normalize(reference)

    @property
    def tmdl_name(self) -> str:
        return _quote_tmdl_identifier(self.name)


@dataclass
class MeasureDefinition:
    name: str
    expression: str
    format_string: str | None = None

    @property
    def tmdl_name(self) -> str:
        return _quote_tmdl_identifier(self.name)


@dataclass
class PartitionDefinition:
    name: str
    source_lines: list[str]
    mode: str = "import"

    @property
    def tmdl_name(self) -> str:
        return _quote_tmdl_identifier(self.name)


@dataclass
class TableDefinition:
    name: str
    locator: Locator
    entity_id: int
    columns: list[ColumnDefinition] = field(default_factory=list)
    measures: list[MeasureDefinition] = field(default_factory=list)
    partition: PartitionDefinition | None = None
    is_hidden: bool = False

    column_lookup: dict[str, ColumnDefinition] = field(default_factory=dict, init=False)

    def register_column(self, column: ColumnDefinition) -> None:
        self.columns.append(column)
        keys: Iterable[str] = {
            _normalize(column.name),
            _normalize(column.source_column) if column.source_column else "",
        }
        for key in keys:
            if key:
                self.column_lookup.setdefault(key, column)

    @property
    def tmdl_name(self) -> str:
        return _quote_tmdl_identifier(self.name)


@dataclass
class RelationshipDefinition:
    name: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str

    @property
    def from_column_ref(self) -> str:
        return f"{_quote_tmdl_identifier(self.from_table)}.{_quote_tmdl_identifier(self.from_column)}"

    @property
    def to_column_ref(self) -> str:
        return f"{_quote_tmdl_identifier(self.to_table)}.{_quote_tmdl_identifier(self.to_column)}"


def _quote_tmdl_identifier(value: str) -> str:
    """Quote TMDL identifiers that cannot be emitted bare."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'" if " " in value or "'" in value else escaped


def _normalize(value: str | None) -> str:
    """Normalize identifiers by keeping alphanumerics only and lowercasing."""
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _slug(value: str | None) -> str:
    """Create a slug token used in generated relationship names."""
    if not value:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return re.sub(r"_+", "_", slug).strip("_")


def _normalize_path(value: str | None) -> str:
    """Normalize a path-like reference for dictionary key comparisons."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _locator_to_path(locator: Locator) -> str:
    """Convert a locator into a model-like absolute path string."""
    parts: list[str] = []
    if locator.folders:
        first = locator.folders[0]
        match = re.match(r"\d{3}-(.+)", first)
        if match:
            parts.append(match.group(1))
        else:
            parts.append(first)
        parts.extend(locator.folders[1:])

    if locator.entityName:
        parts.append(locator.entityName)

    if not parts:
        return ""

    return "/" + "/".join(parts)


def _map_data_type(attribute_type: str, logical_type: str) -> str:
    """Map model data types to Power BI compatible data type names."""
    mapping: dict[str, str] = {
        "long": "int64",
        "int": "int64",
        "short": "int64",
        "double": "double",
        "decimal": "decimal",
        "bool": "boolean",
        "bit": "boolean",
        "string": "string",
        "datetime": "datetime",
        "date": "dateTime",
    }

    result = mapping.get(logical_type.lower())
    if result:
        return result

    logger.debug("Falling back to raw data type '%s' for attribute type '%s'", logical_type, attribute_type)
    return logical_type


def _is_fact_table(locator: Locator) -> bool:
    return any(folder.lower() == "fact" for folder in locator.folders)


def _derive_table_name(entity: Any) -> str:
    return (entity.displayName or entity.name or "").strip() or entity.name


def _collect_mapping_lookup(sources: Sequence[Any]) -> dict[str, tuple[str, str]]:
    """
    Build a lookup keyed by normalized target/source names returning the tuple (targetName, sourceName).
    """
    lookup: dict[str, tuple[str, str]] = {}

    for source in sources or []:
        for mapping in getattr(source, "mapping", []) or []:
            key_target = _normalize(mapping.targetName)
            key_source = _normalize(mapping.sourceName)
            lookup[key_target] = (mapping.targetName, mapping.sourceName)
            lookup[key_source] = (mapping.targetName, mapping.sourceName)

    return lookup


def _properties_to_dict(properties: Iterable[Any] | None) -> dict[str, Any]:
    """Convert iterable of property objects into a lower-cased dictionary."""
    result: dict[str, Any] = {}
    if not properties:
        return result
    for prop in properties:
        name = getattr(prop, "property", None)
        if not name:
            continue
        key = str(name).strip().lower()
        if key in result:
            continue
        result[key] = getattr(prop, "value", None)
    return result


def _target_zone_folders(model: Model) -> set[str]:
    """Return local folder names for zones that target this generator."""
    folders: set[str] = set()
    for wrapper in model.zones.values():
        zone_entity = wrapper.entity
        props = _properties_to_dict(getattr(zone_entity, "properties", None))
        target_value = props.get(TARGET_PROPERTY_NAME)
        if str(target_value or "").strip().lower() != TARGET_NAME:
            continue
        local_folder = getattr(zone_entity, "localFolderName", None)
        if local_folder:
            folders.add(str(local_folder))
    return folders


def _resolve_column(table: TableDefinition, column_name: str | None) -> ColumnDefinition | None:
    if not column_name:
        return None

    normalized = _normalize(column_name)
    column = table.column_lookup.get(normalized)
    if column:
        return column

    for candidate in table.columns:
        if _normalize(candidate.name) == normalized:
            return candidate
        if candidate.source_column and _normalize(candidate.source_column) == normalized:
            return candidate

    return None


def _resolve_relationship_target(
    target_location: Any,
    table_by_id: dict[int, TableDefinition],
    table_by_path: dict[str, TableDefinition],
) -> TableDefinition | None:
    if isinstance(target_location, int):
        return table_by_id.get(target_location)

    if isinstance(target_location, str):
        normalized = _normalize_path(target_location)
        if normalized:
            return table_by_path.get(normalized)

    return None


def _append_relationship(
    relationships: list[RelationshipDefinition],
    seen: set[tuple[str, str, str, str]],
    from_table_name: str,
    from_column_name: str,
    to_table_name: str,
    to_column_name: str,
) -> None:
    key = (
        _normalize_path(from_table_name),
        _normalize_path(from_column_name),
        _normalize_path(to_table_name),
        _normalize_path(to_column_name),
    )

    if key in seen:
        return

    seen.add(key)
    relationships.append(
        RelationshipDefinition(
            name=_format_relationship_name(from_table_name, to_table_name, from_column_name),
            from_table=from_table_name,
            from_column=from_column_name,
            to_table=to_table_name,
            to_column=to_column_name,
        )
    )


def _build_partition_lines(
    model: Model,
    table: TableDefinition,
    entity: Any,
    target_zone_folders: set[str],
) -> list[str]:
    for source in entity.sources:
        source_location = getattr(source, "sourceLocation", None)
        if not isinstance(source_location, int):
            continue

        try:
            referenced = model.get_model_entity_by_id(source_location)
        except Exception:  # noqa: BLE001 - fallback on missing references
            continue

        target_locator = referenced.locator
        # Skip relationships to entities in the same target scope; handled as model relationships.
        if target_locator.folders and target_locator.folders[0] in target_zone_folders:
            continue

        schema_name = _extract_schema_name(target_locator)
        object_name = _to_object_name(referenced.entity.name)

        return [
            "let",
            "    Source = Databricks.Catalogs(DBW_Hostname, DBW_HTTP_Path, [Catalog=null, Database=null, EnableAutomaticProxyDiscovery=null]),",
            '    Database = Source{[Name=DBW_Catalog,Kind="Database"]}[Data],',
            f'    Schema = Database{{[Name="{schema_name}",Kind="Schema"]}}[Data],',
            f'    View = Schema{{[Name="{object_name}",Kind="Table"]}}[Data]',
            "in",
            "    View",
        ]

    # Fallback for entities without model sources (e.g. Measures)
    return [
        "let",
        "    Source = Table.FromRows(Json.Document(Binary.Decompress(Binary.FromText(\"i44FAA==\", BinaryEncoding.Base64), Compression.Deflate)),",
        "        let _t = ((type nullable text) meta [Serialized.Text = true]) in type table [Column1 = _t]),",
        '    #"Changed Type" = Table.TransformColumnTypes(Source,{{"Column1", type text}}),',
        '    #"Removed Columns" = Table.RemoveColumns(#"Changed Type",{"Column1"})',
        "in",
        '    #"Removed Columns"',
    ]


def _extract_schema_name(locator: Locator) -> str:
    if not locator.folders:
        return "default"

    raw_zone = locator.folders[0]
    if "-" in raw_zone:
        raw_zone = raw_zone.split("-", 1)[1]

    return raw_zone.lower()


def _to_object_name(name: str | None) -> str:
    if not name:
        return ""

    return "".join(ch.lower() for ch in name if ch.isalnum())


def _format_relationship_name(from_table: str, to_table: str, column: str) -> str:
    return f"{_slug(from_table)}_{_slug(to_table)}_{_slug(column)}"


def _collect_target_tables(model: Model) -> list[TableDefinition]:
    """Collect target-zone entities and map them into table definitions."""
    tables: list[TableDefinition] = []
    target_zone_folders = _target_zone_folders(model)

    for locator, wrapper in model.modelEntities.items():
        if not locator.folders or locator.folders[0] not in target_zone_folders:
            continue

        entity = wrapper.entity
        table_name = _derive_table_name(entity)
        table = TableDefinition(
            name=table_name,
            locator=locator,
            entity_id=entity.id,
            is_hidden=_is_fact_table(locator),
        )

        mapping_lookup = _collect_mapping_lookup(entity.sources)

        for attribute in entity.attributes:
            expression = getattr(attribute, "expression", None)
            expression_language = getattr(attribute, "expressionLanguage", None)

            if expression and str(expression_language).lower() == "dax":
                measure = MeasureDefinition(
                    name=attribute.displayName or attribute.name,
                    expression=expression,
                    format_string="#,##0" if attribute.dataType.type.lower() in {"long", "int", "double", "decimal"} else None,
                )
                table.measures.append(measure)
                continue

            normalized_name = _normalize(attribute.displayName or attribute.name)
            mapping = mapping_lookup.get(normalized_name)

            column_name = attribute.displayName or attribute.name
            source_column = None

            if mapping:
                column_name = mapping[0]
                source_column = mapping[1]

            data_type = _map_data_type(attribute.attributeType, attribute.dataType.type)
            is_numeric = data_type in {"int64", "double", "decimal"}
            is_integer = data_type == "int64"

            column = ColumnDefinition(
                name=column_name,
                data_type=data_type,
                source_column=source_column,
                is_hidden=table.is_hidden,
                is_key=attribute.attributeType.upper() == "SID" and not table.is_hidden,
                summarize_by="none"
                if is_numeric and attribute.attributeType.upper() in {"SID", "ID"}
                else None,
                format_string="0"
                if is_integer and attribute.attributeType.upper() in {"SID", "ID"} and not table.is_hidden
                else None,
                is_available_in_mdx=False if table.is_hidden else None,
            )

            table.register_column(column)

        partition_lines = _build_partition_lines(model, table, entity, target_zone_folders)
        table.partition = PartitionDefinition(name=table.name, source_lines=partition_lines)
        tables.append(table)

    return tables


def _collect_relationships(model: Model, tables: list[TableDefinition]) -> list[RelationshipDefinition]:
    """Resolve explicit relationships and infer fallbacks when needed."""
    relationships: list[RelationshipDefinition] = []
    table_by_id: dict[int, TableDefinition] = {table.entity_id: table for table in tables}
    table_by_path: dict[str, TableDefinition] = {}

    for table in tables:
        path = _locator_to_path(table.locator)
        if path:
            table_by_path[_normalize_path(path)] = table

    seen: set[tuple[str, str, str, str]] = set()

    for table in tables:
        entity = model.get_model_entity_by_id(table.entity_id).entity

        explicit_relationships = getattr(entity, "relationships", []) or []
        explicit_target_ids: set[int] = set()
        for relationship in explicit_relationships:
            target_location = getattr(relationship, "targetLocation", None)

            target_table = _resolve_relationship_target(target_location, table_by_id, table_by_path)
            if not target_table:
                logger.debug(
                    "Unable to resolve target table for relationship on %s (target=%s)",
                    table.name,
                    target_location,
                )
                continue

            explicit_target_ids.add(target_table.entity_id)

            attribute_mappings = getattr(relationship, "attributes", None)
            if not attribute_mappings:
                continue

            for mapping in attribute_mappings:
                source_name = getattr(mapping, "sourceName", None)
                target_name = getattr(mapping, "targetName", None)

                from_column = _resolve_column(table, source_name)
                to_column = _resolve_column(target_table, target_name)

                from_column_name = from_column.name if from_column else source_name
                to_column_name = to_column.name if to_column else target_name

                if not to_column_name:
                    fallback_target = next((col for col in target_table.columns if col.is_key), None)
                    to_column_name = fallback_target.name if fallback_target else None

                if not from_column_name or not to_column_name:
                    logger.debug(
                        "Unable to resolve relationship columns for %s -> %s (%s -> %s)",
                        table.name,
                        target_table.name,
                        source_name,
                        target_name,
                    )
                    continue

                _append_relationship(
                    relationships,
                    seen,
                    table.name,
                    from_column_name,
                    target_table.name,
                    to_column_name,
                )

        # Fallback: infer from source references when explicit relationships are missing.
        for source in getattr(entity, "sources", []) or []:
            source_location = getattr(source, "sourceLocation", None)
            if not isinstance(source_location, int):
                continue

            target_table = table_by_id.get(source_location)
            if not target_table:
                continue
            if target_table.entity_id in explicit_target_ids:
                continue

            target_column = next((col for col in target_table.columns if col.is_key), None)
            if not target_column:
                continue

            lookup_keys = [
                _normalize(target_column.name),
                _normalize(target_column.source_column),
            ]

            from_column = None
            for key in lookup_keys:
                if not key:
                    continue
                from_column = table.column_lookup.get(key)
                if from_column:
                    break

            if not from_column:
                from_column = _resolve_column(table, target_column.name)

            from_column_name = from_column.name if from_column else None
            if not from_column_name:
                continue

            _append_relationship(
                relationships,
                seen,
                table.name,
                from_column_name,
                target_table.name,
                target_column.name,
            )

    return relationships


def _ensure_tables_cached(model: Model, cache: Cache) -> list[TableDefinition]:
    cache_key = ("powerbi", "tables")
    try:
        tables: list[TableDefinition] = cache.get(cache_key)
    except KeyError:
        tables = _collect_target_tables(model)
        cache.set(cache_key, tables)
    return tables


def _detect_database_name(tables: Sequence[TableDefinition]) -> str:
    names = sorted(
        {
            table.locator.folders[1]
            for table in tables
            if len(table.locator.folders) >= 2
        }
    )
    if not names:
        return DEFAULT_DATABASE_NAME

    if len(names) > 1:
        logger.warning(
            "Multiple target data products detected (%s); using '%s' for Power BI database name.",
            ", ".join(names),
            names[0],
        )

    return names[0]


@register_payload("database.tmdl.jinja2", order=0)
def database_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    tables = _ensure_tables_cached(model, cache)
    data = {
        "database_name": _detect_database_name(tables),
        "compatibility_level": 1550,
        "compatibility_mode": "powerBI",
    }
    return [
        BasePayload(
            data=data,
            output_path=Path("powerbi-tabular", "database.tmdl"),
        )
    ]


@register_payload("model.tmdl.jinja2", order=1)
def model_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    tables = _ensure_tables_cached(model, cache)

    data = {
        "model_name": DEFAULT_MODEL_NAME,
        "culture": "en-US",
        "default_data_source_version": "powerBI_V3",
        "source_query_culture": "de-DE",
        "table_names": [table.tmdl_name for table in tables],
    }

    return [
        BasePayload(
            data=data,
            output_path=Path("powerbi-tabular", "model.tmdl"),
        )
    ]


@register_payload("expressions.tmdl.jinja2", order=2)
def expressions_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    expressions = [
        {
            "name": "DBW_Catalog",
            "value": "datam8_catalog",
            "meta": {
                "IsParameterQuery": "true",
                "Type": "Text",
                "IsParameterQueryRequired": "true",
            },
        },
        {
            "name": "DBW_Hostname",
            "value": "adb-0000000000000000.12.azuredatabricks.net",
            "meta": {
                "IsParameterQuery": "true",
                "Type": "Text",
                "IsParameterQueryRequired": "true",
            },
        },
        {
            "name": "DBW_HTTP_Path",
            "value": "/sql/1.0/warehouses/0000000000000000",
            "meta": {
                "IsParameterQuery": "true",
                "Type": "Text",
                "IsParameterQueryRequired": "true",
            },
        },
    ]

    return [
        BasePayload(
            data={"expressions": expressions},
            output_path=Path("powerbi-tabular", "expressions.tmdl"),
        )
    ]


@register_payload("relationships.tmdl.jinja2", order=3)
def relationships_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit relationship payload for the model-level TMDL file."""
    tables: list[TableDefinition] = cache.get(("powerbi", "tables"))
    relationships = _collect_relationships(model, tables)

    return [
        BasePayload(
            data={"relationships": relationships},
            output_path=Path("powerbi-tabular", "relationships.tmdl"),
        )
    ]


@register_payload("table.tmdl.jinja2", order=4)
def table_payloads(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Emit one payload per table TMDL file."""
    tables: list[TableDefinition] = cache.get(("powerbi", "tables"))

    payloads: list[IPayload] = []
    for table in tables:
        payloads.append(
            BasePayload(
                data={"table": table},
                output_path=Path("powerbi-tabular", "tables", f"{table.name}.tmdl"),
            )
        )

    return payloads
