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

TARGET_NAME = "databricks"

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


def _properties_to_dict(properties: Iterable[Any] | None) -> dict[str, Any]:
    """Convert iterable of property objects into a dictionary."""
    result: dict[str, Any] = {}
    if not properties:
        return result
    for prop in properties:
        name = getattr(prop, "property", None)
        if not name:
            continue
        result[name] = _convert_property_value(getattr(prop, "value", None))
    return result


def _strip_brackets(value: str) -> str:
    """Remove surrounding square brackets from identifiers."""
    trimmed = value.strip()
    if trimmed.startswith("[") and trimmed.endswith("]"):
        return trimmed[1:-1]
    return trimmed


def _sanitize_identifier(value: str | None) -> str:
    """Turn an arbitrary identifier into an underscore-delimited token."""
    if not value:
        return ""
    # Replace any non-word character with underscores and collapse duplicates.
    cleaned = re.sub(r"\W+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("_")


def _select_expr(source_expr: str, target: str) -> str:
    """Build a selectExpr statement with alias."""
    identifier = _strip_brackets(source_expr)
    return f"`{identifier}` AS `{target}`"


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
        """Cache solution/model paths and build quick helpers for entity lookups."""
        self.model = model
        self.solution_root = config.solution_folder_path
        self.model_root = self.solution_root / model.solution.modelPath
        self.base_root = self.solution_root / model.solution.basePath
        self._entity_by_id: dict[int, tuple] = {}
        for locator, wrapper in model.modelEntities.items():
            entity_id = getattr(wrapper.entity, "id", None)
            if entity_id is None:
                continue
            self._entity_by_id[entity_id] = (locator, wrapper.entity)

    # ------------------------------------------------------ Property values
    @property
    @lru_cache
    def _property_values_map(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """Split PropertyValues.json into job and schedule lookups."""
        data = _load_json(self.base_root / "PropertyValues.json")
        jobs: dict[str, dict[str, Any]] = {}
        schedules: dict[str, dict[str, Any]] = {}
        for entry in data.get("propertyValues", []):
            prop = entry.get("property")
            name = entry.get("name")
            if not name:
                continue
            if prop == "jobs":
                jobs[name] = entry
            elif prop == "schedules":
                schedules[name] = entry
        return jobs, schedules

    def resolve_property(self, locator, entity, property_name: str) -> Any:
        """Resolve an entity property using entity -> module -> product fallback."""
        entity_props = self.entity_properties(entity)
        if property_name in entity_props:
            return entity_props[property_name]

        if len(locator.folders) >= 3:
            module_info = self.folder_info(tuple(locator.folders[:3]))
            if property_name in module_info.properties:
                return module_info.properties[property_name]

        if len(locator.folders) >= 2:
            product_info = self.folder_info(tuple(locator.folders[:2]))
            if property_name in product_info.properties:
                return product_info.properties[property_name]

        return None

    def job_definition(self, job_value: str | None) -> dict[str, Any] | None:
        """Return job display metadata (name, schedule, cluster) for a job value."""
        if not job_value:
            return None

        jobs, schedules = self._property_values_map
        job_entry = jobs.get(job_value)
        if not job_entry:
            return None

        schedule_name = None
        for prop in job_entry.get("properties", []) or []:
            if prop.get("property") == "schedules":
                schedule_name = prop.get("value")
                break

        schedule_entry = schedules.get(schedule_name) if schedule_name else None
        schedule_data = None
        if schedule_entry:
            schedule_data = {
                "name": schedule_name,
                "display_name": schedule_entry.get("displayName", schedule_name),
                "cron": schedule_entry.get("cron"),
            }

        return {
            "value": job_value,
            "display_name": job_entry.get("displayName", job_value),
            "cluster": job_entry.get("cluster", {}),
            "schedule": schedule_data,
        }

    def entity_job_definition(self, locator, entity) -> dict[str, Any] | None:
        """Return the job metadata assigned to the entity, if any."""
        job_value = self.resolve_property(locator, entity, "jobs")
        return self.job_definition(job_value)

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

    def zones(self) -> list[ZoneMetadata]:
        """Return all known zones defined in Base/Zones.json."""
        _, name_map = self._zones_maps
        # name_map already keyed by lower-case zone name; values are the ZoneMetadata instances.
        # Preserve insertion order from the JSON file by relying on dict value order.
        return list(name_map.values())

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
    def _canonical_to_target(self) -> dict[str, str]:
        """Map canonical data types to generator target-specific types."""
        data = _load_json(self.base_root / "DataTypes.json")
        mapping: dict[str, str] = {}
        for entry in data.get("dataTypes", []):
            name = entry.get("name")
            if not name:
                continue
            targets = entry.get("targets", {})
            target_value = targets.get(TARGET_NAME)
            if target_value:
                mapping[name.lower()] = target_value
        return mapping

    def build_column_from_canonical(
        self,
        *,
        name: str,
        canonical: str,
        nullable: bool,
        comment: str | None,
        data_type_model,
        extra_metadata: dict[str, Any] | None = None,
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
                target_type = f"decimal({precision},{scale})"
            else:
                target_type = self._canonical_to_target.get(canonical_norm, "decimal")
        else:
            target_type = self._canonical_to_target.get(canonical_norm)
            if not target_type:
                logger.warning(
                    "Canonical data type '%s' is not defined in DataTypes.json; defaulting to string.",
                    canonical,
                )
                target_type = "string"

        ddl_type = target_type.upper()
        metadata: dict[str, Any] = {}
        if comment:
            metadata["comment"] = comment
        if extra_metadata:
            metadata.update(extra_metadata)
        metadata_repr = repr(metadata) if metadata else None

        return {
            "name": name,
            "spark_type_expr": f'DataType.fromDDL("{ddl_type}")',
            "struct_nullable": nullable,
            "metadata_repr": metadata_repr,
            "delta_type": ddl_type,
            "delta_nullable": nullable,
            "delta_comment": comment,
        }

    # ----------------------------------------------------------- Column builds
    def attribute_metadata(self, attribute) -> dict[str, Any]:
        """Derive metadata flags for an attribute."""
        metadata: dict[str, Any] = {}
        if getattr(attribute, "isBusinessKey", False):
            metadata["business_key"] = True
            #metadata.setdefault("primary_key", True)

        attribute_type = getattr(attribute, "attributeType", "") or ""
        if attribute_type.lower() == "sid":
            metadata["surrogate_key"] = True
            #metadata["primary_key"] = True

        return metadata

    def build_standard_columns(self, entity) -> list[dict[str, Any]]:
        """Create column descriptors for a modeled entity (non-raw)."""
        columns: list[dict[str, Any]] = []
        for attribute in entity.attributes:
            extra_metadata = self.attribute_metadata(attribute)
            columns.append(
                self.build_column_from_canonical(
                    name=attribute.name,
                    canonical=attribute.dataType.type,
                    nullable=attribute.dataType.nullable
                    if attribute.dataType.nullable is not None
                    else True,
                    comment=attribute.description or None,
                    data_type_model=attribute.dataType,
                    extra_metadata=extra_metadata or None,
                )
            )
        return columns

    def build_raw_columns(self, entity, source) -> list[dict[str, Any]]:
        """
        Create column descriptors for a raw notebook.

        The method reads the source mapping to determine the target column names
        and source data types. When no explicit mapping is present, it falls
        back to the modeled attributes (old behaviour).
        """
        columns = self.build_raw_base_columns()

        mapping_entries = getattr(source, "mapping", None) or []
        data_source_name = getattr(source, "dataSource", "") or ""

        if mapping_entries:
            attributes_by_name = {
                attribute.name: attribute
                for attribute in getattr(entity, "attributes", []) or []
            }

            for mapping in mapping_entries:
                target_name = getattr(mapping, "targetName", None)
                if not target_name:
                    continue

                source_data_type = getattr(mapping, "sourceDataType", None)
                canonical = None
                nullable = True
                if source_data_type:
                    source_type = getattr(source_data_type, "type", None)
                    if source_type:
                        mapped_type = self.map_source_type_to_canonical(data_source_name, source_type)
                        if mapped_type is None:
                            logger.warning(
                                "Missing data type mapping for '%s' in data source '%s'. Falling back to modeled type or string.",
                                source_type,
                                data_source_name,
                            )
                        else:
                            canonical = mapped_type
                    nullable = getattr(source_data_type, "nullable", None)

                attribute_model = attributes_by_name.get(target_name)
                data_type_model = getattr(attribute_model, "dataType", None) if attribute_model else None

                if canonical is None and attribute_model:
                    canonical = attribute_model.dataType.type
                if nullable is None and attribute_model:
                    nullable = (
                        attribute_model.dataType.nullable
                        if attribute_model.dataType.nullable is not None
                        else True
                    )

                if canonical is None:
                    canonical = "string"
                if nullable is None:
                    nullable = True

                columns.append(
                    self.build_column_from_canonical(
                        name=target_name,
                        canonical=canonical,
                        nullable=nullable,
                        comment=None,
                        data_type_model=data_type_model,
                        extra_metadata=None,
                    )
                )
        else:
            # Fallback: reuse the modeled attributes if no mapping is present.
            for attribute in getattr(entity, "attributes", []) or []:
                columns.append(
                    self.build_column_from_canonical(
                        name=attribute.name,
                        canonical=attribute.dataType.type,
                        nullable=attribute.dataType.nullable
                        if attribute.dataType.nullable is not None
                        else True,
                        comment=None,
                        data_type_model=attribute.dataType,
                        extra_metadata=None,
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

    def raw_table_identifiers(self, locator, source) -> dict[str, str]:
        """Derive naming components for a raw table based on entity folders and source alias."""
        if locator and getattr(locator, "folders", None):
            folders = locator.folders
        else:
            folders = ()

        product_info = self.folder_info(tuple(folders[:2])) if len(folders) >= 2 else None
        module_info = self.folder_info(tuple(folders[:3])) if len(folders) >= 3 else None

        data_product_name = (
            product_info.name
            if product_info
            else (folders[1] if len(folders) >= 2 else "UnknownProduct")
        )
        data_module_name = (
            module_info.name
            if module_info
            else (folders[2] if len(folders) >= 3 else "General")
        )

        table_name = build_raw_source_name(source) or "raw_entity"
        full_table_name = "_".join(
            part for part in (data_product_name, data_module_name, table_name) if part
        )

        return {
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": table_name,
            "full_table_name": full_table_name,
        }

    # ----------------------------------------------------------- Entity extras
    def entity_folder_path(self, locator) -> Path:
        """Return the filesystem path to the entity folder."""
        return self.model_root.joinpath(*locator.folders)

    def locator_to_dm8l(self, locator) -> str:
        """Convert a locator into a DM8L style path (e.g. /Core/Sales/.../Entity)."""
        if not locator.folders:
            return f"/{locator.entityName}"
        zone_meta = self.zone_from_folder(locator.folders[0])
        zone_segment = zone_meta.name.capitalize() if zone_meta else locator.folders[0]
        parts = [zone_segment, *locator.folders[1:], locator.entityName or ""]
        return "/" + "/".join(part for part in parts if part)

    def entity_properties(self, entity) -> dict[str, Any]:
        """Expose entity-level properties as a dictionary."""
        return _properties_to_dict(getattr(entity, "properties", None))

    def source_properties(self, source) -> dict[str, Any]:
        """Expose properties defined on a source configuration."""
        return _properties_to_dict(getattr(source, "properties", None))

    def write_mode(
        self,
        entity,
        product_info: FolderInfo | None,
        module_info: FolderInfo | None,
        default: str = "overwrite",
    ) -> str:
        """Resolve write mode using entity -> module -> product fallback."""
        entity_props = self.entity_properties(entity)
        if "write_mode" in entity_props and entity_props["write_mode"]:
            return str(entity_props["write_mode"]).lower()

        if module_info:
            module_props = module_info.properties
            if "write_mode" in module_props and module_props["write_mode"]:
                return str(module_props["write_mode"]).lower()

        if product_info:
            product_props = product_info.properties
            if "write_mode" in product_props and product_props["write_mode"]:
                return str(product_props["write_mode"]).lower()

        return default

    def history_configuration(self, entity) -> dict[str, list[str]]:
        """Return history configuration buckets for an entity."""
        config = {
            "business_keys": [],
            "scd0": [],
            "scd1": [],
            "scd2": [],
        }

        for attribute in getattr(entity, "attributes", []):
            if getattr(attribute, "isBusinessKey", False):
                config["business_keys"].append(attribute.name)
            history_flag = getattr(attribute, "history", None)
            if not history_flag:
                continue
            if hasattr(history_flag, "value"):
                history_value = str(history_flag.value)
            else:
                history_value = str(history_flag)
            normalized = history_value.lower()
            if normalized == "scd0":
                config["scd0"].append(attribute.name)
            elif normalized == "scd1":
                config["scd1"].append(attribute.name)
            elif normalized == "scd2":
                config["scd2"].append(attribute.name)

        return config

    def attribute_names(self, entity) -> list[str]:
        """Return attribute names in modeling order."""
        return [attribute.name for attribute in getattr(entity, "attributes", [])]

    # ----------------------------------------------------------- Dimensions
    @property
    @lru_cache
    def _curated_dimensions(self) -> list[dict[str, Any]]:
        """Collect curated zone entities that expose SID attributes for lookups."""
        dimensions: list[dict[str, Any]] = []
        for locator, wrapper in self.model.modelEntities.items():
            if not locator.folders:
                continue
            zone_meta = self.zone_from_folder(locator.folders[0])
            if zone_meta is None or zone_meta.name != "curated":
                continue

            entity = wrapper.entity
            sid_attributes = [
                attribute
                for attribute in getattr(entity, "attributes", [])
                if getattr(attribute, "attributeType", "").lower() == "sid"
            ]
            if not sid_attributes:
                continue

            bk_attributes = [
                attribute
                for attribute in getattr(entity, "attributes", [])
                if getattr(attribute, "isBusinessKey", False)
            ]
            if not bk_attributes:
                continue

            product_info = (
                self.folder_info(tuple(locator.folders[:2]))
                if len(locator.folders) >= 2
                else None
            )
            module_info = (
                self.folder_info(tuple(locator.folders[:3]))
                if len(locator.folders) >= 3
                else None
            )
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

            full_table_name = f"{data_product_name}_{data_module_name}_{entity.name}"

            dimensions.append(
                {
                    "locator": locator,
                    "entity": entity,
                    "zone": zone_meta.name,
                    "zone_folder": self.zone_folder_name(zone_meta),
                    "data_product": data_product_name,
                    "data_module": data_module_name,
                    "full_table_name": full_table_name,
                    "sid_columns": [attr.name for attr in sid_attributes],
                    "business_key_columns": [attr.name for attr in bk_attributes],
                    "dm8l_path": self.locator_to_dm8l(locator),
                    "alias": f"dim_{entity.name}",
                }
            )

        return dimensions

    def has_lookup_dimensions(self, entity) -> bool:
        """Return True if the entity defines the builtin lookup_dimensions step."""
        for transformation in getattr(entity, "transformations", []) or []:
            kind = getattr(transformation, "kind", None)
            if isinstance(kind, str):
                kind_value = kind
            elif hasattr(kind, "value"):
                kind_value = kind.value
            elif isinstance(transformation, dict):
                kind_value = transformation.get("kind")
            else:
                kind_value = None

            name = getattr(transformation, "name", None)
            if name is None and isinstance(transformation, dict):
                name = transformation.get("name")

            if (
                kind_value == "builtin"
                and name
                and name.lower() == "lookup_dimensions"
            ):
                return True
        return False

    def dimension_lookups_for_fact(self, locator, entity) -> list[dict[str, Any]]:
        """
        Determine dimension join instructions for a fact entity using explicit relationships.

        Each relationship produces a lookup entry that joins the fact to the target entity
        based on the configured attribute mappings.
        """
        lookups: list[dict[str, Any]] = []
        fact_attributes = {
            attribute.name: attribute for attribute in getattr(entity, "attributes", [])
        }

        relationships = getattr(entity, "relationships", []) or []
        for relationship in relationships:
            target_location = getattr(relationship, "targetLocation", None)
            if target_location is None and isinstance(relationship, dict):
                target_location = relationship.get("targetLocation")

            target_locator = None
            target_entity = None

            if isinstance(target_location, int):
                locator_entity = self._entity_by_id.get(target_location)
                if locator_entity:
                    target_locator, target_entity = locator_entity
            elif isinstance(target_location, str):
                search_target = target_location.strip()
                if search_target:
                    for candidate_locator, candidate_wrapper in self.model.modelEntities.items():
                        if self.locator_to_dm8l(candidate_locator) == search_target:
                            target_locator = candidate_locator
                            target_entity = candidate_wrapper.entity
                            break

            if not target_locator or target_entity is None or not getattr(target_locator, "folders", None):
                continue

            join_mappings = getattr(relationship, "attributes", None)
            if join_mappings is None and isinstance(relationship, dict):
                join_mappings = relationship.get("attributes")

            join_columns: list[dict[str, str]] = []
            if join_mappings:
                for mapping in join_mappings:
                    fact_column = getattr(mapping, "sourceName", None)
                    dimension_column = getattr(mapping, "targetName", None)
                    if fact_column is None and isinstance(mapping, dict):
                        fact_column = mapping.get("sourceName")
                    if dimension_column is None and isinstance(mapping, dict):
                        dimension_column = mapping.get("targetName")
                    if not fact_column or not dimension_column:
                        continue
                    join_columns.append(
                        {"fact_column": fact_column, "dimension_column": dimension_column}
                    )

            if not join_columns:
                continue

            dimension_zone_meta = self.zone_from_folder(target_locator.folders[0])
            if dimension_zone_meta is None:
                continue

            dimension_product_info = (
                self.folder_info(tuple(target_locator.folders[:2]))
                if len(target_locator.folders) >= 2
                else None
            )
            dimension_module_info = (
                self.folder_info(tuple(target_locator.folders[:3]))
                if len(target_locator.folders) >= 3
                else None
            )
            data_product_name = (
                dimension_product_info.name
                if dimension_product_info
                else (target_locator.folders[1] if len(target_locator.folders) >= 2 else "UnknownProduct")
            )
            data_module_name = (
                dimension_module_info.name
                if dimension_module_info
                else (target_locator.folders[2] if len(target_locator.folders) >= 3 else "General")
            )
            dimension_full_table_name = f"{data_product_name}_{data_module_name}_{target_entity.name}"

            dimension_attributes = {
                attribute.name: attribute for attribute in getattr(target_entity, "attributes", [])
            }
            dimension_sid_column = next(
                (
                    column["dimension_column"]
                    for column in join_columns
                    if (
                        dim_attr := dimension_attributes.get(column["dimension_column"])
                    )
                    and getattr(dim_attr, "attributeType", "").lower() == "sid"
                ),
                None,
            )
            if dimension_sid_column is None:
                dimension_sid_candidates = [
                    attr.name
                    for attr in dimension_attributes.values()
                    if getattr(attr, "attributeType", "").lower() == "sid"
                ]
                if dimension_sid_candidates:
                    dimension_sid_column = dimension_sid_candidates[0]
                else:
                    dimension_sid_column = join_columns[0]["dimension_column"]

            sid_column = next(
                (
                    column["fact_column"]
                    for column in join_columns
                    if (
                        fact_attr := fact_attributes.get(column["fact_column"])
                    )
                    and getattr(fact_attr, "attributeType", "").lower() == "sid"
                ),
                None,
            )
            if sid_column is None:
                sid_column = join_columns[0]["fact_column"]

            lookups.append(
                {
                    "sid_column": sid_column,
                    "join_columns": join_columns,
                    "dimension_zone": dimension_zone_meta.name,
                    "dimension_full_table_name": dimension_full_table_name,
                    "dimension_alias": f"dim_{target_entity.name}",
                    "dimension_sid_column": dimension_sid_column,
                    "dimension_dm8l": self.locator_to_dm8l(target_locator),
                }
            )

        return lookups

    def raw_sources(self, locator, entity) -> list[dict[str, Any]]:
        """Collect metadata about external/raw sources feeding the entity."""
        sources: list[dict[str, Any]] = []
        for source in getattr(entity, "sources", []):
            data_source = getattr(source, "dataSource", None)
            if not data_source:
                continue

            identifiers = self.raw_table_identifiers(locator, source)
            properties = _properties_to_dict(getattr(source, "properties", None))
            mapping_dict: dict[str, str] = {}
            mapping_entries: list[dict[str, Any]] = []
            for mapping in getattr(source, "mapping", []) or []:
                target_name = getattr(mapping, "targetName", None)
                source_name = getattr(mapping, "sourceName", None)
                if not target_name or not source_name:
                    continue
                mapping_dict[target_name] = source_name
                source_data_type = getattr(mapping, "sourceDataType", None)
                mapping_entries.append(
                    {
                        "target": target_name,
                        "source": source_name,
                        "properties": _properties_to_dict(getattr(mapping, "properties", None)),
                        "source_data_type": {
                            "type": getattr(source_data_type, "type", None),
                            "nullable": getattr(source_data_type, "nullable", None),
                        }
                        if source_data_type
                        else None,
                    }
                )

            delta_entry = next(
                (
                    entry
                    for entry in mapping_entries
                    if entry["properties"].get("extract_column") == "delta"
                ),
                None,
            )

            sources.append(
                {
                    "data_source": data_source,
                    "data_product": identifiers["data_product"],
                    "data_module": identifiers["data_module"],
                    "source_alias": getattr(source, "sourceAlias", None),
                    "table_name": identifiers["table_name"],
                    "raw_name": identifiers["table_name"],
                    "raw_full_table": identifiers["full_table_name"],
                    "full_table_name": identifiers["full_table_name"],
                    "properties": properties,
                    "mapping": mapping_dict,
                    "mapping_entries": mapping_entries,
                    "source_location": getattr(source, "sourceLocation", None),
                    "source_type": self._data_source_type_by_name.get(data_source),
                    "delta_column": delta_entry["target"] if delta_entry else None,
                    "source_delta_column": delta_entry["source"] if delta_entry else None,
                }
            )
        return sources

    def entity_dependencies(self, locator, entity) -> set[int]:
        """Return entity IDs referenced via the sources collection."""
        dependencies: set[int] = set()
        for source in getattr(entity, "sources", []) or []:
            source_location = getattr(source, "sourceLocation", None)
            if isinstance(source_location, int) and source_location in self._entity_by_id:
                dependencies.add(source_location)
        return dependencies

    def entity_source_references(self, entity) -> list[dict[str, str]]:
        """
        Collect DM8L references to upstream modeled entities.

        Entries originating from external sources are skipped.
        """
        references: list[dict[str, str]] = []
        for source in getattr(entity, "sources", []):
            if getattr(source, "dataSource", None):
                continue

            source_location = getattr(source, "sourceLocation", None)
            dm8l_path: str | None = None

            if isinstance(source_location, str):
                parts = [part for part in source_location.strip("/").split("/") if part]
                if parts:
                    zone_meta = self.zone_from_folder(parts[0])
                    zone_segment = zone_meta.name.capitalize() if zone_meta else parts[0]
                    dm8l_path = "/" + "/".join([zone_segment, *parts[1:]])
            elif isinstance(source_location, int):
                locator_entity = self._entity_by_id.get(source_location)
                if locator_entity:
                    locator, _ = locator_entity
                    dm8l_path = self.locator_to_dm8l(locator)

            if dm8l_path:
                references.append({"dm8l": dm8l_path})

        return references

    def collect_transformations(self, locator, entity) -> list[dict[str, Any]]:
        """Return function-based transformation metadata for the entity."""
        transformations: list[dict[str, Any]] = []
        folder_path = self.entity_folder_path(locator)
        for definition in getattr(entity, "transformations", []) or []:
            kind = getattr(definition, "kind", None)
            if kind is None and isinstance(definition, dict):
                kind = definition.get("kind")
            if hasattr(kind, "value"):
                kind_value = kind.value
            else:
                kind_value = kind
            if kind_value != "function":
                continue
            function_meta = getattr(definition, "function", None)
            if function_meta is None and isinstance(definition, dict):
                function_meta = definition.get("function")
            source_ref = None
            if function_meta is not None:
                source_ref = getattr(function_meta, "source", None)
                if source_ref is None and isinstance(function_meta, dict):
                    source_ref = function_meta.get("source")
            if not source_ref:
                continue

            script_relative = source_ref.lstrip("./")
            script_path = folder_path / script_relative
            script_content = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
            script_name = Path(script_relative).stem
            step_no = getattr(definition, "stepNo", None)
            if step_no is None and isinstance(definition, dict):
                step_no = definition.get("stepNo")
            display_name = getattr(definition, "name", None)
            if display_name is None and isinstance(definition, dict):
                display_name = definition.get("name")

            transformations.append(
                {
                    "step_no": step_no,
                    "name": display_name or script_name,
                    "script_name": script_path.name,
                    "script_module": f"{locator.entityName}_functions/{script_path.stem}",
                    "script_content": script_content,
                    "key": script_path.stem,
                    "merge_type": "replace",
                    "frequency": "no_restriction",
                    "sources": self.entity_source_references(entity),
                }
            )
        return transformations

    def stage_select_expressions(self, entity, raw_source: dict[str, Any]) -> list[str]:
        """Build selectExpr expressions for stage entities fed from raw sources."""
        expressions: list[str] = []
        mapping = raw_source.get("mapping", {})
        for attribute in getattr(entity, "attributes", []):
            source_expr = mapping.get(attribute.name, attribute.name)
            expressions.append(_select_expr(source_expr, attribute.name))

        expressions.extend(
            [
                "current_timestamp() AS __InsertTimestampUTC",
                "current_timestamp() AS __UpdateTimestampUTC",
                "__InsertTimestampUTC AS __InsertTimestampRawUTC",
            ]
        )
        return expressions

# --------------------------------------------------------------------- helpers
def collect_imports(columns: Iterable[dict[str, Any]]) -> list[str]:
    """
    Determine which pyspark types to import based on the generated columns.

    StructType and StructField are always required.
    """
    return ["StructType", "StructField", "DataType"]


def collect_column_tags(
    entity,
    *,
    include_attribute_tags: bool = True,
    include_mapping_tags: bool = True,
) -> list[dict[str, Any]]:
    """Return column-level tag assignments from attribute and mapping properties."""
    tag_map: dict[str, dict[str, Any]] = {}

    if include_attribute_tags:
        for attribute in getattr(entity, "attributes", []) or []:
            if not getattr(attribute, "properties", None):
                continue
            tags = {
                prop.property: _convert_property_value(prop.value)
                for prop in attribute.properties
            }
            if tags:
                tag_map[attribute.name] = tags

    if include_mapping_tags:
        for source in getattr(entity, "sources", []) or []:
            for mapping in getattr(source, "mapping", []) or []:
                if not getattr(mapping, "properties", None):
                    continue
                target_name = getattr(mapping, "targetName", None)
                if not target_name:
                    continue
                tags = tag_map.setdefault(target_name, {})
                for prop in mapping.properties:
                    name = getattr(prop, "property", None)
                    if not name:
                        continue
                    tags[name] = _convert_property_value(getattr(prop, "value", None))

    return [{"column": column, "tags_repr": repr(tags)} for column, tags in tag_map.items()]


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


def format_table_tag_values(tags: dict[str, Any]) -> dict[str, Any]:
    """Convert table tag values to notebook-friendly representations."""
    formatted: dict[str, Any] = {}
    for key, value in tags.items():
        if isinstance(value, bool):
            formatted[key] = "true" if value else "false"
        else:
            formatted[key] = value
    return formatted


def _to_bool_string(value: Any) -> str:
    """Convert a boolean-like value to a lowercase string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered
        return value
    return str(value)


def build_delta_table_properties(table_tags: dict[str, Any]) -> dict[str, str]:
    """Translate table tags into Delta table properties used in SQL DDL."""
    properties: dict[str, str] = {}

    column_mapping_mode = table_tags.get("column_mapping_mode")
    if column_mapping_mode:
        properties["delta.columnMapping.mode"] = str(column_mapping_mode)

    enable_type_widening = table_tags.get("enable_type_widening")
    if enable_type_widening is not None:
        properties["delta.enableTypeWidening"] = _to_bool_string(enable_type_widening)

    data_retention = table_tags.get("data_retention")
    if data_retention:
        interval_value = str(data_retention).replace("_", " ")
        if not interval_value.lower().startswith("interval"):
            interval_value = f"interval {interval_value}"
        properties["delta.logRetentionDuration"] = interval_value
        properties["delta.deletedFileRetentionDuration"] = interval_value

    return properties


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
    alias = _sanitize_identifier(getattr(source, "sourceAlias", None))
    if alias:
        return alias

    schema, table = _parse_source_location(getattr(source, "sourceLocation", None))
    fallback_parts = [_sanitize_identifier(schema), _sanitize_identifier(table)]
    fallback = "_".join(part for part in fallback_parts if part)
    return fallback or "raw_entity"
