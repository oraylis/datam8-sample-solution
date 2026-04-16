"""Shared metadata resolution and normalization helpers for Databricks templates."""

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
TARGET_PROPERTY_NAME = "target"

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
        key = str(name).strip().lower()
        if key in result:
            continue
        result[key] = _convert_property_value(getattr(prop, "value", None))
    return result


def _normalize_string_map(values: Any) -> dict[str, str]:
    """Normalize arbitrary mappings to a plain string dictionary."""
    if not isinstance(values, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in values.items():
        if key is None or value is None:
            continue
        normalized[str(key)] = str(value)
    return normalized


def _connector_id_from_plugin_id(plugin_id: Any) -> str | None:
    """Normalize DataSourceType.pluginId to the connector token used in code/templates."""
    if plugin_id is None:
        return None
    text = str(plugin_id).strip()
    if not text:
        return None

    # Support namespaced plugin IDs such as `builtin:SQLServer`.
    if ":" in text:
        text = text.split(":")[-1].strip()
    if not text:
        return None

    token = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_").lower()
    return token or None


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


def attribute_property_equals(attribute: Any, property_name: str, expected_value: str) -> bool:
    """Public helper to check an attribute property against an expected value."""
    return _attribute_property_equals(attribute, property_name, expected_value)


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
    properties: dict[str, Any]


@dataclass(frozen=True)
class FolderInfo:
    """Metadata about a folder (.properties.json) in the model tree."""

    name: str
    display_name: str | None
    data_product: str | None
    data_module: str | None
    properties: dict[str, Any]


@dataclass(frozen=True)
class PropertyScope:
    """Scope metadata loaded from Base/Properties.json for one property."""

    type_name: str
    single_usage: bool | None
    mandatory: bool | None


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

    @property
    @lru_cache
    def _property_scope_map(self) -> dict[str, list[PropertyScope]]:
        """Load property scope definitions from validated model properties."""
        definitions: dict[str, list[PropertyScope]] = {}
        for wrapper in self.model.properties.values():
            entry = wrapper.entity
            name = getattr(entry, "name", None)
            if not name:
                continue
            scopes: list[PropertyScope] = []
            for scope in getattr(entry, "scopes", []) or []:
                type_name = str(getattr(scope, "type", "")).strip().lower()
                if not type_name:
                    continue
                scopes.append(
                    PropertyScope(
                        type_name=type_name,
                        single_usage=getattr(scope, "singleUsage", None),
                        mandatory=getattr(scope, "mandatory", None),
                    )
                )
            definitions[str(name).strip().lower()] = scopes
        return definitions

    def _property_scopes(self, property_name: str) -> list[PropertyScope]:
        """Return configured scopes for a property."""
        if not property_name:
            return []
        return self._property_scope_map.get(property_name.strip().lower(), [])

    def property_supports_folder_scope(self, property_name: str) -> bool:
        """Return True when the property is allowed on folders."""
        scopes = self._property_scopes(property_name)
        if not scopes:
            return True
        return any(scope.type_name == "folder" for scope in scopes)

    def property_supports_model_scope(self, property_name: str) -> bool:
        """Return True when the property is allowed on model entities."""
        scopes = self._property_scopes(property_name)
        if not scopes:
            return True
        return any(scope.type_name == "entity" for scope in scopes)

    def property_supports_column_usage(self, property_name: str) -> bool:
        """Return True when the property may be used repeatedly at column level."""
        scopes = self._property_scopes(property_name)
        if not scopes:
            return True
        return any(
            scope.type_name == "entity" and scope.single_usage is False
            for scope in scopes
        )

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
            key = str(property_name).strip().lower()
            if key in result:
                continue
            result[key] = _convert_property_value(getattr(property_value, "name", None))
        return result

    def resolve_property(self, locator, entity, property_name: str) -> Any:
        """Resolve a property following scope rules defined in Base/Properties.json."""
        if not property_name:
            return None
        property_key = property_name.strip().lower()
        entity_props = self.entity_properties(entity)
        supports_model = self.property_supports_model_scope(property_key)
        supports_folder = self.property_supports_folder_scope(property_key)

        if supports_model and property_key in entity_props:
            return entity_props[property_key]

        if supports_folder:
            resolved_props = self._resolved_property_map(locator)
            if property_key in resolved_props:
                return resolved_props[property_key]

        # Backward-compatible fallback for properties without explicit scope metadata.
        if property_key in entity_props:
            return entity_props[property_key]

        return None

    def job_definition(self, job_value: str | None) -> dict[str, Any] | None:
        """Return job display metadata (name, schedule, cluster) for a job value."""
        if not job_value:
            return None

        try:
            job_entry = self.model.get_property_value(job_value, "jobs").entity
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
                schedule_entry = self.model.get_property_value(schedule_name, "schedules").entity
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
                cluster_entry = self.model.get_property_value(cluster_name, "cluster").entity
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
                properties=_properties_to_dict(getattr(zone_entity, "properties", None)),
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

    def is_target_zone(self, zone: ZoneMetadata | None) -> bool:
        """Return True when zone property `target` resolves to this generator target."""
        if zone is None:
            return False
        target = zone.properties.get(TARGET_PROPERTY_NAME)
        if target is None:
            return False
        return str(target).strip().lower() == TARGET_NAME

    def is_model_backed_zone(self, zone: ZoneMetadata | None) -> bool:
        """Return True when the zone targets this generator and has a local folder."""
        return bool(zone and zone.local_folder and self.is_target_zone(zone))

    def model_backed_zones(self) -> list[ZoneMetadata]:
        """Return zones that should be processed through model entities."""
        return [zone for zone in self.zones() if self.is_model_backed_zone(zone)]

    def external_zones(self) -> list[ZoneMetadata]:
        """Return target zones without local folders used for external ingestion."""
        return [zone for zone in self.zones() if self.is_target_zone(zone) and not zone.local_folder]

    def default_external_zone(self) -> ZoneMetadata | None:
        """Return the first external zone in definition order."""
        zones = self.external_zones()
        return zones[0] if zones else None

    # ------------------------------------------------------------- Folder info
    @lru_cache
    def folder_info(self, folder_tuple: tuple[str, ...]) -> FolderInfo:
        """Return folder metadata from the validated folder entities."""
        if not folder_tuple:
            return FolderInfo(name="", display_name=None, data_product=None, data_module=None, properties={})

        wrapped_folder = self._folder_wrapper(folder_tuple)
        if wrapped_folder is None:
            return FolderInfo(
                name=folder_tuple[-1],
                display_name=None,
                data_product=None,
                data_module=None,
                properties={},
            )

        folder_entity = wrapped_folder.entity
        return FolderInfo(
            name=getattr(folder_entity, "name", folder_tuple[-1]) or folder_tuple[-1],
            display_name=getattr(folder_entity, "displayName", None),
            data_product=getattr(folder_entity, "dataProduct", None),
            data_module=getattr(folder_entity, "dataModule", None),
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
        - source entries by name
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

            source_key = str(source_name).strip().lower()
            entries[source_key] = source_entity
            type_by_name[source_key] = getattr(source_entity, "type", None)

            source_mappings: dict[str, str] = {}
            for mapping in getattr(source_entity, "dataTypeMapping", []) or []:
                source_type = getattr(mapping, "sourceType", None)
                target_type = getattr(mapping, "targetType", None)
                if not source_type or not target_type:
                    continue
                source_mappings[source_type.lower()] = _normalize_canonical(target_type)
            mapping_by_name[source_key] = source_mappings

        return entries, type_by_name, mapping_by_name

    @property
    @lru_cache
    def _data_source_type_entries(self) -> dict[str, Any]:
        """Expose data source type entities by normalized name."""
        entries: dict[str, Any] = {}
        for wrapper in self.model.dataSourceTypes.values():
            source_type_entity = wrapper.entity
            type_name = getattr(source_type_entity, "name", None)
            if not type_name:
                continue
            entries[str(type_name).strip().lower()] = source_type_entity
        return entries

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

    def data_source_extended_properties(self, data_source_name: str) -> dict[str, str]:
        """Return normalized extended properties for a data source."""
        source_key = str(data_source_name).strip().lower()
        source_entity = self.data_sources.get(source_key)
        if source_entity is None:
            return {}
        return _normalize_string_map(getattr(source_entity, "extendedProperties", None))

    def data_source_connector_id(self, data_source_name: str) -> str | None:
        """Resolve connector id via bound DataSourceType.pluginId."""
        source_key = str(data_source_name).strip().lower()
        source_type_name = self._data_source_type_by_name.get(source_key)
        if not source_type_name:
            return None
        source_type = self._data_source_type_entries.get(str(source_type_name).strip().lower())
        if source_type is None:
            return None
        return _connector_id_from_plugin_id(
            getattr(source_type, "pluginId", None) or getattr(source_type, "plugin_id", None)
        )

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
        Map an external-source data type to its canonical representation using the data source
        specific mapping, falling back to the data source type mapping when necessary.
        """
        source_key = str(data_source_name).strip().lower()
        source_type_lower = source_type.lower()

        canonical = self._data_source_mapping_by_name.get(source_key, {}).get(source_type_lower)
        if canonical:
            return canonical

        data_source_type = self._data_source_type_by_name.get(source_key)
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
            yield source, self.data_sources.get(str(data_source_name).strip().lower())

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
        """Create column descriptors for a modeled entity (non-external)."""
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

    def build_external_columns(self, entity, source) -> list[dict[str, Any]]:
        """
        Create column descriptors for an external-ingestion notebook.

        The method reads the source mapping to determine the target column names
        and source data types. When no explicit mapping is present, it falls
        back to the modeled attributes (old behaviour).
        """
        columns = self.build_external_base_columns()

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

    def build_external_base_columns(self) -> list[dict[str, Any]]:
        """Default ingestion columns for external-ingestion notebooks."""
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

    def _folders_after_zone(self, locator) -> tuple[str, ...]:
        """Return folder segments below the zone segment."""
        if not locator or not getattr(locator, "folders", None):
            return ()
        return tuple(locator.folders[1:])

    def output_folder_segments(self, locator) -> tuple[str, ...]:
        """
        Return folder segments for generated output paths.

        The method prefers inherited dataProduct/dataModule attributes and falls back
        to the existing folder hierarchy when attributes are missing.
        """
        segments = list(self._folders_after_zone(locator))
        product_name, module_name = self.inherited_product_module_values(locator)

        if product_name:
            if segments:
                segments[0] = product_name
            else:
                segments.append(product_name)

        if module_name:
            if len(segments) >= 2:
                segments[1] = module_name
            elif len(segments) == 1:
                segments.append(module_name)
            else:
                segments.extend(["UnknownProduct", module_name])

        return tuple(segment for segment in segments if segment)

    def _folder_chain(self, locator) -> list[FolderInfo]:
        """Return folder metadata for each ancestor after the zone."""
        folders = getattr(locator, "folders", None) or []
        chain: list[FolderInfo] = []
        for depth in range(2, len(folders) + 1):
            chain.append(self.folder_info(tuple(folders[:depth])))
        return chain

    def inherited_product_module_values(self, locator) -> tuple[str | None, str | None]:
        """Return inherited dataProduct/dataModule values without folder-name fallback."""
        data_product_name: str | None = None
        data_module_name: str | None = None
        for folder in reversed(self._folder_chain(locator)):
            if data_product_name is None and folder.data_product:
                data_product_name = folder.data_product
            if data_module_name is None and folder.data_module:
                data_module_name = folder.data_module
            if data_product_name and data_module_name:
                break
        return data_product_name, data_module_name

    def product_module_context(self, locator) -> tuple[FolderInfo | None, FolderInfo | None, str, str]:
        """Resolve effective data product/module names using folder attributes first."""
        folders_after_zone = self._folders_after_zone(locator)
        product_info = self.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = self.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name, data_module_name = self.inherited_product_module_values(locator)

        if not data_product_name:
            data_product_name = folders_after_zone[0] if folders_after_zone else "UnknownProduct"
        if not data_module_name:
            data_module_name = folders_after_zone[1] if len(folders_after_zone) > 1 else "General"

        return product_info, module_info, data_product_name, data_module_name

    def full_table_name(
        self,
        locator,
        table_name: str,
        *,
        data_product_name: str | None = None,
        data_module_name: str | None = None,
    ) -> str:
        """Build a table name from dataProduct/dataModule, or full folder fallback."""
        if data_product_name and data_module_name:
            parts = [data_product_name, data_module_name, table_name]
        else:
            parts = [*self._folders_after_zone(locator), table_name]
        return "_".join(part for part in parts if part)

    def modeled_table_identifiers(self, locator, entity_name: str) -> dict[str, str]:
        """Derive naming components for modeled tables."""
        _, _, data_product_name, data_module_name = self.product_module_context(locator)
        inherited_product, inherited_module = self.inherited_product_module_values(locator)
        return {
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": entity_name,
            "full_table_name": self.full_table_name(
                locator,
                entity_name,
                data_product_name=inherited_product,
                data_module_name=inherited_module,
            ),
        }

    def external_table_identifiers(self, locator, source) -> dict[str, str]:
        """Derive naming components for an external-ingestion table based on folders and source alias."""
        table_name = build_external_source_name(source) or "external_entity"
        _, _, data_product_name, data_module_name = self.product_module_context(locator)
        inherited_product, inherited_module = self.inherited_product_module_values(locator)
        return {
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": table_name,
            "full_table_name": self.full_table_name(
                locator,
                table_name,
                data_product_name=inherited_product,
                data_module_name=inherited_module,
            ),
        }

    # ----------------------------------------------------------- Entity extras
    def entity_folder_path(self, locator) -> Path:
        """Return the filesystem path to the module folder that contains entities."""
        return self.model_root.joinpath(*locator.folders)

    def entity_script_folder_path(self, locator) -> Path:
        """Return the filesystem path to the entity-specific script folder."""
        base = self.entity_folder_path(locator)
        entity_name = getattr(locator, "entityName", None) or ""
        return base / entity_name if entity_name else base

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

    def write_mode(self, locator, entity, default: str = "overwrite") -> str:
        """Resolve write mode via scope-aware property lookup."""
        value = self.resolve_property(locator, entity, "write_mode")
        if value:
            return str(value).lower()
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

            identifiers = self.modeled_table_identifiers(locator, entity.name)
            data_product_name = identifiers["data_product"]
            data_module_name = identifiers["data_module"]
            full_table_name = identifiers["full_table_name"]

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

                dimension_identifiers = self.modeled_table_identifiers(target_locator, target_entity.name)
                dimension_full_table_name = dimension_identifiers["full_table_name"]
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

            dimension_identifiers = self.modeled_table_identifiers(target_locator, target_entity.name)
            dimension_full_table_name = dimension_identifiers["full_table_name"]

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

    def external_sources(self, locator, entity) -> list[dict[str, Any]]:
        """Collect metadata about external sources feeding the entity."""
        sources: list[dict[str, Any]] = []
        for source in getattr(entity, "sources", []):
            data_source = getattr(source, "dataSource", None)
            if not data_source:
                continue

            identifiers = self.external_table_identifiers(locator, source)
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
                    "external_name": identifiers["table_name"],
                    "external_full_table": identifiers["full_table_name"],
                    "full_table_name": identifiers["full_table_name"],
                    "properties": properties,
                    "mapping": mapping_dict,
                    "mapping_entries": mapping_entries,
                    "source_location": getattr(source, "sourceLocation", None),
                    "source_type": self._data_source_type_by_name.get(
                        str(data_source).strip().lower()
                    ),
                    "connector_id": self.data_source_connector_id(str(data_source)),
                    "data_source_extended_properties": self.data_source_extended_properties(
                        str(data_source)
                    ),
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
        folder_path = self.entity_script_folder_path(locator)
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
            if not script_path.exists():
                logger.warning(
                    "Transformation script not found for entity '%s': %s",
                    getattr(locator, "entityName", "<unknown>"),
                    script_path,
                )
                script_content = ""
            else:
                script_content = script_path.read_text(encoding="utf-8")
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

    def stage_select_expressions(self, entity, external_source: dict[str, Any]) -> list[str]:
        """Build selectExpr expressions for stage entities fed from external sources."""
        expressions: list[str] = []
        for attribute in getattr(entity, "attributes", []):
            expression = getattr(attribute, "expression", None)
            if expression:
                expressions.append(f"{expression} AS `{attribute.name}`")
                continue
            # External-source tables already use modeled/target column names, so select them directly.
            expressions.append(f"`{attribute.name}`")

        source_label = (
            external_source.get("source_alias")
            or external_source.get("external_full_table")
            or external_source.get("table_name")
            or external_source.get("data_source")
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
    resolver: MetadataResolver | None = None,
    include_attribute_tags: bool = True,
    include_mapping_tags: bool = True,
) -> list[dict[str, Any]]:
    """Return column-level tag assignments from attribute and mapping properties."""
    tag_map: dict[str, dict[str, Any]] = {}

    if include_attribute_tags:
        for attribute in getattr(entity, "attributes", []) or []:
            if not getattr(attribute, "properties", None):
                continue
            tags: dict[str, Any] = {}
            for prop in attribute.properties:
                name = getattr(prop, "property", None)
                if not name:
                    continue
                if resolver and not resolver.property_supports_column_usage(name):
                    continue
                tags[name] = _convert_property_value(prop.value)
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
                    if resolver and not resolver.property_supports_column_usage(name):
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
    *,
    resolver: MetadataResolver | None = None,
) -> dict[str, Any]:
    """Combine table-level properties from product, module, and entity definitions."""
    tags: dict[str, Any] = {}
    if product_info:
        for key, value in product_info.properties.items():
            if resolver and not resolver.property_supports_folder_scope(key):
                continue
            tags[key] = value
    if module_info:
        for key, value in module_info.properties.items():
            if resolver and not resolver.property_supports_folder_scope(key):
                continue
            tags[key] = value
    if entity.properties:
        for prop in entity.properties:
            key = getattr(prop, "property", None)
            if not key:
                continue
            if resolver and not resolver.property_supports_model_scope(key):
                continue
            tags[key] = _convert_property_value(prop.value)
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
    """Use business-key attributes as partition columns for non-external tables."""
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


def build_external_source_name(source) -> str:
    """Derive an external-ingestion table/filename from source alias/location."""
    alias = _sanitize_identifier(getattr(source, "sourceAlias", None))
    if alias:
        return alias

    schema, table = _parse_source_location(getattr(source, "sourceLocation", None))
    fallback_parts = [_sanitize_identifier(schema), _sanitize_identifier(table)]
    fallback = "_".join(part for part in fallback_parts if part)
    return fallback or "external_entity"
