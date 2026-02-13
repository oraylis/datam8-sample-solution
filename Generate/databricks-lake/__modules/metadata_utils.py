from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from datam8 import config
from datam8.utils import start_logger

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


def _value_or_default(value: Any, default: Any) -> Any:
    """Return default when value is None, preserving other falsy values."""
    return default if value is None else value


def _normalize_canonical(name: str | None) -> str:
    """Normalize canonical data type names for lookups."""
    if not name:
        return "string"
    lower = name.strip().lower()
    return TYPE_ALIASES.get(lower, lower)


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


def _attribute_property_equals(attribute: Any, property_name: str, expected_value: str) -> bool:
    """Check if an attribute exposes a property matching the provided value."""
    props = getattr(attribute, "properties", None) or []
    if not props:
        return False
    target_name = (property_name or "").strip().lower()
    target_value = (expected_value or "").strip().lower()
    if not target_name:
        return False
    for prop in props:
        name = getattr(prop, "property", None)
        if not name:
            continue
        if str(name).strip().lower() != target_name:
            continue
        value = getattr(prop, "value", None)
        if value is None:
            continue
        if str(value).strip().lower() == target_value:
            return True
    return False


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


def _slug(value: str | None) -> str:
    """Generate a filesystem-safe slug from a value."""
    if not value:
        return "default"
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    return cleaned or "default"


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

    @lru_cache
    def _model_entity_by_id(self, entity_id: int) -> tuple[Any, Any] | None:
        """Resolve a model entity by id via the central model API."""
        try:
            wrapped = self.model.get_model_entity_by_id(entity_id)
        except Exception:  # noqa: BLE001 - not-found and parsing errors should not break generation
            return None
        return wrapped.locator, wrapped.entity

    @lru_cache
    def _folder_wrapper(self, folder_tuple: tuple[str, ...]) -> Any | None:
        """Resolve a folder via the central model API with case-insensitive fallback."""
        if not folder_tuple:
            return None

        locator_path = "folders/" + "/".join(folder_tuple)
        try:
            return self.model.get_entity_by_locator(locator_path)
        except Exception:  # noqa: BLE001 - fallback below handles mixed casing
            pass

        normalized = tuple(part.lower() for part in folder_tuple)
        for locator, wrapper in self.model.folders.items():
            locator_tuple = tuple([*getattr(locator, "folders", []), getattr(locator, "entityName", "")])
            if tuple(part.lower() for part in locator_tuple) == normalized:
                return wrapper
        return None

    # ------------------------------------------------------ Property values
    @property
    @lru_cache
    def _property_values_map(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Split validated property values into job, schedule, and cluster lookups."""
        jobs: dict[str, Any] = {}
        schedules: dict[str, Any] = {}
        clusters: dict[str, Any] = {}
        for wrapper in self.model.propertyValues.values():
            entity = wrapper.entity
            name = getattr(entity, "name", None)
            prop = getattr(entity, "property", None)
            if not name:
                continue
            if prop == "jobs":
                jobs[name] = entity
            elif prop == "schedules":
                schedules[name] = entity
            elif prop == "cluster":
                clusters[name] = entity
        return jobs, schedules, clusters

    @lru_cache
    def _resolved_property_map(self, locator) -> dict[str, Any]:
        """
        Resolve effective properties for an entity via EntityWrapper resolution.

        This includes inherited folder properties resolved by the core model.
        """
        try:
            wrapped = self.model.get_entity_by_locator(locator)
        except Exception:  # noqa: BLE001 - unresolved locators should not break generation
            return {}

        try:
            property_values = wrapped.properties.values()
        except Exception:  # noqa: BLE001 - unresolved wrapper state
            return {}

        result: dict[str, Any] = {}
        for property_value in property_values:
            property_name = getattr(property_value, "property", None)
            if not property_name:
                continue
            result[property_name] = _convert_property_value(getattr(property_value, "name", None))
        return result

    def resolve_property(self, locator, entity, property_name: str) -> Any:
        """Resolve an entity property using entity-first and wrapper-resolved fallback."""
        entity_props = self.entity_properties(entity)
        if property_name in entity_props:
            return entity_props[property_name]

        resolved_props = self._resolved_property_map(locator)
        if property_name in resolved_props:
            return resolved_props[property_name]

        return None

    def job_definition(self, job_value: str | None) -> dict[str, Any] | None:
        """Return job display metadata (name, schedule, cluster) for a job value."""
        if not job_value:
            return None

        try:
            job_entry = self.model.get_property_value("jobs", job_value).entity
        except Exception:  # noqa: BLE001 - missing/invalid property value should not break generation
            return None

        schedule_name = None
        cluster_name = getattr(job_entry, "cluster", None)
        for prop in getattr(job_entry, "properties", []) or []:
            prop_name = getattr(prop, "property", None)
            prop_value = getattr(prop, "value", None)
            if prop_name == "schedules":
                schedule_name = prop_value
            elif prop_name == "cluster":
                cluster_name = prop_value

        schedule_entry = None
        if schedule_name:
            try:
                schedule_entry = self.model.get_property_value("schedules", schedule_name).entity
            except Exception:  # noqa: BLE001 - schedule reference is optional
                schedule_entry = None
        schedule_data = None
        if schedule_entry:
            schedule_data = {
                "name": schedule_name,
                "display_name": _value_or_default(getattr(schedule_entry, "displayName", None), schedule_name),
                "cron": getattr(schedule_entry, "cron", None),
            }

        cluster_entry = None
        if cluster_name:
            try:
                cluster_entry = self.model.get_property_value("cluster", cluster_name).entity
            except Exception:  # noqa: BLE001 - cluster reference is optional
                cluster_entry = None
        cluster_data = None
        if cluster_entry:
            cluster_data = {
                "name": cluster_name,
                "display_name": _value_or_default(getattr(cluster_entry, "displayName", None), cluster_name),
                "node_type": getattr(cluster_entry, "node_type", None),
                "num_workers": getattr(cluster_entry, "num_workers", None),
                "workload_type": getattr(cluster_entry, "workload_type", None),
                "spark_version": getattr(cluster_entry, "spark_version", None),
                "autotermination_minutes": getattr(cluster_entry, "autotermination_minutes", None),
                "variable_name": self.cluster_variable_name(cluster_name),
            }

        return {
            "value": job_value,
            "display_name": _value_or_default(getattr(job_entry, "displayName", None), job_value),
            "cluster": cluster_data,
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
        """Load zone metadata from the validated model once."""
        folder_map: dict[str, ZoneMetadata] = {}
        name_map: dict[str, ZoneMetadata] = {}

        for wrapper in self.model.zones.values():
            zone_entity = wrapper.entity
            zone_name = getattr(zone_entity, "name", "")
            zone = ZoneMetadata(
                name=zone_name,
                display_name=getattr(zone_entity, "displayName", None) or zone_name,
                target_name=getattr(zone_entity, "targetName", None) or zone_name,
                local_folder=getattr(zone_entity, "localFolderName", None),
            )
            if zone.local_folder:
                folder_map[zone.local_folder.lower()] = zone
            if zone.name:
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
        """Return folder metadata from the validated folder entities."""
        if not folder_tuple:
            return FolderInfo(name="", display_name=None, properties={})

        wrapped_folder = self._folder_wrapper(folder_tuple)
        if wrapped_folder is None:
            return FolderInfo(name=folder_tuple[-1], display_name=None, properties={})

        folder_entity = wrapped_folder.entity
        return FolderInfo(
            name=getattr(folder_entity, "name", folder_tuple[-1]) or folder_tuple[-1],
            display_name=getattr(folder_entity, "displayName", None),
            properties=_properties_to_dict(getattr(folder_entity, "properties", None)),
        )

    # ----------------------------------------------------------- Data sources
    @property
    @lru_cache
    def _data_source_details(
        self,
    ) -> tuple[dict[str, Any], dict[str, str | None], dict[str, dict[str, str]]]:
        """
        Load validated data sources and derive:
        - raw entries by name
        - source type per data source (e.g. SqlDataSource)
        - source-specific type mappings (sourceType -> canonical type)
        """
        entries: dict[str, Any] = {}
        type_by_name: dict[str, str | None] = {}
        mapping_by_name: dict[str, dict[str, str]] = {}

        for wrapper in self.model.dataSources.values():
            source_entity = wrapper.entity
            source_name = getattr(source_entity, "name", None)
            if not source_name:
                continue

            entries[source_name] = source_entity
            type_by_name[source_name] = getattr(source_entity, "type", None)

            source_mappings: dict[str, str] = {}
            for mapping in getattr(source_entity, "dataTypeMapping", []) or []:
                source_type = getattr(mapping, "sourceType", None)
                target_type = getattr(mapping, "targetType", None)
                if not source_type or not target_type:
                    continue
                source_mappings[source_type.lower()] = _normalize_canonical(target_type)
            mapping_by_name[source_name] = source_mappings

        return entries, type_by_name, mapping_by_name

    @property
    @lru_cache
    def data_sources(self) -> dict[str, Any]:
        """Expose data sources by name."""
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
        Load validated data source types to provide fallback mappings for a source type.

        Some sources (e.g. Oracle) may not have an explicit type definition; in that case
        the resolver falls back to an empty mapping.
        """
        type_mappings: dict[str, dict[str, str]] = {}
        for wrapper in self.model.dataSourceTypes.values():
            source_type_entity = wrapper.entity
            type_name = getattr(source_type_entity, "name", None)
            if not type_name:
                continue
            mappings: dict[str, str] = {}
            for mapping in getattr(source_type_entity, "dataTypeMapping", []) or []:
                source_name = getattr(mapping, "sourceType", None)
                target_name = getattr(mapping, "targetType", None)
                if not source_name or not target_name:
                    continue
                mappings[source_name.lower()] = _normalize_canonical(target_name)
            type_mappings[type_name] = mappings
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

    def iter_external_sources(self, entity) -> Iterable[tuple[Any, Any | None]]:
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
        mapping: dict[str, str] = {}
        for wrapper in self.model.dataTypes.values():
            data_type_entity = wrapper.entity
            name = getattr(data_type_entity, "name", None)
            if not name:
                continue
            targets = getattr(data_type_entity, "targets", {}) or {}
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
    def attribute_metadata(self, attribute, *, foreign_key_table: str | None = None) -> dict[str, Any]:
        """Derive metadata flags for an attribute."""
        metadata: dict[str, Any] = {}
        if getattr(attribute, "isBusinessKey", False):
            metadata["business_key"] = True
        if _attribute_property_equals(attribute, "attribute_type", "sk"):
            metadata["surrogate_key"] = True
        if foreign_key_table:
            metadata["foreign_key"] = True
            metadata["foreign_key_table"] = foreign_key_table
        return metadata

    def build_standard_columns(self, entity, *, foreign_key_columns: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Create column descriptors for a modeled entity (non-raw)."""
        columns: list[dict[str, Any]] = []
        fk_columns = foreign_key_columns or {}
        for attribute in entity.attributes:
            extra_metadata = self.attribute_metadata(
                attribute,
                foreign_key_table=fk_columns.get(attribute.name),
            )
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
            else:
                kind_value = None

            name = getattr(transformation, "name", None)

            if (
                kind_value == "builtin"
                and name
                and name.lower() == "lookup_dimensions"
            ):
                return True
        return False

    def _resolve_model_entity_reference(self, reference) -> tuple[Any, Any] | None:
        """Resolve model entity references via core model APIs."""
        if reference is None:
            return None

        if isinstance(reference, int):
            return self._model_entity_by_id(reference)

        if not isinstance(reference, str):
            return None

        search_target = reference.strip()
        if not search_target:
            return None

        normalized = search_target.removeprefix("/").strip()
        candidates: list[str] = []

        if normalized.lower().startswith("modelentities/"):
            candidates.append(normalized)
        elif "/" in normalized:
            candidates.append(f"modelEntities/{normalized}")
            parts = [part for part in normalized.split("/") if part]
            if parts:
                zone = self.zone_by_name(parts[0])
                if zone:
                    zone_folder = self.zone_folder_name(zone)
                    candidates.append(f"modelEntities/{zone_folder}/{'/'.join(parts[1:])}")

        for candidate in candidates:
            try:
                wrapped = self.model.get_entity_by_locator(candidate)
            except Exception:  # noqa: BLE001 - continue with next candidate/fallback
                continue
            return wrapped.locator, wrapped.entity

        # Fallback for DM8L-style references where direct locator normalization is ambiguous.
        for candidate_locator, candidate_wrapper in self.model.modelEntities.items():
            if self.locator_to_dm8l(candidate_locator) == search_target:
                return candidate_locator, candidate_wrapper.entity

        return None

    def _relationship_target_entity(self, relationship):
        """Resolve the locator/entity referenced by a relationship's target."""
        target_location = getattr(relationship, "targetLocation", None)
        resolved = self._resolve_model_entity_reference(target_location)
        if resolved is None:
            return None, None
        return resolved

    def foreign_key_columns(self, entity) -> dict[str, str]:
        """Return mapping of attribute name -> foreign dimension table."""
        fk_columns: dict[str, str] = {}
        relationships = getattr(entity, "relationships", []) or []
        if not relationships:
            return fk_columns

        for relationship in relationships:
            target_locator, target_entity = self._relationship_target_entity(relationship)
            if target_entity is None:
                continue

            dimension_zone_meta = self.zone_from_folder(target_locator.folders[0]) if getattr(target_locator, "folders", None) else None
            if dimension_zone_meta is None:
                continue

            target_attributes = {
                attribute.name: attribute for attribute in getattr(target_entity, "attributes", [])
            }

            mappings = getattr(relationship, "attributes", None)

            for mapping in mappings or []:
                source_name = getattr(mapping, "sourceName", None)
                target_name = getattr(mapping, "targetName", None)
                if not source_name or not target_name:
                    continue
                target_attribute = target_attributes.get(target_name)
                if not target_attribute:
                    continue
                if not _attribute_property_equals(target_attribute, "attribute_type", "sk"):
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
                referenced_table = f"{dimension_zone_meta.name}.{dimension_full_table_name}"
                fk_columns[source_name] = referenced_table

        return fk_columns

    def cluster_variable_name(self, cluster_name: str | None) -> str | None:
        """Return the variable name for a cluster value."""
        if not cluster_name:
            return None
        return f"cluster_{_slug(cluster_name)}"

    def cluster_definitions(self) -> list[dict[str, Any]]:
        """Return cluster definitions from PropertyValues."""
        _, _, clusters = self._property_values_map
        definitions: list[dict[str, Any]] = []
        for name, entry in clusters.items():
            definitions.append(
                {
                    "name": name,
                    "display_name": _value_or_default(getattr(entry, "displayName", None), name),
                    "node_type": _value_or_default(getattr(entry, "node_type", None), "Standard_D4ds_v5"),
                    "num_workers": _value_or_default(getattr(entry, "num_workers", None), 2),
                    "workload_type": _value_or_default(getattr(entry, "workload_type", None), "job"),
                    "spark_version": _value_or_default(getattr(entry, "spark_version", None), "16.4.x-scala2.12"),
                    "autotermination_minutes": _value_or_default(getattr(entry, "autotermination_minutes", None), 60),
                    "data_security_mode": _value_or_default(getattr(entry, "data_security_mode", None), "DATA_SECURITY_MODE_DEDICATED"),
                    "runtime_engine": _value_or_default(getattr(entry, "runtime_engine", None), "STANDARD"),
                    "variable_name": self.cluster_variable_name(name),
                    "is_default": bool(getattr(entry, "default", False)),
                }
            )
        return definitions

    def default_cluster_variable_name(self) -> str | None:
        """Return the variable name for the default cluster."""
        definitions = self.cluster_definitions()
        for entry in definitions:
            if entry.get("is_default"):
                return entry.get("variable_name")
        return definitions[0]["variable_name"] if definitions else None

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
            target_locator, target_entity = self._relationship_target_entity(relationship)
            if not target_locator or target_entity is None or not getattr(target_locator, "folders", None):
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
            dimension_business_keys = [
                attr.name for attr in dimension_attributes.values() if getattr(attr, "isBusinessKey", False)
            ]
            dimension_surrogate_keys = [
                attr.name
                for attr in dimension_attributes.values()
                if _attribute_property_equals(attr, "attribute_type", "sk")
            ]

            join_mappings = getattr(relationship, "attributes", None)

            relationship_join_columns: list[dict[str, str]] = []
            sk_fact_columns: list[str] = []
            if join_mappings:
                for mapping in join_mappings:
                    fact_column = getattr(mapping, "sourceName", None)
                    dimension_column = getattr(mapping, "targetName", None)
                    if not fact_column or not dimension_column:
                        continue
                    relationship_join_columns.append(
                        {"fact_column": fact_column, "dimension_column": dimension_column}
                    )
                    target_attribute = dimension_attributes.get(dimension_column)
                    if target_attribute and _attribute_property_equals(
                        target_attribute, "attribute_type", "sk"
                    ):
                        sk_fact_columns.append(fact_column)

            if not relationship_join_columns or not sk_fact_columns:
                continue

            # Determine which fact column receives the surrogate key update.
            sid_column = next((column for column in sk_fact_columns if column), None)
            if sid_column is None:
                for column in relationship_join_columns:
                    fact_attr = fact_attributes.get(column["fact_column"])
                    if fact_attr and (
                        getattr(fact_attr, "attributeType", "").lower() == "sid"
                        or _attribute_property_equals(fact_attr, "attribute_type", "sk")
                    ):
                        sid_column = column["fact_column"]
                        break
            if sid_column is None and relationship_join_columns:
                sid_column = relationship_join_columns[0]["fact_column"]
            if sid_column is None:
                sid_column = next(
                    (
                        name
                        for name, attr in fact_attributes.items()
                        if getattr(attr, "attributeType", "").lower() == "sid"
                        or _attribute_property_equals(attr, "attribute_type", "sk")
                    ),
                    None,
                )
            if sid_column is None:
                continue

            join_columns: list[dict[str, str]] = []
            if dimension_business_keys:
                seen_pairs: set[tuple[str, str]] = set()
                for bk in dimension_business_keys:
                    fact_column = next(
                        (
                            column["fact_column"]
                            for column in relationship_join_columns
                            if column["dimension_column"] == bk
                        ),
                        None,
                    )
                    if fact_column is None:
                        fact_column = bk
                    key = (fact_column, bk)
                    if fact_column and key not in seen_pairs:
                        join_columns.append({"fact_column": fact_column, "dimension_column": bk})
                        seen_pairs.add(key)

            if not join_columns:
                join_columns = relationship_join_columns

            if not join_columns:
                continue

            dimension_sid_column = None
            if dimension_surrogate_keys:
                dimension_sid_column = dimension_surrogate_keys[0]
            if dimension_sid_column is None:
                dimension_sid_column = next(
                    (
                        column["dimension_column"]
                        for column in relationship_join_columns
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
                elif dimension_surrogate_keys:
                    dimension_sid_column = dimension_surrogate_keys[0]
                else:
                    dimension_sid_column = join_columns[0]["dimension_column"]

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

    def entity_dependencies(self, entity) -> set[int]:
        """Return entity IDs referenced via the sources collection."""
        dependencies: set[int] = set()
        for source in getattr(entity, "sources", []) or []:
            source_location = getattr(source, "sourceLocation", None)
            if isinstance(source_location, int) and self._model_entity_by_id(source_location):
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
                resolved = self._resolve_model_entity_reference(source_location)
                if resolved:
                    dm8l_path = self.locator_to_dm8l(resolved[0])
                else:
                    parts = [part for part in source_location.strip("/").split("/") if part]
                    if parts:
                        zone_meta = self.zone_from_folder(parts[0])
                        zone_segment = zone_meta.name.capitalize() if zone_meta else parts[0]
                        dm8l_path = "/" + "/".join([zone_segment, *parts[1:]])
            elif isinstance(source_location, int):
                locator_entity = self._model_entity_by_id(source_location)
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
            if hasattr(kind, "value"):
                kind_value = kind.value
            else:
                kind_value = kind
            if kind_value != "function":
                continue
            function_meta = getattr(definition, "function", None)
            source_ref = None
            if function_meta is not None:
                source_ref = getattr(function_meta, "source", None)
            if not source_ref:
                continue

            script_relative = source_ref.lstrip("./")
            script_path = folder_path / script_relative
            script_content = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
            script_name = Path(script_relative).stem
            step_no = getattr(definition, "stepNo", None)
            display_name = getattr(definition, "name", None)

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
                    "source_literal": repr(display_name or script_name),
                }
            )
        return transformations

    def stage_select_expressions(self, entity, raw_source: dict[str, Any]) -> list[str]:
        """Build selectExpr expressions for stage entities fed from raw sources."""
        expressions: list[str] = []
        for attribute in getattr(entity, "attributes", []):
            # Calculated columns (with expressions) are materialized later in the notebook.
            if getattr(attribute, "expression", None):
                continue
            # Raw tables already use the modeled/target column names, so select them directly.
            expressions.append(f"`{attribute.name}`")

        source_label = (
            raw_source.get("source_alias")
            or raw_source.get("raw_full_table")
            or raw_source.get("table_name")
            or raw_source.get("data_source")
            or "_unknown_source"
        )
        expressions.append(f"{repr(source_label)} AS __SourceTable")
        expressions.extend(
            [
                "current_timestamp() AS __InsertTimestampUTC",
                "current_timestamp() AS __UpdateTimestampUTC",
                "__InsertTimestampUTC AS __InsertTimestampRawUTC",
            ]
        )
        return expressions

    def calculated_columns(self, entity) -> list[dict[str, Any]]:
        """Return SQL-based calculated columns defined on the entity attributes."""
        calculated: list[dict[str, Any]] = []
        for attribute in getattr(entity, "attributes", []) or []:
            expression = getattr(attribute, "expression", None)
            if not expression:
                continue
            language = getattr(attribute, "expressionLanguage", None)
            if hasattr(language, "value"):
                language_value = language.value
            else:
                language_value = (language or "sql")
            language_value = str(language_value).lower()
            if language_value != "sql":
                continue
            calculated.append(
                {
                    "name": attribute.name,
                    "expression": expression,
                    "expression_literal": repr(expression),
                    "language": language_value,
                }
            )
        return calculated

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
