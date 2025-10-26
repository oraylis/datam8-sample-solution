from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from dm8gen import config
from dm8gen.utils import start_logger

logger = start_logger(__name__)

# Common aliases so source / canonical names converge to those defined in DataTypes.json.
TYPE_ALIASES: dict[str, str] = {
    "integer": "int",
    "boolean": "bit",
    "number": "int",
    "dyndecimal": "decimal",
    "dynstring": "string",
}


def _normalize_canonical(name: str | None) -> str:
    """Normalize canonical data type names for lookups."""
    if not name:
        return "string"
    lower = name.strip().lower()
    return TYPE_ALIASES.get(lower, lower)


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON file and return its content."""
    return json.loads(path.read_text(encoding="utf-8"))


def _convert_property_value(value: Any) -> Any:
    """Normalize property values to booleans/None where applicable."""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None
    return value


@dataclass(frozen=True)
class ZoneMetadata:
    """Represents a zone entry from Base/Zones.json."""

    name: str
    display_name: str
    target_name: str
    local_folder: str | None


@dataclass(frozen=True)
class FolderInfo:
    """Metadata about a folder (.properties.json) in the model tree."""

    name: str
    display_name: str | None
    properties: dict[str, Any]


class MetadataResolver:
    """
    Central helper that exposes zone, folder, type, and data source information.

    The resolver caches lookups because the same folders/zones/types are reused
    for each entity during payload generation.
    """

    def __init__(self, model):
        self.model = model
        self.solution_root = config.solution_folder_path
        self.model_root = self.solution_root / model.solution.modelPath
        self.base_root = self.solution_root / model.solution.basePath

    # ------------------------------------------------------------------ Zones
    @property
    @lru_cache
    def _zones_maps(self) -> tuple[dict[str, ZoneMetadata], dict[str, ZoneMetadata]]:
        """Load zone metadata from Base/Zones.json once."""
        data = _load_json(self.base_root / "Zones.json")
        folder_map: dict[str, ZoneMetadata] = {}
        name_map: dict[str, ZoneMetadata] = {}

        for entry in data.get("zones", []):
            zone = ZoneMetadata(
                name=entry.get("name", ""),
                display_name=entry.get("displayName", entry.get("name", "")),
                target_name=entry.get("targetName", entry.get("name", "")),
                local_folder=entry.get("localFolderName"),
            )
            if zone.local_folder:
                folder_map[zone.local_folder.lower()] = zone
            name_map[zone.name.lower()] = zone

        return folder_map, name_map

    def zone_from_folder(self, folder_name: str) -> ZoneMetadata | None:
        """Resolve a zone using a folder prefix like '010-Stage'."""
        folder_map, name_map = self._zones_maps
        return folder_map.get(folder_name.lower()) or name_map.get(folder_name.lower())

    def zone_by_name(self, name: str) -> ZoneMetadata | None:
        """Resolve a zone directly by its canonical name."""
        _, name_map = self._zones_maps
        return name_map.get(name.lower())

    def zone_folder_name(self, zone: ZoneMetadata) -> str:
        """Return the folder name that represents the given zone."""
        return zone.local_folder or zone.name

    # ------------------------------------------------------------- Folder info
    @lru_cache
    def folder_info(self, folder_tuple: tuple[str, ...]) -> FolderInfo:
        """Return folder name/properties from the matching .properties.json file."""
        if not folder_tuple:
            return FolderInfo(name="", display_name=None, properties={})

        properties_path = self.model_root.joinpath(*folder_tuple) / ".properties.json"
        if not properties_path.exists():
            return FolderInfo(name=folder_tuple[-1], display_name=None, properties={})

        data = _load_json(properties_path)
        folders = data.get("folders", [])
        if not folders:
            return FolderInfo(name=folder_tuple[-1], display_name=None, properties={})

        entry = folders[0]
        properties = {
            prop["property"]: _convert_property_value(prop["value"])
            for prop in entry.get("properties", [])
        }

        return FolderInfo(
            name=entry.get("name", folder_tuple[-1]),
            display_name=entry.get("displayName"),
            properties=properties,
        )

    # ----------------------------------------------------------- Data sources
    @property
    @lru_cache
    def _data_source_details(
        self,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str | None], dict[str, dict[str, str]]]:
        """
        Load Base/DataSources.json and derive:
        - raw entries by name
        - source type per data source (e.g. SqlDataSource)
        - source-specific type mappings (sourceType -> canonical type)
        """
        data = _load_json(self.base_root / "DataSources.json")
        entries = {source["name"]: source for source in data.get("dataSources", []) if source.get("name")}
        type_by_name = {name: entry.get("type") for name, entry in entries.items()}
        mapping_by_name: dict[str, dict[str, str]] = {}

        for name, entry in entries.items():
            mapping_by_name[name] = {
                m["sourceType"].lower(): _normalize_canonical(m["targetType"])
                for m in entry.get("dataTypeMapping", [])
                if m.get("sourceType") and m.get("targetType")
            }

        return entries, type_by_name, mapping_by_name

    @property
    @lru_cache
    def data_sources(self) -> dict[str, dict[str, Any]]:
        """Expose the raw data source entries."""
        entries, _, _ = self._data_source_details
        return entries

    @property
    @lru_cache
    def _data_source_type_by_name(self) -> dict[str, str | None]:
        """Map data source name to source type (e.g. SqlDataSource)."""
        _, type_by_name, _ = self._data_source_details
        return type_by_name

    @property
    @lru_cache
    def _data_source_mapping_by_name(self) -> dict[str, dict[str, str]]:
        """Per data source, map source data types to canonical types."""
        _, _, mapping_by_name = self._data_source_details
        return mapping_by_name

    @property
    @lru_cache
    def _data_source_type_mappings(self) -> dict[str, dict[str, str]]:
        """
        Load Base/DataSourceTypes.json to provide fallback mappings for a source type.

        Some sources (e.g. Oracle) may not have an explicit type definition; in that case
        the resolver falls back to an empty mapping.
        """
        path = self.base_root / "DataSourceTypes.json"
        if not path.exists():
            return {}

        data = _load_json(path)
        type_mappings: dict[str, dict[str, str]] = {}
        for entry in data.get("dataSourceTypes", []):
            type_name = entry.get("name")
            if not type_name:
                continue
            type_mappings[type_name] = {
                m["sourceType"].lower(): _normalize_canonical(m["targetType"])
                for m in entry.get("dataTypeMapping", [])
                if m.get("sourceType") and m.get("targetType")
            }
        return type_mappings

    def map_source_type_to_canonical(self, data_source_name: str, source_type: str) -> str | None:
        """
        Map a raw source data type to its canonical representation using the data source
        specific mapping, falling back to the data source type mapping when necessary.
        """
        source_type_lower = source_type.lower()

        canonical = self._data_source_mapping_by_name.get(data_source_name, {}).get(source_type_lower)
        if canonical:
            return canonical

        data_source_type = self._data_source_type_by_name.get(data_source_name)
        if data_source_type:
            canonical = self._data_source_type_mappings.get(data_source_type, {}).get(source_type_lower)
            if canonical:
                return canonical

        return None

    def iter_external_sources(self, entity) -> Iterable[tuple[Any, dict[str, Any] | None]]:
        """Yield external sources attached to a model entity."""
        for source in getattr(entity, "sources", []):
            data_source_name = getattr(source, "dataSource", None)
            if not data_source_name:
                continue
            yield source, self.data_sources.get(data_source_name)

    # ----------------------------------------------------------- Canonical map
    @property
    @lru_cache
    def _canonical_to_parquet(self) -> dict[str, str]:
        """Map canonical data types to parquet types from Base/DataTypes.json."""
        data = _load_json(self.base_root / "DataTypes.json")
        return {
            entry["name"].lower(): entry.get("parquetType", "string")
            for entry in data.get("dataTypes", [])
            if entry.get("name")
        }

    def build_column_from_canonical(
        self,
        *,
        name: str,
        canonical: str,
        nullable: bool,
        comment: str | None,
        data_type_model,
    ) -> dict[str, Any]:
        """
        Convert a canonical type into a column descriptor with Spark/Delta types.

        Precision/scale are respected when provided via the attribute's dataType model.
        """
        canonical_norm = _normalize_canonical(canonical)

        # Special handling for decimals so precision / scale are kept.
        if canonical_norm == "decimal":
            precision = getattr(data_type_model, "precision", None) if data_type_model else None
            scale = getattr(data_type_model, "scale", None) if data_type_model else None
            if precision is not None and scale is not None:
                parquet_type = f"decimal({precision},{scale})"
            else:
                parquet_type = "decimal"
        else:
            parquet_type = self._canonical_to_parquet.get(canonical_norm)
            if not parquet_type:
                logger.warning(
                    "Canonical data type '%s' is not defined in DataTypes.json; defaulting to string.",
                    canonical,
                )
                parquet_type = "string"

        spark_type = parquet_type.lower()
        delta_type = parquet_type.upper() if "(" not in parquet_type else parquet_type.upper()
        metadata_repr = "{'comment': " + repr(comment) + "}" if comment else None

        return {
            "name": name,
            "spark_type_expr": f'StructType.fromDDL("{spark_type}")',
            "struct_nullable": nullable,
            "metadata_repr": metadata_repr,
            "delta_type": delta_type,
            "delta_nullable": nullable,
            "delta_comment": comment,
        }

    # ----------------------------------------------------------- Column builds
    def build_standard_columns(self, entity) -> list[dict[str, Any]]:
        """Create column descriptors for a modeled entity (non-raw)."""
        columns: list[dict[str, Any]] = []
        for attribute in entity.attributes:
            columns.append(
                self.build_column_from_canonical(
                    name=attribute.name,
                    canonical=attribute.dataType.type,
                    nullable=attribute.dataType.nullable
                    if attribute.dataType.nullable is not None
                    else True,
                    comment=attribute.description or None,
                    data_type_model=attribute.dataType,
                )
            )
        return columns

    def build_raw_columns(self, entity, source) -> list[dict[str, Any]]:
        """
        Create column descriptors for a raw notebook.

        The method maps source data types to canonical ones and then to parquet types.
        """
        # Always start with the ingestion metadata columns.
        columns = self.build_raw_base_columns()

        mapping_by_target = {}
        if getattr(source, "mapping", None):
            mapping_by_target = {
                mapping.targetName: mapping
                for mapping in source.mapping
                if getattr(mapping, "targetName", None)
            }

        data_source_name = getattr(source, "dataSource", "")

        for attribute in entity.attributes:
            canonical_override = None
            mapping = mapping_by_target.get(attribute.name)
            if mapping and getattr(mapping, "sourceDataType", None):
                source_type = getattr(mapping.sourceDataType, "type", None)
                if source_type:
                    canonical_override = self.map_source_type_to_canonical(data_source_name, source_type)
                    if canonical_override is None:
                        logger.warning(
                            "Missing data type mapping for '%s' in data source '%s'. Falling back to modeled type.",
                            source_type,
                            data_source_name,
                        )

            canonical = canonical_override or attribute.dataType.type
            columns.append(
                self.build_column_from_canonical(
                    name=attribute.name,
                    canonical=canonical,
                    nullable=attribute.dataType.nullable
                    if attribute.dataType.nullable is not None
                    else True,
                    comment=attribute.description or None,
                    data_type_model=attribute.dataType,
                )
            )

        return columns

    def build_raw_base_columns(self) -> list[dict[str, Any]]:
        """Default ingestion columns for raw notebooks."""
        defs = (
            ("__Year", "short"),
            ("__Month", "short"),
            ("__Day", "short"),
            ("__InsertTimestampUTC", "datetime"),
        )
        return [
            self.build_column_from_canonical(
                name=name,
                canonical=canonical,
                nullable=False,
                comment=None,
                data_type_model=None,
            )
            for name, canonical in defs
        ]


# --------------------------------------------------------------------- helpers
def collect_imports(columns: Iterable[dict[str, Any]]) -> list[str]:
    """
    Determine which pyspark types to import based on the generated columns.

    StructType and StructField are always required.
    """
    return ["StructType", "StructField"]


def collect_column_tags(entity) -> list[dict[str, Any]]:
    """Return column-level tag assignments from attribute properties."""
    tagged: list[dict[str, Any]] = []
    for attribute in entity.attributes:
        if not attribute.properties:
            continue
        tags = {
            prop.property: _convert_property_value(prop.value)
            for prop in attribute.properties
        }
        tagged.append({"column": attribute.name, "tags_repr": repr(tags)})
    return tagged


def collect_refactored_columns(entity) -> list[dict[str, Any]]:
    """Capture refactor name mappings so the template can render them."""
    refactored: list[dict[str, Any]] = []
    for attribute in entity.attributes:
        if not getattr(attribute, "refactorNames", None):
            continue
        refactored.append(
            {
                "name": attribute.name,
                "aliases": list(attribute.refactorNames),
            }
        )
    return refactored


def merge_table_tags(
    entity,
    product_info: FolderInfo | None,
    module_info: FolderInfo | None,
) -> dict[str, Any]:
    """Combine table-level properties from product, module, and entity definitions."""
    tags: dict[str, Any] = {}
    if product_info:
        tags.update(product_info.properties)
    if module_info:
        tags.update(module_info.properties)
    if entity.properties:
        tags.update(
            {
                prop.property: _convert_property_value(prop.value)
                for prop in entity.properties
            }
        )
    return tags


def build_business_key_partitions(entity) -> list[str]:
    """Use business-key attributes as partition columns for non-raw tables."""
    return [
        attribute.name
        for attribute in entity.attributes
        if attribute.isBusinessKey
    ]


def _parse_source_location(location: str | None) -> tuple[str | None, str | None]:
    """Split a source location like '[schema].[table]' into schema/table pieces."""
    if not location:
        return None, None
    matches = re.findall(r"\[([^\]]+)\]", location)
    if len(matches) >= 2:
        return matches[-2], matches[-1]
    if matches:
        return None, matches[-1]
    return None, None


def build_raw_source_name(source) -> str:
    """Derive a raw table/filename from source alias/location."""
    schema, table = _parse_source_location(getattr(source, "sourceLocation", None))
    alias = (getattr(source, "sourceAlias", None) or table or "").strip()
    alias = alias.replace(" ", "_")
    schema_part = (schema or "").strip().replace(" ", "_")
    parts = [part for part in (schema_part, alias) if part]
    return "_".join(parts) or alias or "raw_entity"
