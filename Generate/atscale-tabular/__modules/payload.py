from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Locator, Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache

logger = start_logger(__name__)

CONSUMER_FOLDER = "030-Curated"  # generate SML from curated layer
DEFAULT_CATALOG_NAME = "datam8_catalog"
DEFAULT_MODEL_NAME = "Model"


@dataclass
class ColumnDefinition:
    name: str
    data_type: str
    source_column: str | None = None
    is_hidden: bool = False
    is_key: bool = False
    format_string: str | None = None

    def normalized_key(self) -> str:
        reference = self.source_column or self.name
        return _normalize(reference)


@dataclass
class MetricDefinition:
    name: str
    expression: str
    format_string: str | None = None


@dataclass
class TableDefinition:
    name: str
    locator: Locator
    entity_id: int
    columns: list[ColumnDefinition] = field(default_factory=list)
    metrics: list[MetricDefinition] = field(default_factory=list)
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


@dataclass
class RelationshipDefinition:
    name: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str


# helpers

def _normalize(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _normalize_path(value: str | None) -> str:
    if not value:
        return ""
    import re
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _locator_to_path(locator: Locator) -> str:
    parts: list[str] = []
    if locator.folders:
        first = locator.folders[0]
        parts.append(first.split("-", 1)[-1] if "-" in first else first)
        parts.extend(locator.folders[1:])

    if locator.entityName:
        parts.append(locator.entityName)

    if not parts:
        return ""

    return "/" + "/".join(parts)


def _map_data_type(attribute_type: str, logical_type: str) -> str:
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
    return mapping.get(logical_type.lower(), logical_type)


def _derive_table_name(entity: Any) -> str:
    return (entity.displayName or entity.name or "").strip() or entity.name


def _collect_mapping_lookup(sources: Sequence[Any]) -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    for source in sources or []:
        for mapping in getattr(source, "mapping", []) or []:
            key_target = _normalize(mapping.targetName)
            key_source = _normalize(mapping.sourceName)
            lookup[key_target] = (mapping.targetName, mapping.sourceName)
            lookup[key_source] = (mapping.targetName, mapping.sourceName)
    return lookup


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
            name=f"{_normalize_path(from_table_name)}_{_normalize_path(to_table_name)}_{_normalize_path(from_column_name)}",
            from_table=from_table_name,
            from_column=from_column_name,
            to_table=to_table_name,
            to_column=to_column_name,
        )
    )


def _collect_curated_tables(model: Model) -> list[TableDefinition]:
    tables: list[TableDefinition] = []
    for locator, wrapper in model.modelEntities.items():
        if not locator.folders or locator.folders[0] != CONSUMER_FOLDER:
            continue

        entity = wrapper.entity
        table_name = _derive_table_name(entity)
        table = TableDefinition(
            name=table_name,
            locator=locator,
            entity_id=entity.id,
            is_hidden=False,
        )

        mapping_lookup = _collect_mapping_lookup(entity.sources)

        for attribute in entity.attributes:
            expression = getattr(attribute, "expression", None)
            expression_language = getattr(attribute, "expressionLanguage", None)

            # AtScale metric from DAX measure (simple mapping for now)
            if expression and str(expression_language).lower() == "dax":
                table.metrics.append(
                    MetricDefinition(
                        name=attribute.displayName or attribute.name,
                        expression=expression,
                        format_string="#,##0" if attribute.dataType.type.lower() in {"long", "int", "double", "decimal"} else None,
                    )
                )
                continue

            normalized_name = _normalize(attribute.displayName or attribute.name)
            mapping = mapping_lookup.get(normalized_name)
            column_name = attribute.displayName or attribute.name
            source_column = None
            if mapping:
                column_name = mapping[0]
                source_column = mapping[1]

            data_type = _map_data_type(attribute.attributeType, attribute.dataType.type)
            is_integer = data_type == "int64"

            column = ColumnDefinition(
                name=column_name,
                data_type=data_type,
                source_column=source_column,
                is_hidden=False,
                is_key=attribute.attributeType.upper() == "SID",
                format_string="0" if is_integer and attribute.attributeType.upper() in {"SID", "ID"} else None,
            )
            table.register_column(column)

        tables.append(table)
    return tables


def _collect_relationships(model: Model, tables: list[TableDefinition]) -> list[RelationshipDefinition]:
    relationships: list[RelationshipDefinition] = []
    table_by_id: dict[int, TableDefinition] = {table.entity_id: table for table in tables}
    seen: set[tuple[str, str, str, str]] = set()

    for table in tables:
        entity = model.get_model_entity_by_id(table.entity_id).entity

        explicit_relationships = getattr(entity, "relationships", []) or []
        for relationship in explicit_relationships:
            attribute_mappings = getattr(relationship, "attributes", None)
            if attribute_mappings is None and isinstance(relationship, dict):
                attribute_mappings = relationship.get("attributes")
            if not attribute_mappings:
                continue

            # resolve target table via id reference when present
            target_location = getattr(relationship, "targetLocation", None)
            if target_location is None and isinstance(relationship, dict):
                target_location = relationship.get("targetLocation")
            target_table = table_by_id.get(target_location) if isinstance(target_location, int) else None

            if not target_table:
                # try fallback by name match
                for candidate in tables:
                    if candidate.name == getattr(relationship, "target", None):
                        target_table = candidate
                        break
            if not target_table:
                continue

            for mapping in attribute_mappings:
                source_name = getattr(mapping, "sourceName", None) or (mapping.get("sourceName") if isinstance(mapping, dict) else None)
                target_name = getattr(mapping, "targetName", None) or (mapping.get("targetName") if isinstance(mapping, dict) else None)

                from_column = _resolve_column(table, source_name)
                to_column = _resolve_column(target_table, target_name)

                if not (from_column and to_column):
                    continue

                _append_relationship(
                    relationships,
                    seen,
                    table.name,
                    from_column.name,
                    target_table.name,
                    to_column.name,
                )

    return relationships


# caching helpers

def _ensure_tables_cached(model: Model, cache: Cache) -> list[TableDefinition]:
    cache_key = ("atscale", "tables")
    try:
        tables: list[TableDefinition] = cache.get(cache_key)
    except KeyError:
        tables = _collect_curated_tables(model)
        cache.set(cache_key, tables)
    return tables


# payload registrations: Catalog, Model, Dataset, Metric

@register_payload("catalog.sml.jinja2", order=0)
def catalog_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    tables = _ensure_tables_cached(model, cache)
    # Try to infer catalog from first folder after zone
    names = sorted({
        table.locator.folders[1]
        for table in tables
        if len(table.locator.folders) >= 2
    })
    catalog_name = names[0] if names else DEFAULT_CATALOG_NAME
    data = {"catalog_name": catalog_name}
    return [
        BasePayload(
            data=data,
            output_path=Path("atscale-tabular", "Catalog.sml"),
        )
    ]


@register_payload("model.sml.jinja2", order=1)
def model_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    data = {
        "model_name": DEFAULT_MODEL_NAME,
    }
    return [
        BasePayload(
            data=data,
            output_path=Path("atscale-tabular", "Model.sml"),
        )
    ]


@register_payload("dataset.sml.jinja2", order=2)
def dataset_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    tables = _ensure_tables_cached(model, cache)
    # dataset contains tables and column schemas
    data = {
        "tables": tables,
    }
    return [
        BasePayload(
            data=data,
            output_path=Path("atscale-tabular", "Dataset.sml"),
        )
    ]


@register_payload("metric.sml.jinja2", order=3)
def metric_payload(model: Model, cache: Cache) -> Sequence[IPayload]:
    tables = _ensure_tables_cached(model, cache)
    metrics: list[MetricDefinition] = []
    for t in tables:
        metrics.extend(t.metrics)
    data = {"metrics": metrics}
    return [
        BasePayload(
            data=data,
            output_path=Path("atscale-tabular", "Metric.sml"),
        )
    ]
