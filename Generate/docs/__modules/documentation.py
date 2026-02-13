from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from datam8 import config
from datam8.model import Locator, Model
from datam8.utils import start_logger

logger = start_logger(__name__)

ZONE_ORDER = ["raw", "stage", "core", "curated", "consumer"]
ZONE_COLORS: dict[str, tuple[str, str]] = {
    "raw": ("#FFF4E0", "#CC8B00"),
    "stage": ("#E0F2FF", "#0077B6"),
    "core": ("#E8F5E9", "#2E7D32"),
    "curated": ("#FCE4EC", "#AD1457"),
    "consumer": ("#EDE7F6", "#5E35B1"),
}
DEFAULT_NODE_COLORS = ("#DAE8FC", "#1F2A44")


def _slug(value: str | None) -> str:
    if not value:
        return "item"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug or "item"


def _convert_property_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes"}:
            return True
        if lowered in {"false", "no"}:
            return False
        if lowered in {"null", "none"}:
            return None
    return value


def _properties_to_dict(entries: Iterable[Any] | None) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if not entries:
        return props
    for entry in entries:
        name = getattr(entry, "property", None)
        if not name:
            continue
        props[name] = _convert_property_value(getattr(entry, "value", None))
    return props


def _format_data_type(data_type) -> str:
    if not data_type:
        return "string"
    type_name = getattr(data_type, "type", None) or "string"
    precision = getattr(data_type, "precision", None) or getattr(data_type, "numericPrecision", None)
    scale = getattr(data_type, "scale", None) or getattr(data_type, "numericScale", None)
    length = getattr(data_type, "length", None) or getattr(data_type, "charLen", None)
    if precision is not None and scale is not None:
        return f"{type_name}({precision},{scale})"
    if length is not None:
        return f"{type_name}({length})"
    return type_name


def _entity_kind(name: str | None, module: str | None) -> str:
    tokens = [(name or "").lower(), (module or "").lower()]
    for token in tokens:
        if "fact" in token:
            return "fact"
        if "dim" in token or "dimension" in token:
            return "dimension"
    return "entity"


def _relationship_label(mapping: list[dict[str, str]]) -> str:
    if not mapping:
        return ""
    parts = [f"{item['source']}->{item['target']}" for item in mapping if item.get("source") and item.get("target")]
    return ", ".join(parts)


def _mapping_label_from_docs(mapping_docs: Iterable[MappingDoc | dict[str, str]]) -> str:
    parts: list[str] = []
    for item in mapping_docs or []:
        if isinstance(item, MappingDoc):
            source = item.source
            target = item.target
        else:
            source = item.get("source")
            target = item.get("target")
        if source and target:
            parts.append(f"{source}->{target}")
    return ", ".join(parts)


@dataclass
class AttributeDoc:
    ordinal: int
    name: str
    description: str | None
    attribute_type: str | None
    data_type: str
    nullable: bool | None
    history: str | None
    is_business_key: bool
    is_surrogate_key: bool
    refactor_names: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class MappingDoc:
    target: str
    source: str
    source_data_type: str | None
    nullable: bool | None


@dataclass
class SourceDoc:
    kind: str
    reference: str
    name: str
    display_name: str | None
    zone: str | None
    product: str | None
    module: str | None
    path: str | None
    data_source_name: str | None
    data_source_display: str | None
    data_source_type: str | None
    source_alias: str | None
    location: str | None
    description: str | None
    properties: dict[str, Any] = field(default_factory=dict)
    mapping: list[MappingDoc] = field(default_factory=list)
    mapping_label: str | None = None
    entity_id: int | None = None
    external_key: str | None = None
    diagram_node_id: str | None = None


@dataclass
class RelationshipDoc:
    direction: str  # outgoing or incoming
    peer_id: int | None
    peer_name: str
    peer_display_name: str
    peer_zone: str
    peer_product: str | None
    peer_module: str | None
    path: str | None
    mapping: list[dict[str, str]] = field(default_factory=list)
    label: str = ""


@dataclass
class TransformationDoc:
    step_no: int | None
    kind: str | None
    name: str | None
    details: dict[str, Any] = field(default_factory=dict)
    code_path: str | None = None
    code_language: str | None = None
    code_excerpt: str | None = None


@dataclass
class CodeSnippet:
    name: str
    path: str
    language: str
    content: str


@dataclass
class EntityDoc:
    id: int | None
    name: str
    display_name: str
    description: str | None
    locator_path: str
    zone_name: str
    zone_display: str
    zone_folder: str | None
    zone_target: str | None
    product_name: str | None
    product_display: str | None
    module_name: str | None
    module_display: str | None
    folder_segments: list[str]
    breadcrumbs: list[str]
    slug_path: list[str]
    diagram_id: str
    entity_kind: str
    entity_properties: dict[str, Any]
    inherited_properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    attributes: list[AttributeDoc] = field(default_factory=list)
    attribute_summary: dict[str, Any] = field(default_factory=dict)
    sources: list[SourceDoc] = field(default_factory=list)
    source_summary: dict[str, Any] = field(default_factory=dict)
    relationships_out: list[RelationshipDoc] = field(default_factory=list)
    relationships_in: list[RelationshipDoc] = field(default_factory=list)
    relationship_summary: dict[str, Any] = field(default_factory=dict)
    transformations: list[TransformationDoc] = field(default_factory=list)
    code_snippets: list[CodeSnippet] = field(default_factory=list)


@dataclass
class ModuleSummary:
    product: str | None
    product_display: str | None
    module: str | None
    module_display: str | None
    entity_count: int = 0
    fact_count: int = 0
    dimension_count: int = 0


@dataclass
class ZoneSummary:
    name: str
    display_name: str
    folder: str | None
    target_name: str | None
    entity_count: int = 0
    module_summaries: list[ModuleSummary] = field(default_factory=list)


@dataclass
class DiagramNode:
    id: str
    label: str
    zone: str
    product: str | None
    module: str | None
    x: float
    y: float
    width: float
    height: float
    path: str
    fill_color: str
    stroke_color: str


@dataclass
class DiagramEdge:
    id: str
    source: str
    target: str
    label: str
    style: str


@dataclass
class DiagramModel:
    title: str
    name: str
    width: int
    height: int
    nodes: list[DiagramNode] = field(default_factory=list)
    edges: list[DiagramEdge] = field(default_factory=list)
    legend: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DocumentationResult:
    generated_at: str
    solution_name: str
    schema_version: str | None
    stats: dict[str, Any]
    zones: list[ZoneSummary]
    entities: list[EntityDoc]
    catalog_rows: list[dict[str, Any]]
    lineage_highlights: list[dict[str, Any]]
    diagram: DiagramModel


@dataclass(frozen=True)
class ZoneInfo:
    name: str
    display: str
    folder: str | None
    target: str | None


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    display: str | None


@dataclass(frozen=True)
class ProductInfo:
    name: str
    display: str | None
    modules: dict[str, ModuleInfo]


@dataclass(frozen=True)
class DataSourceInfo:
    name: str
    display_name: str | None
    source_type: str | None
    description: str | None


class DocumentationBuilder:
    def __init__(self, model: Model):
        self.model = model
        self.solution_root = config.solution_folder_path
        self.model_root = self.solution_root / model.solution.modelPath
        self._zone_lookup: dict[str, ZoneInfo] = self._load_zones()
        self._product_lookup: dict[str, ProductInfo] = self._load_data_products()
        self._data_sources: dict[str, DataSourceInfo] = self._load_data_sources()

    def build(self) -> DocumentationResult:
        generated_at = datetime.now(timezone.utc).isoformat()
        solution_name = getattr(self.model.solution, "name", None) or config.solution_path.stem
        schema_version = getattr(self.model.solution, "schemaVersion", None)

        entities = self._build_entities()
        zones = self._summarize_zones(entities)
        stats = self._compute_stats(entities, zones)
        catalog_rows = self._build_catalog_rows(entities)
        lineage_highlights = self._build_lineage_highlights(entities)
        diagram = self._build_diagram(entities)

        return DocumentationResult(
            generated_at=generated_at,
            solution_name=solution_name,
            schema_version=schema_version,
            stats=stats,
            zones=zones,
            entities=entities,
            catalog_rows=catalog_rows,
            lineage_highlights=lineage_highlights,
            diagram=diagram,
        )

    def _build_entities(self) -> list[EntityDoc]:
        docs: list[EntityDoc] = []
        for locator, wrapper in sorted(self.model.modelEntities.items(), key=lambda item: (item[0].folders, item[0].entityName or "")):
            docs.append(self._build_entity(locator, wrapper.entity))

        self._populate_inbound_relationships(docs)
        return docs

    def _build_entity(self, locator: Locator, entity) -> EntityDoc:
        folders = list(locator.folders)
        zone_folder = folders[0] if folders else None
        zone_info = self._zone_from_folder(zone_folder)
        product_folder = folders[1] if len(folders) >= 2 else None
        module_folder = folders[2] if len(folders) >= 3 else None
        product_info = self._product_lookup.get((product_folder or "").lower())
        module_info = (
            product_info.modules.get((module_folder or "").lower())
            if product_info
            else None
        )
        breadcrumbs = [
            value
            for value in [
                zone_info.display,
                product_info.display if product_info else product_folder,
                module_info.display if module_info else module_folder,
                entity.displayName or entity.name,
            ]
            if value
        ]
        slug_path = [
            _slug(zone_folder or zone_info.name),
            _slug(product_folder or (product_info.name if product_info else None)),
        ]
        if module_folder or (module_info.name if module_info else None):
            slug_path.append(_slug(module_folder or (module_info.name if module_info else None)))
        entity_slug = _slug(entity.name)
        entity_id = getattr(entity, "id", None)
        if entity_id is not None:
            entity_slug = f"{entity_slug}-{entity_id}"
        slug_path = [part for part in slug_path if part]
        slug_path.append(entity_slug)

        inherited_props: dict[str, dict[str, Any]] = {}

        attributes = self._build_attributes(entity)
        attribute_summary = self._summarize_attributes(attributes)
        sources = self._build_sources(locator, entity)
        source_summary = self._summarize_sources(sources)
        relationships = self._build_relationships(entity)
        transformations, code_snippets = self._build_transformations(locator, entity)

        doc = EntityDoc(
            id=entity_id,
            name=entity.name,
            display_name=entity.displayName or entity.name,
            description=getattr(entity, "description", None),
            locator_path="/".join([*folders, locator.entityName or entity.name]),
            zone_name=zone_info.name,
            zone_display=zone_info.display,
            zone_folder=zone_folder,
            zone_target=zone_info.target,
            product_name=product_folder,
            product_display=product_info.display if product_info else None,
            module_name=module_folder,
            module_display=module_info.display if module_info else None,
            folder_segments=folders,
            breadcrumbs=breadcrumbs,
            slug_path=slug_path,
            diagram_id=f"entity-{entity_id or _slug(entity.name)}",
            entity_kind=_entity_kind(entity.name, module_folder),
            entity_properties=_properties_to_dict(getattr(entity, "properties", [])),
            inherited_properties=inherited_props,
            attributes=attributes,
            attribute_summary=attribute_summary,
            sources=sources,
            source_summary=source_summary,
            relationships_out=relationships,
            transformations=transformations,
            code_snippets=code_snippets,
        )
        return doc

    def _build_attributes(self, entity) -> list[AttributeDoc]:
        attributes: list[AttributeDoc] = []
        for attr in getattr(entity, "attributes", []) or []:
            properties = _properties_to_dict(getattr(attr, "properties", []))
            attribute = AttributeDoc(
                ordinal=getattr(attr, "ordinalNumber", len(attributes) + 1),
                name=attr.name,
                description=getattr(attr, "description", None),
                attribute_type=getattr(attr, "attributeType", None),
                data_type=_format_data_type(getattr(attr, "dataType", None)),
                nullable=getattr(getattr(attr, "dataType", None), "nullable", None),
                history=getattr(attr, "history", None),
                is_business_key=getattr(attr, "isBusinessKey", False),
                is_surrogate_key=self._has_surrogate_key_flag(attr),
                refactor_names=list(getattr(attr, "refactorNames", []) or []),
                properties=properties,
            )
            attributes.append(attribute)
        attributes.sort(key=lambda attr: attr.ordinal)
        return attributes

    def _summarize_attributes(self, attributes: list[AttributeDoc]) -> dict[str, Any]:
        type_counter: Counter[str] = Counter()
        history_flags: set[str] = set()
        business_keys: list[str] = []
        surrogate_keys: list[str] = []
        nullable = 0

        for attr in attributes:
            type_counter[attr.data_type] += 1
            if attr.history:
                history_flags.add(str(attr.history))
            if attr.is_business_key:
                business_keys.append(attr.name)
            if attr.is_surrogate_key:
                surrogate_keys.append(attr.name)
            if attr.nullable:
                nullable += 1

        return {
            "total": len(attributes),
            "business_keys": business_keys,
            "surrogate_keys": surrogate_keys,
            "history_types": sorted(history_flags),
            "data_types": dict(type_counter),
            "nullable": nullable,
            "not_nullable": len(attributes) - nullable,
        }

    def _build_sources(self, locator: Locator, entity) -> list[SourceDoc]:
        sources: list[SourceDoc] = []
        for source in getattr(entity, "sources", []) or []:
            data_source_name = getattr(source, "dataSource", None)
            mapping_entries = []
            for mapping in getattr(source, "mapping", []) or []:
                source_type = getattr(getattr(mapping, "sourceDataType", None), "type", None)
                nullable = getattr(getattr(mapping, "sourceDataType", None), "nullable", None)
                mapping_entries.append(
                    MappingDoc(
                        target=getattr(mapping, "targetName", ""),
                        source=getattr(mapping, "sourceName", ""),
                        source_data_type=_format_data_type(getattr(mapping, "sourceDataType", None)) if source_type else None,
                        nullable=nullable,
                    )
                )
            properties = _properties_to_dict(getattr(source, "properties", []))
            source_location = getattr(source, "sourceLocation", None)
            mapping_label = _mapping_label_from_docs(mapping_entries)

            if data_source_name:
                entry = self._data_sources.get(data_source_name)
                raw_zone_display = self._raw_zone_info().display
                external_key = f"{data_source_name}:{getattr(source, 'sourceAlias', None) or source_location or getattr(entity, 'name', '')}"
                sources.append(
                    SourceDoc(
                        kind="external",
                        reference=data_source_name,
                        name=data_source_name,
                        display_name=entry.display_name if entry else None,
                        zone=raw_zone_display,
                        product=None,
                        module=None,
                        path=None,
                        data_source_name=data_source_name,
                        data_source_display=entry.display_name if entry else None,
                        data_source_type=entry.source_type if entry else None,
                        source_alias=getattr(source, "sourceAlias", None),
                        location=source_location,
                        description=entry.description if entry else None,
                        properties=properties,
                        mapping=mapping_entries,
                        mapping_label=mapping_label or None,
                        external_key=external_key,
                    )
                )
            else:
                resolved = self._resolve_entity_reference(source_location)
                if resolved:
                    target_locator, target_entity = resolved
                    zone_info = self._zone_from_folder(target_locator.folders[0] if target_locator.folders else None)
                    sources.append(
                        SourceDoc(
                            kind="model",
                            reference=str(source_location),
                            name=target_entity.name,
                            display_name=target_entity.displayName or target_entity.name,
                            zone=zone_info.display,
                            product=target_locator.folders[1] if len(target_locator.folders) >= 2 else None,
                            module=target_locator.folders[2] if len(target_locator.folders) >= 3 else None,
                            path="/".join([*target_locator.folders, target_locator.entityName or target_entity.name]),
                            data_source_name=None,
                            data_source_display=None,
                            data_source_type=None,
                            source_alias=getattr(source, "sourceAlias", None),
                            location=str(source_location),
                            description=getattr(target_entity, "description", None),
                            properties=properties,
                            mapping=mapping_entries,
                            mapping_label=mapping_label or None,
                            entity_id=getattr(target_entity, "id", None),
                        )
                    )
                else:
                    sources.append(
                        SourceDoc(
                            kind="reference",
                            reference=str(source_location),
                            name=str(source_location),
                            display_name=str(source_location),
                            zone=None,
                            product=None,
                            module=None,
                            path=None,
                            data_source_name=None,
                            data_source_display=None,
                            data_source_type=None,
                            source_alias=getattr(source, "sourceAlias", None),
                            location=str(source_location),
                            description=None,
                            properties=properties,
                            mapping=mapping_entries,
                            mapping_label=mapping_label or None,
                        )
                    )
        return sources

    def _build_relationships(self, entity) -> list[RelationshipDoc]:
        relationships: list[RelationshipDoc] = []
        for relation in getattr(entity, "relationships", []) or []:
            mapping = [
                {
                    "source": getattr(mapping_item, "sourceName", ""),
                    "target": getattr(mapping_item, "targetName", ""),
                }
                for mapping_item in getattr(relation, "attributes", []) or []
            ]
            resolved = self._resolve_entity_reference(getattr(relation, "targetLocation", None))
            if resolved:
                locator, target_entity = resolved
                zone_info = self._zone_from_folder(locator.folders[0] if locator.folders else None)
                relationships.append(
                    RelationshipDoc(
                        direction="outgoing",
                        peer_id=getattr(target_entity, "id", None),
                        peer_name=target_entity.name,
                        peer_display_name=target_entity.displayName or target_entity.name,
                        peer_zone=zone_info.display,
                        peer_product=locator.folders[1] if len(locator.folders) >= 2 else None,
                        peer_module=locator.folders[2] if len(locator.folders) >= 3 else None,
                        path="/".join([*locator.folders, locator.entityName or target_entity.name]),
                        mapping=mapping,
                        label=_relationship_label(mapping),
                    )
                )
            else:
                relationships.append(
                    RelationshipDoc(
                        direction="outgoing",
                        peer_id=None,
                        peer_name=str(getattr(relation, "targetLocation", "")),
                        peer_display_name=str(getattr(relation, "targetLocation", "")),
                        peer_zone="Unknown",
                        peer_product=None,
                        peer_module=None,
                        path=None,
                        mapping=mapping,
                        label=_relationship_label(mapping),
                    )
                )
        return relationships

    def _build_transformations(self, locator: Locator, entity) -> tuple[list[TransformationDoc], list[CodeSnippet]]:
        transformations: list[TransformationDoc] = []
        code_snippets: list[CodeSnippet] = []
        for step in getattr(entity, "transformations", []) or []:
            details = {}
            code_path: str | None = None
            code_language: str | None = None
            code_content: str | None = None
            step_function = getattr(step, "function", None)
            if step_function and getattr(step_function, "source", None):
                source_reference = getattr(step_function, "source")
                details["source"] = source_reference
                resolved = self._resolve_transformation_source(locator, source_reference)
                if resolved:
                    try:
                        content = resolved.read_text(encoding="utf-8")
                    except OSError as exc:
                        logger.warning("Failed to read transformation source %s: %s", resolved, exc)
                    else:
                        code_content = content
                        code_path = (
                            resolved.relative_to(self.solution_root).as_posix()
                            if resolved.is_relative_to(self.solution_root)
                            else resolved.as_posix()
                        )
                        ext = resolved.suffix.lstrip(".")
                        language = "python" if ext == "py" else (ext or "text")
                        code_language = language
                        code_snippets.append(
                            CodeSnippet(
                                name=getattr(step, "name", None) or source_reference,
                                path=code_path,
                                language=language,
                                content=content,
                            )
                        )
            transformations.append(
                TransformationDoc(
                    step_no=getattr(step, "stepNo", None),
                    kind=getattr(step, "kind", None),
                    name=getattr(step, "name", None),
                    details=details,
                    code_path=code_path,
                    code_language=code_language,
                    code_excerpt=code_content,
                )
            )
        return transformations, code_snippets

    def _resolve_transformation_source(self, locator: Locator, source_reference: str) -> Path | None:
        if not source_reference:
            return None
        base_dir = self.model_root.joinpath(*locator.folders)
        candidate = Path(source_reference)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        candidate = candidate.resolve()
        if candidate.exists():
            return candidate
        logger.debug("Transformation source %s not found for locator %s", source_reference, locator)
        return None

    def _populate_inbound_relationships(self, entities: list[EntityDoc]) -> None:
        lookup = {doc.id: doc for doc in entities if doc.id is not None}
        for doc in entities:
            for relation in doc.relationships_out:
                if relation.peer_id is None:
                    continue
                target = lookup.get(relation.peer_id)
                if not target:
                    continue
                inverted_mapping = [
                    {"source": item.get("target"), "target": item.get("source")}
                    for item in relation.mapping
                ]
                target.relationships_in.append(
                    RelationshipDoc(
                        direction="incoming",
                        peer_id=doc.id,
                        peer_name=doc.name,
                        peer_display_name=doc.display_name,
                        peer_zone=doc.zone_display,
                        peer_product=doc.product_name,
                        peer_module=doc.module_name,
                        path=doc.locator_path,
                        mapping=inverted_mapping,
                        label=relation.label,
                    )
                )
        for doc in entities:
            doc.relationship_summary = {
                "incoming": len(doc.relationships_in),
                "outgoing": len(doc.relationships_out),
                "total": len(doc.relationships_in) + len(doc.relationships_out),
                "incoming_names": [rel.peer_display_name for rel in doc.relationships_in],
                "outgoing_names": [rel.peer_display_name for rel in doc.relationships_out],
            }

    def _summarize_sources(self, sources: list[SourceDoc]) -> dict[str, Any]:
        external = sum(1 for source in sources if source.kind == "external")
        modeled = sum(1 for source in sources if source.kind == "model")
        return {
            "total": len(sources),
            "external": external,
            "modeled": modeled,
            "data_sources": sorted({source.data_source_name for source in sources if source.data_source_name}),
        }

    def _summarize_zones(self, entities: list[EntityDoc]) -> list[ZoneSummary]:
        summary: dict[str, ZoneSummary] = {}
        for doc in entities:
            zone_key = doc.zone_name.lower()
            zone_entry = summary.get(zone_key)
            if not zone_entry:
                zone_entry = ZoneSummary(
                    name=doc.zone_name,
                    display_name=doc.zone_display,
                    folder=doc.zone_folder,
                    target_name=doc.zone_target,
                )
                summary[zone_key] = zone_entry
            zone_entry.entity_count += 1

            module_key = (doc.product_name or "", doc.module_name or "")
            module_entry = next(
                (
                    module
                    for module in zone_entry.module_summaries
                    if module.product == module_key[0] and module.module == module_key[1]
                ),
                None,
            )
            if not module_entry:
                module_entry = ModuleSummary(
                    product=doc.product_name,
                    product_display=doc.product_display,
                    module=doc.module_name,
                    module_display=doc.module_display,
                )
                zone_entry.module_summaries.append(module_entry)
            module_entry.entity_count += 1
            if doc.entity_kind == "fact":
                module_entry.fact_count += 1
            elif doc.entity_kind == "dimension":
                module_entry.dimension_count += 1

        def zone_sort_key(item: ZoneSummary) -> tuple[int, str]:
            zone_name_lower = item.name.lower()
            order_index = ZONE_ORDER.index(zone_name_lower) if zone_name_lower in ZONE_ORDER else len(ZONE_ORDER)
            return (order_index, zone_name_lower)

        for entry in summary.values():
            entry.module_summaries.sort(key=lambda module: (module.product or "", module.module or ""))

        return sorted(summary.values(), key=zone_sort_key)

    def _compute_stats(self, entities: list[EntityDoc], zones: list[ZoneSummary]) -> dict[str, Any]:
        history_counter: Counter[str] = Counter()
        property_counter: Counter[str] = Counter()
        entity_with_description = sum(1 for doc in entities if doc.description)
        for doc in entities:
            for history in doc.attribute_summary.get("history_types", []):
                history_counter[history] += 1
            property_counter.update(doc.entity_properties.keys())

        return {
            "entity_count": len(entities),
            "attribute_count": sum(doc.attribute_summary.get("total", 0) for doc in entities),
            "relationship_count": sum(doc.relationship_summary.get("outgoing", 0) for doc in entities),
            "zones": len(zones),
            "external_sources": sum(doc.source_summary.get("external", 0) for doc in entities),
            "modeled_sources": sum(doc.source_summary.get("modeled", 0) for doc in entities),
            "entities_with_descriptions": entity_with_description,
            "history_types": dict(history_counter),
            "top_properties": property_counter.most_common(5),
        }

    def _build_catalog_rows(self, entities: list[EntityDoc]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in entities:
            relative_path = Path("entities").joinpath(*doc.slug_path[:-1], f"{doc.slug_path[-1]}.md").as_posix()
            rows.append(
                {
                    "zone": doc.zone_display,
                    "product": doc.product_display or doc.product_name or "",
                    "module": doc.module_display or doc.module_name or "",
                    "entity": doc.display_name,
                    "id": doc.id,
                    "description": doc.description or "",
                    "attributes": doc.attribute_summary.get("total", 0),
                    "business_keys": len(doc.attribute_summary.get("business_keys", [])),
                    "history": ", ".join(doc.attribute_summary.get("history_types", [])) or "N/A",
                    "sources": doc.source_summary.get("total", 0),
                    "relationships": doc.relationship_summary.get("total", 0),
                    "link": relative_path,
                }
            )
        rows.sort(key=lambda row: (row["zone"], row["product"], row["module"], row["entity"]))
        return rows

    def _build_lineage_highlights(self, entities: list[EntityDoc]) -> list[dict[str, Any]]:
        highlights: list[dict[str, Any]] = []
        for doc in entities:
            for relation in doc.relationships_out:
                highlights.append(
                    {
                        "source": doc.display_name,
                        "target": relation.peer_display_name,
                        "source_zone": doc.zone_display,
                        "target_zone": relation.peer_zone,
                        "columns": relation.mapping,
                        "column_summary": relation.label or "N/A",
                        "path": f"{doc.display_name} -> {relation.peer_display_name}",
                    }
                )
            for source in doc.sources:
                if source.kind != "model":
                    continue
                highlights.append(
                    {
                        "source": source.display_name or source.name,
                        "target": doc.display_name,
                        "source_zone": source.zone or "Unknown",
                        "target_zone": doc.zone_display,
                        "columns": [
                            {"source": mapping.source, "target": mapping.target}
                            for mapping in source.mapping
                            if mapping.source and mapping.target
                        ],
                        "column_summary": source.mapping_label or "N/A",
                        "path": f"{source.display_name or source.name} -> {doc.display_name}",
                    }
                )
        highlights.sort(key=lambda item: len(item["columns"]), reverse=True)
        return highlights[:10]

    def _build_diagram(self, entities: list[EntityDoc]) -> DiagramModel:
        zone_groups: dict[str, list[dict[str, Any]]] = {}
        diagram_lookup: dict[int, str] = {}
        legend_lookup: dict[str, dict[str, Any]] = {}
        used_node_ids: set[str] = set()

        for doc in entities:
            zone_key = doc.zone_name.lower()
            fill_color, stroke_color = self._zone_colors(doc.zone_name)
            node_input = {
                "id": doc.diagram_id,
                "label": doc.display_name,
                "zone_display": doc.zone_display,
                "zone_key": zone_key,
                "product": doc.product_display or doc.product_name,
                "module": doc.module_display or doc.module_name,
                "path": doc.locator_path,
                "fill_color": fill_color,
                "stroke_color": stroke_color,
            }
            zone_groups.setdefault(zone_key, []).append(node_input)
            legend_lookup.setdefault(
                zone_key,
                {
                    "label": doc.zone_display,
                    "fill_color": fill_color,
                    "stroke_color": stroke_color,
                },
            )
            used_node_ids.add(doc.diagram_id)
            if doc.id is not None:
                diagram_lookup[doc.id] = doc.diagram_id

        raw_zone_info = self._raw_zone_info()
        external_nodes: dict[str, dict[str, Any]] = {}
        for doc in entities:
            for source in doc.sources:
                if source.kind != "external":
                    continue
                key = source.external_key or f"{source.reference}:{source.source_alias or source.name}"
                if key not in external_nodes:
                    data_source_label = source.data_source_name or source.reference
                    alias_label = source.source_alias or source.location or "source"
                    base_label = f"{data_source_label} - {alias_label}"
                    fill_color, stroke_color = self._zone_colors("raw")
                    node_id = self._unique_node_id(f"external-{_slug(key)}", used_node_ids)
                    used_node_ids.add(node_id)
                    external_nodes[key] = {
                        "id": node_id,
                        "label": base_label,
                        "zone_display": raw_zone_info.display,
                        "zone_key": "raw",
                        "product": source.data_source_display or source.data_source_name,
                        "module": source.source_alias or source.location,
                        "path": source.location or source.reference,
                        "fill_color": fill_color,
                        "stroke_color": stroke_color,
                    }
                    zone_groups.setdefault("raw", []).append(external_nodes[key])
                    legend_lookup.setdefault(
                        "raw",
                        {
                            "label": raw_zone_info.display,
                            "fill_color": fill_color,
                            "stroke_color": stroke_color,
                        },
                    )
                source.diagram_node_id = external_nodes[key]["id"]

        zone_keys = sorted(
            zone_groups.keys(),
            key=lambda zone: (ZONE_ORDER.index(zone) if zone in ZONE_ORDER else len(ZONE_ORDER), zone),
        )

        nodes: list[DiagramNode] = []
        y_offset = 120
        x_offset = 120
        column_spacing = 220
        row_spacing = 200

        for row_index, zone_key in enumerate(zone_keys):
            zone_nodes = sorted(
                zone_groups[zone_key],
                key=lambda info: (info.get("product") or "", info.get("module") or "", info["label"]),
            )
            for column_index, info in enumerate(zone_nodes):
                nodes.append(
                    DiagramNode(
                        id=info["id"],
                        label=info["label"],
                        zone=info["zone_display"],
                        product=info.get("product"),
                        module=info.get("module"),
                        x=x_offset + column_index * column_spacing,
                        y=y_offset + row_index * row_spacing,
                        width=180,
                        height=80,
                        path=info.get("path") or "",
                        fill_color=info["fill_color"],
                        stroke_color=info["stroke_color"],
                    )
                )

        edges: list[DiagramEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        edge_index = 0

        def add_edge(source_node_id: str | None, target_node_id: str | None, label: str, style: str) -> None:
            nonlocal edge_index
            if not source_node_id or not target_node_id:
                return
            edge_key = (source_node_id, target_node_id, label or "", style)
            if edge_key in seen_edges:
                return
            seen_edges.add(edge_key)
            edges.append(
                DiagramEdge(
                    id=f"edge-{edge_index}",
                    source=source_node_id,
                    target=target_node_id,
                    label=label,
                    style=style,
                )
            )
            edge_index += 1

        for doc in entities:
            for relation in doc.relationships_out:
                target_node = diagram_lookup.get(relation.peer_id)
                add_edge(doc.diagram_id, target_node, relation.label, "relationship")
            for source in doc.sources:
                if source.kind == "model" and source.entity_id is not None:
                    add_edge(diagram_lookup.get(source.entity_id), doc.diagram_id, "", "source")
                if source.kind == "external":
                    add_edge(source.diagram_node_id, doc.diagram_id, "", "external")

        legend_entries: list[dict[str, Any]] = []
        legend_x = x_offset
        legend_y = 20
        legend_height = 24
        legend_width = 160
        for index, zone_key in enumerate(zone_keys):
            entry = legend_lookup.get(zone_key)
            if not entry:
                continue
            legend_entries.append(
                {
                    "label": entry["label"],
                    "fill_color": entry["fill_color"],
                    "stroke_color": entry["stroke_color"],
                    "x": legend_x + index * (legend_width + 16),
                    "y": legend_y,
                    "width": legend_width,
                    "height": legend_height,
                }
            )

        return DiagramModel(
            title="Entity Relationships",
            name="Model Overview",
            width=1920,
            height=1080,
            nodes=nodes,
            edges=edges,
            legend=legend_entries,
        )

    def _unique_node_id(self, base: str, used: set[str]) -> str:
        candidate = base
        counter = 1
        while candidate in used:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _zone_colors(self, zone_name: str | None) -> tuple[str, str]:
        if not zone_name:
            return DEFAULT_NODE_COLORS
        return ZONE_COLORS.get(zone_name.lower(), DEFAULT_NODE_COLORS)

    def _has_surrogate_key_flag(self, attribute) -> bool:
        for prop in getattr(attribute, "properties", []) or []:
            name = getattr(prop, "property", "")
            value = getattr(prop, "value", "")
            if str(name).strip().lower() == "attribute_type" and str(value).strip().lower() == "sk":
                return True
        return False

    def _reference_locator_candidates(self, reference: str) -> list[str]:
        normalized = reference.strip().removeprefix("/")
        if not normalized:
            return []

        candidates: list[str] = []
        if normalized.lower().startswith("modelentities/"):
            candidates.append(normalized)
        elif "/" in normalized:
            candidates.append(f"modelEntities/{normalized}")
            parts = [part for part in normalized.split("/") if part]
            if parts:
                zone_info = self._zone_lookup.get(parts[0].lower())
                if zone_info and zone_info.folder:
                    candidates.append(f"modelEntities/{zone_info.folder}/{'/'.join(parts[1:])}")

        # Preserve insertion order while removing duplicates.
        return list(dict.fromkeys(candidates))

    def _locator_dm8l_path(self, locator: Locator) -> str:
        if not locator.folders:
            return f"/{locator.entityName or ''}"
        zone_info = self._zone_from_folder(locator.folders[0])
        zone_segment = zone_info.name.capitalize()
        return "/" + "/".join([zone_segment, *locator.folders[1:], locator.entityName or ""])

    def _resolve_entity_reference(self, reference) -> tuple[Locator, Any] | None:
        if reference is None:
            return None
        if isinstance(reference, int):
            try:
                wrapped = self.model.get_model_entity_by_id(reference)
            except Exception:  # noqa: BLE001 - unresolved IDs should not fail documentation generation
                return None
            return wrapped.locator, wrapped.entity
        if isinstance(reference, str):
            search_target = reference.strip()
            for candidate in self._reference_locator_candidates(search_target):
                try:
                    wrapped = self.model.get_entity_by_locator(candidate)
                except Exception:  # noqa: BLE001 - continue with next candidate/fallback
                    continue
                return wrapped.locator, wrapped.entity

            normalized = search_target.lower()
            if not normalized.startswith("/"):
                normalized = f"/{normalized}"
            for locator, wrapper in self.model.modelEntities.items():
                raw_path = f"/{'/'.join([*locator.folders, locator.entityName or ''])}".lower()
                if raw_path == normalized or self._locator_dm8l_path(locator).lower() == normalized:
                    return locator, wrapper.entity
        return None

    def _zone_from_folder(self, folder: str | None) -> ZoneInfo:
        if not folder:
            return ZoneInfo(name="unknown", display="Unknown", folder=None, target=None)
        lookup_key = folder.lower()
        if lookup_key in self._zone_lookup:
            return self._zone_lookup[lookup_key]
        normalized = re.sub(r"^\d+-", "", folder).lower()
        if normalized in self._zone_lookup:
            return self._zone_lookup[normalized]
        return ZoneInfo(name=folder, display=folder, folder=folder, target=None)

    def _raw_zone_info(self) -> ZoneInfo:
        return self._zone_lookup.get("raw") or ZoneInfo(
            name="raw",
            display="Raw Data Layer",
            folder="raw",
            target=None,
        )

    def _load_zones(self) -> dict[str, ZoneInfo]:
        lookup: dict[str, ZoneInfo] = {}
        for wrapper in self.model.zones.values():
            zone_entity = wrapper.entity
            name = getattr(zone_entity, "name", None)
            if not name:
                continue
            info = ZoneInfo(
                name=name,
                display=getattr(zone_entity, "displayName", None) or name.title(),
                folder=getattr(zone_entity, "localFolderName", None),
                target=getattr(zone_entity, "targetName", None),
            )
            lookup[name.lower()] = info
            if info.folder:
                lookup[info.folder.lower()] = info
        return lookup

    def _load_data_products(self) -> dict[str, ProductInfo]:
        products: dict[str, ProductInfo] = {}
        for wrapper in self.model.dataProducts.values():
            product_entity = wrapper.entity
            name = getattr(product_entity, "name", None)
            if not name:
                continue
            modules = {
                module_name.lower(): ModuleInfo(
                    name=module_name,
                    display=getattr(module, "displayName", None),
                )
                for module in getattr(product_entity, "dataModules", []) or []
                if (module_name := getattr(module, "name", None))
            }
            products[name.lower()] = ProductInfo(
                name=name,
                display=getattr(product_entity, "displayName", None),
                modules=modules,
            )
        return products

    def _load_data_sources(self) -> dict[str, DataSourceInfo]:
        sources: dict[str, DataSourceInfo] = {}
        for wrapper in self.model.dataSources.values():
            source_entity = wrapper.entity
            name = getattr(source_entity, "name", None)
            if name:
                sources[name] = DataSourceInfo(
                    name=name,
                    display_name=getattr(source_entity, "displayName", None),
                    source_type=getattr(source_entity, "type", None),
                    description=getattr(source_entity, "description", None),
                )
        return sources
