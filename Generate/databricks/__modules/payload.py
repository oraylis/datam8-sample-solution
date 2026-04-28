"""
Module to prepare payload to be rendered by DataM8.

* each payload function is processed in a separate thread
* each payload instance of a function is rendered in a async manor
* a payloads need to implement the IPayload protocol which just requires two functions
    - get_data() -> object // object available as `data` in template
    - get_output_path() -> Path // path where the rendered template gets saved to
* payloads can be split across multiple files and import via their filename/path within the
    `__modules` directory
* the cache can be used to carry over generated value or similar across payloads
    - it would technically also be possible to create a dummy payload that returns an empty list
        and simply adds some values to the cache

Some notes/explanations to lean into the way the payloads/templates are rendered and make debugging
simpler.

* payloads only "gath" entities to be rendered and do some slight initialization
* payloads contain references to the model, wrapper and any additional entity to allow for further
    lookups
* most logic is implemented on the payload itself as a function or property, so that it gets
    executed within the asynchronous call
* a search locator used in `get_many` and `get_many_where` needs to end on with a "/", otherwise
    DataM8 will look for an entity with that exact locator
* use match statements for structural pattern matching to avoid inreadable chains of if-elif-else
    blocks
* prefer returning basic types or objects of classes defined in the payload itself, to narrow
    potential errors to the payload itself and not errors thrown by DataM8 itself or be affected
    by changes within DataM8 or its model
* retrieving an entity by its locator via `get()` is faster than using `get_where()` with a filter
* all functions return an EntityWrapper instance, with an entity attribute containing the content of
    the corresponding json file

"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datam8 import logging
from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import EntityWrapper, Model
from datam8.utils.cache import Cache
from datam8_model.attribute import Attribute, HistoryType
from datam8_model.data_type import DataType, DataTypeDefinition
from datam8_model.folder import Folder
from datam8_model.model import ExternalModelSource, ModelEntity
from datam8_model.property import PropertyReference
from datam8_model.zone import Zone

logger = logging.getLogger(__name__)

TARGET = "databricks"


def create_resource_slug_from_name(name: str) -> str:
    resource_slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    if len(resource_slug) == 0:
        return "default"
    return resource_slug


def create_task_key(*parts: str) -> str:
    value = "_".join(part for part in parts if part)
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "task"


class DatabricksModel:
    def __init__(self, model: Model) -> None:
        self.model = model

    @staticmethod
    def zone_target_name(zone: EntityWrapper[Zone]) -> str:
        return zone.entity.targetName or zone.entity.name

    @staticmethod
    def zone_folder_name(zone: EntityWrapper[Zone]) -> str:
        return zone.entity.localFolderName or zone.entity.targetName or zone.entity.name

    @staticmethod
    def zone_display_name(zone: EntityWrapper[Zone]) -> str:
        return zone.entity.displayName

    @staticmethod
    def zone_targets_databricks(zone: EntityWrapper[Zone]) -> bool:
        return any(
            ref.property == "target" and ref.value == TARGET for ref in zone.entity.properties or []
        )

    @property
    def model_backed_zones(self) -> list[EntityWrapper[Zone]]:
        return [
            zone
            for zone in self.model.zones.values()
            if self.zone_targets_databricks(zone) and zone.entity.localFolderName
        ]

    @property
    def external_zone(self) -> EntityWrapper[Zone]:
        for zone in self.model.zones.values():
            if self.zone_targets_databricks(zone) and not zone.entity.localFolderName:
                return zone
        raise ValueError(
            "No external Databricks zone found. Configure a Databricks zone without localFolderName."
        )

    def zone_for_folder(self, folder: str) -> EntityWrapper[Zone] | None:
        for zone in self.model.zones.values():
            if zone.entity.localFolderName == folder and self.zone_targets_databricks(zone):
                return zone
        return None

    @property
    def model_entity_wrappers(self) -> list[EntityWrapper[ModelEntity]]:
        wrappers: list[EntityWrapper[ModelEntity]] = []
        for zone in self.model_backed_zones:
            wrappers.extend(self.model.modelEntities.get_many(f"{zone.entity.localFolderName}/"))
        return wrappers

    @staticmethod
    def property_values_by_name(
        refs: Iterable[PropertyReference] | None, property_name: str
    ) -> list[str]:
        return [ref.value for ref in refs or [] if ref.property == property_name]

    @staticmethod
    def collect_transformations(wrapper: EntityWrapper[ModelEntity]) -> list[dict[str, Any]]:
        transformations: list[dict[str, Any]] = []
        frequency = next(
            (pv.name for pv in wrapper.properties.values() if pv.property == "frequency"),
            "no_restriction",
        )
        for transform in wrapper.entity.transformations or []:
            function = getattr(transform, "function", None)
            script_name = getattr(function, "source", None) if function is not None else None
            if not script_name:
                continue
            script_stem = Path(script_name).stem
            script_path = wrapper.source_file.parent / wrapper.entity.name / script_name
            if not script_path.exists():
                script_path = wrapper.source_file.parent / script_name
            transformations.append(
                {
                    "key": script_stem,
                    "name": transform.name,
                    "merge_type": "replace",
                    "frequency": frequency,
                    "sources": [],
                    "script_name": script_name,
                    "script_module": f"{wrapper.entity.name}_functions/{script_stem}",
                    "script_content": script_path.read_text(encoding="utf-8"),
                }
            )
        return transformations

    @property
    def default_cluster_variable(self) -> str:
        for pv in self.model.propertyValues.get_many("cluster/"):
            if pv.entity.default:
                return f"cluster_{create_resource_slug_from_name(pv.entity.name)}"
        clusters = self.model.propertyValues.get_many("cluster/")
        return f"cluster_{create_resource_slug_from_name(clusters[0].entity.name)}" if clusters else ""

    @staticmethod
    def job_property(wrapper: EntityWrapper[Any]) -> str:
        return next((pv.name for pv in wrapper.properties.values() if pv.property == "jobs"), "daily")

    def schedule_for_job(self, job_name: str) -> dict[str, str] | None:
        job = self.model.propertyValues.get(f"jobs/{job_name}").entity
        schedules = self.property_values_by_name(job.properties, "schedules")
        if not schedules:
            return None
        schedule = self.model.propertyValues.get(f"schedules/{schedules[0]}").entity
        return {
            "cron_expression": getattr(schedule, "quartz_cron_expression", "49 0 1 * * ?"),
            "timezone_id": "UTC",
        }

    def cluster_for_job(self, job_name: str) -> str:
        job = self.model.propertyValues.get(f"jobs/{job_name}").entity
        clusters = self.property_values_by_name(job.properties, "cluster")
        if clusters:
            return f"cluster_{create_resource_slug_from_name(clusters[0])}"
        return self.default_cluster_variable


class ExternalSourcePayload:
    def __init__(
        self,
        model: Model,
        wrapper: EntityWrapper[ModelEntity],
        source: ExternalModelSource,
    ) -> None:
        self.model = model
        self.wrapper = wrapper
        self.source = source
        self.source_zone = DatabricksModel.zone_target_name(DatabricksModel(model).external_zone)
        self.data_source_entry = model.dataSources.get(source.dataSource).entity

    @property
    def table_name(self) -> str:
        return self.source.sourceAlias or self.wrapper.entity.name

    @property
    def full_table_name(self) -> str:
        return "_".join([self.data_product, self.data_module, self.table_name])

    @property
    def key(self) -> str:
        return create_task_key(self.source_zone, self.full_table_name)

    @property
    def external_table(self) -> str:
        return self.table_name

    @property
    def external_full_table(self) -> str:
        return self.full_table_name

    @property
    def data_product(self) -> str:
        return self.wrapper.locator.folders[1] if len(self.wrapper.locator.folders) > 1 else "default"

    @property
    def data_module(self) -> str:
        return self.wrapper.locator.folders[2] if len(self.wrapper.locator.folders) > 2 else "default"

    @property
    def data_source(self) -> str:
        return self.source.dataSource

    @property
    def data_source_display(self) -> str:
        return self.data_source_entry.displayName or self.data_source

    @property
    def data_source_type(self) -> str:
        return self.data_source_entry.type

    @property
    def data_source_extended_properties(self) -> dict[str, Any]:
        return self.data_source_entry.extendedProperties or {}

    @property
    def source_alias(self) -> str:
        return self.source.sourceAlias or self.table_name

    @property
    def source_name(self) -> str:
        return self.source.sourceAlias or self.table_name

    @property
    def source_location(self) -> str:
        return self.source.sourceLocation or self.table_name

    @property
    def properties(self) -> dict[str, str]:
        return {ref.property: ref.value for ref in self.source.properties or []}

    @property
    def extract_mode(self) -> str | None:
        return self.properties.get("extract_mode")

    @property
    def mapping(self) -> Sequence[Any] | None:
        return self.source.mapping

    @property
    def mapping_entries(self) -> Sequence[Any]:
        return self.source.mapping or []

    @property
    def type_mappings(self) -> dict[str, str]:
        data_source_type = self.model.dataSourceTypes.get(self.data_source_entry.type).entity
        mappings = {m.sourceType: m.targetType for m in data_source_type.dataTypeMapping or []}
        mappings.update({m.sourceType: m.targetType for m in self.data_source_entry.dataTypeMapping or []})
        return mappings

    @property
    def select_columns(self) -> list[str]:
        columns: list[str] = []
        mappings_by_target = {mapping.targetName: mapping for mapping in self.mapping_entries}
        for attr in self.wrapper.entity.attributes:
            if expr := (getattr(attr, "calculation", None) or getattr(attr, "expression", None)):
                columns.append(f"{expr} AS `{attr.name}`")
                continue
            mapping = mappings_by_target.get(attr.name)
            if mapping is not None:
                columns.append(f"`{mapping.targetName}`")
        return columns

    @property
    def target_columns(self) -> list[str]:
        columns: list[str] = []
        mappings_by_target = {mapping.targetName: mapping for mapping in self.mapping_entries}
        for attr in self.wrapper.entity.attributes:
            if getattr(attr, "calculation", None) or getattr(attr, "expression", None):
                columns.append(attr.name)
                continue
            mapping = mappings_by_target.get(attr.name)
            if mapping is not None:
                columns.append(mapping.targetName)
        return columns

    @property
    def column_renames(self) -> list[dict[str, str]]:
        return [
            {"source": mapping.sourceName, "target": mapping.targetName}
            for mapping in self.mapping_entries
            if mapping.sourceName != mapping.targetName
        ]

    @property
    def delta_column_details(self) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for mapping in self.mapping_entries:
            props = {ref.property: ref.value for ref in mapping.properties or []}
            if props.get("extract_mode") != "delta":
                continue
            data_type = mapping.sourceDataType.type if mapping.sourceDataType else ""
            details.append(
                {
                    "source": mapping.sourceName,
                    "target": mapping.targetName,
                    "type": self.type_mappings.get(data_type, data_type),
                }
            )
        return details

    @property
    def select_expressions(self) -> list[str]:
        return [
            *self.select_columns,
            f"'{self.table_name}' AS __SourceTable",
            "current_timestamp() AS __InsertTimestampUTC",
            "current_timestamp() AS __UpdateTimestampUTC",
            "__InsertTimestampUTC AS __InsertTimestampExternalUTC",
        ]


class MergeConfig:
    def __init__(
        self,
        entity: ModelEntity,
        history: dict[str, list[str]],
        attribute_names: list[str],
        *,
        write_mode: str,
        include_external_timestamp: bool,
        include_source_table: bool,
        include_business_function: bool,
    ) -> None:
        self.entity = entity
        self.history = history
        self.attribute_names = attribute_names
        self.write_mode = write_mode
        self.include_external_timestamp = include_external_timestamp
        self.include_source_table = include_source_table
        self.include_business_function = include_business_function

    @staticmethod
    def assignment_literal(column: str, expression: str) -> dict[str, str]:
        return {"column": column, "expression": repr(expression)}

    @staticmethod
    def scd0_helper_name(column: str) -> str:
        sanitized = re.sub(r"\W+", "_", column or "").strip("_") or "value"
        return f"__scd0__{sanitized}"

    @property
    def business_keys(self) -> list[str]:
        return self.history["business_keys"]

    @property
    def sk_columns(self) -> set[str]:
        return {
            attr.name
            for attr in self.entity.attributes
            if any(
                ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
                for ref in attr.properties or []
            )
        }

    @property
    def enabled(self) -> bool:
        return self.write_mode == "merge" and bool(self.business_keys)

    @property
    def assignment_names(self) -> list[str]:
        if self.write_mode == "merge" and self.sk_columns:
            return [name for name in self.attribute_names if name not in self.sk_columns]
        return self.attribute_names

    @property
    def scd0_columns(self) -> list[str]:
        return self.history["scd0"]

    @property
    def scd1_columns(self) -> list[str]:
        columns = [name for name in self.history["scd1"] if name not in self.business_keys]
        if self.write_mode == "merge" and self.sk_columns:
            columns = [name for name in columns if name not in self.sk_columns]
        return columns

    @property
    def scd2_non_business_columns(self) -> list[str]:
        columns = [name for name in self.history["scd2"] if name not in self.business_keys]
        if self.write_mode == "merge" and self.sk_columns:
            columns = [name for name in columns if name not in self.sk_columns]
        return columns

    @property
    def has_scd2_history(self) -> bool:
        return bool(self.scd2_non_business_columns)

    @property
    def scd0_helper_columns(self) -> list[dict[str, str]]:
        return [
            {"column": column, "helper": self.scd0_helper_name(column)}
            for column in self.scd0_columns
        ]

    @property
    def scd0_helper_lookup(self) -> dict[str, str]:
        return {entry["column"]: entry["helper"] for entry in self.scd0_helper_columns}

    @property
    def scd1_update_assignments(self) -> list[dict[str, str]]:
        assignments = [
            self.assignment_literal(name, f"src.`{name}`") for name in self.scd1_columns
        ]
        if self.scd1_columns:
            assignments.append(
                self.assignment_literal("__UpdateTimestampUTC", "src.__UpdateTimestampUTC")
            )
        return assignments

    @property
    def scd1_change_condition(self) -> str:
        return " OR ".join(
            f"NOT (tgt.`{column}` <=> src.`{column}`)" for column in self.scd1_columns
        )

    @property
    def insert_assignments(self) -> list[dict[str, str]]:
        technical_columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
        if self.include_business_function:
            technical_columns.append("__BusinessFunction")
        if self.include_source_table:
            technical_columns.append("__SourceTable")
        if self.include_external_timestamp:
            technical_columns.append("__InsertTimestampExternalUTC")

        assignments = [
            self.assignment_literal(column, f"src.{column}") for column in technical_columns
        ]
        assignments.extend(
            self.assignment_literal(name, f"src.`{name}`") for name in self.assignment_names
        )
        return assignments

    @property
    def merge_condition(self) -> str:
        return " AND ".join(f"tgt.`{col}` <=> src.`{col}`" for col in self.business_keys)


class ModelEntityPayload(BasePayload):
    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        self.wrapper = wrapper
        self.model = model
        self.entity = wrapper.entity
        self.zone_wrapper = model.get_zone_for_entity(wrapper)

    def get_data(self) -> object:
        return self

    @property
    def zone_name(self) -> str:
        return DatabricksModel.zone_target_name(self.zone_wrapper)

    @property
    def zone(self) -> str:
        return self.zone_name

    @property
    def zone_display(self) -> str:
        return DatabricksModel.zone_display_name(self.zone_wrapper)

    @property
    def data_product(self) -> str:
        return self.wrapper.locator.folders[1] if len(self.wrapper.locator.folders) > 1 else "default"

    @property
    def data_module(self) -> str:
        return self.wrapper.locator.folders[2] if len(self.wrapper.locator.folders) > 2 else "default"

    @property
    def table_name(self) -> str:
        return self.entity.name

    @property
    def full_table_name(self) -> str:
        return "_".join([*self.wrapper.locator.folders[1:], self.table_name])

    def wrapper_property(self, property_name: str, default: str | None = None) -> str | None:
        return next(
            (pv.name for pv in self.wrapper.properties.values() if pv.property == property_name),
            default,
        )

    @property
    def surrogate_key_columns(self) -> list[str]:
        return [
            attr.name
            for attr in self.entity.attributes
            if any(
                ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
                for ref in attr.properties or []
            )
        ]


class DmlNotebookPayload(ModelEntityPayload):
    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        model: Model,
        transformations: list[dict[str, Any]],
    ) -> None:
        super().__init__(wrapper, model)
        self.transformations = transformations

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            DatabricksModel.zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.wrapper.locator.entityName or self.entity.name}.py",
        )

    @property
    def history(self) -> dict[str, list[str]]:
        history = {
            "business_keys": [attr.name for attr in self.entity.attributes if attr.isBusinessKey],
            "scd0": [],
            "scd1": [],
            "scd2": [],
        }
        for attr in self.entity.attributes:
            match attr.history:
                case HistoryType.SCD0:
                    history["scd0"].append(attr.name)
                case HistoryType.SCD2:
                    history["scd2"].append(attr.name)
                case _:
                    history["scd1"].append(attr.name)
        return history

    @property
    def attribute_columns(self) -> list[str]:
        return [attr.name for attr in self.entity.attributes]

    @property
    def source_mode(self) -> str:
        if self.transformations:
            return "transformation"
        if self.external_source_items:
            return "external_delta"
        return "none"

    @property
    def has_external_source(self) -> bool:
        return bool(self.external_source_items)

    @property
    def include_external_timestamp(self) -> bool:
        return self.source_mode == "external_delta"

    @property
    def include_source_table(self) -> bool:
        return self.source_mode == "external_delta"

    @property
    def include_business_function(self) -> bool:
        return not self.has_external_source

    @property
    def write_mode(self) -> str:
        return self.wrapper_property("write_mode", "overwrite")

    @property
    def spark_write_mode(self) -> str:
        return {"overwrite": "overwrite", "append": "append"}.get(self.write_mode, "overwrite")

    @property
    def external_source_items(self) -> list[ExternalSourcePayload]:
        return [
            ExternalSourcePayload(self.model, self.wrapper, source)
            for source in self.wrapper.entity.sources or []
            if getattr(source, "dataSource", None)
        ]

    @property
    def external_sources(self) -> list[ExternalSourcePayload]:
        return self.external_source_items

    @property
    def final_function_key(self) -> str | None:
        return self.transformations[-1]["key"] if self.transformations else None

    @property
    def business_keys(self) -> list[str]:
        return self.history["business_keys"]

    @property
    def non_business_columns(self) -> list[str]:
        return [name for name in self.attribute_columns if name not in self.business_keys]

    @property
    def schema_columns(self) -> list[str]:
        columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
        if self.include_business_function:
            columns.append("__BusinessFunction")
        if self.include_source_table:
            columns.append("__SourceTable")
        if self.include_external_timestamp:
            columns.append("__InsertTimestampExternalUTC")
        columns.extend(self.attribute_columns)
        return columns

    @property
    def write_schema_columns(self) -> list[str]:
        return [column for column in self.schema_columns if column not in self.surrogate_key_columns]

    @property
    def merge_config(self) -> MergeConfig:
        return MergeConfig(
            self.entity,
            self.history,
            self.attribute_columns,
            write_mode=self.write_mode,
            include_external_timestamp=self.include_external_timestamp,
            include_source_table=self.include_source_table,
            include_business_function=self.include_business_function,
        )

    @property
    def merge_conditions_flat(self) -> str:
        return self.merge_config.merge_condition

    @property
    def source_references(self) -> list[Any]:
        return []

    @property
    def has_lookup_dimensions(self) -> bool:
        return False

    @property
    def dimension_lookups(self) -> list[Any]:
        return []

    @property
    def insert_assignments(self) -> list[dict[str, str]]:
        return self.merge_config.insert_assignments

    @property
    def scd0_columns(self) -> list[str]:
        return self.history["scd0"]

    @property
    def scd0_helper_columns(self) -> list[dict[str, str]]:
        return self.merge_config.scd0_helper_columns

    @property
    def scd0_helper_lookup(self) -> dict[str, str]:
        return self.merge_config.scd0_helper_lookup

    @property
    def scd1_columns(self) -> list[str]:
        return self.history["scd1"]

    @property
    def scd1_non_business_columns(self) -> list[str]:
        return [name for name in self.scd1_columns if name not in self.business_keys]

    @property
    def scd2_columns(self) -> list[str]:
        return self.history["scd2"]

    @property
    def scd2_non_business_columns(self) -> list[str]:
        return self.merge_config.scd2_non_business_columns

    @property
    def has_scd2_history(self) -> bool:
        return bool(self.scd2_columns)

    @property
    def external_merge_config(self) -> MergeConfig | None:
        if self.merge_config.enabled and self.external_source_items:
            return self.merge_config
        return None

    @property
    def final_merge_config(self) -> MergeConfig | None:
        if self.merge_config.enabled and self.transformations:
            return self.merge_config
        return None

    @property
    def calculated_columns(self) -> list[dict[str, str]]:
        columns: list[dict[str, str]] = []
        for attr in self.entity.attributes:
            expr = getattr(attr, "calculation", None) or getattr(attr, "expression", None)
            if expr:
                columns.append({"name": attr.name, "expression_literal": repr(expr)})
        return columns


class DmlExternalNotebookPayload(ModelEntityPayload):
    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        model: Model,
        source: ExternalModelSource,
    ) -> None:
        super().__init__(wrapper, model)
        self.source = source
        self.external_source = ExternalSourcePayload(model, wrapper, source)
        self.zone_wrapper = DatabricksModel(model).external_zone
        self.current = ExternalSourcePayload(model, wrapper, source)
        self.data_source_entry = model.dataSources.get(self.current.data_source).entity

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            DatabricksModel.zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.table_name}.py",
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return getattr(self.current, name)
        except AttributeError:
            raise AttributeError(name) from None

    @property
    def zone(self) -> str:
        return DatabricksModel.zone_target_name(self.zone_wrapper)

    @property
    def zone_display(self) -> str:
        return DatabricksModel.zone_display_name(self.zone_wrapper)

    @property
    def data_source_display(self) -> str:
        return self.data_source_entry.displayName or self.current.data_source

    @property
    def table_name(self) -> str:
        return self.current.table_name

    @property
    def full_table_name(self) -> str:
        return self.current.full_table_name

    @property
    def write_mode(self) -> str:
        return "overwrite" if self.extract_mode == "overwrite" else "append"

    @property
    def use_connector(self) -> bool:
        return bool(getattr(self.data_source_entry, "connector", None))

    @property
    def connector_id(self) -> str | None:
        return getattr(self.data_source_entry, "connector", None)

    @property
    def is_query(self) -> bool:
        return str(self.extract_mode or "").lower() == "query"

    @property
    def query_plan(self) -> dict[str, Any]:
        return {
            "is_query": self.is_query,
            "has_delta_filter": str(self.extract_mode or "").lower() == "delta",
            "timestamp_delta": False,
            "delta_columns_csv": ", ".join(item["source"] for item in self.delta_column_details),
        }

    @property
    def driver(self) -> str:
        return "com.microsoft.sqlserver.jdbc.SQLServerDriver"

    @property
    def connection_secret_key(self) -> str:
        return f"datasource-{self.current.data_source}-password"

    @property
    def delta_column(self) -> str | None:
        if self.delta_column_details:
            return self.delta_column_details[0]["target"]
        return None

    @property
    def source_delta_column(self) -> str | None:
        if self.delta_column_details:
            return self.delta_column_details[0]["source"]
        return None


class DmlFunctionPayload(ModelEntityPayload):
    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        zone: EntityWrapper[Zone],
        model: Model,
        transform: dict[str, Any],
    ) -> None:
        super().__init__(wrapper, model)
        self.zone_wrapper = zone
        self.transform = transform

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            DatabricksModel.zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.wrapper.locator.entityName}_functions",
            self.transform["script_name"],
        )

    @property
    def content(self) -> str:
        return self.transform["script_content"]


@register_payload("ddl_notebook.jinja2")
def ddl_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    return [DdlPayload(wrapper, model) for wrapper in DatabricksModel(model).model_entity_wrappers]


@register_payload("ddl_notebook.jinja2")
def ddl_external_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    external_source_zone = DatabricksModel(model).model_backed_zones[0]
    return [
        DdlExternalPayload(wrapper, model, source)
        for wrapper in model.modelEntities.get_many(
            f"{external_source_zone.entity.localFolderName}/"
        )
        for source in wrapper.entity.sources or []
        if getattr(source, "dataSource", None)
    ]


@register_payload("schema.yml.jinja2")
def dab_schemas(model: Model, cache: Cache) -> Sequence[IPayload]:
    return [
        BasePayload(
            data=[
                {
                    "resource_key": f"schema_{create_resource_slug_from_name(DatabricksModel.zone_target_name(zone))}",
                    "name": DatabricksModel.zone_target_name(zone),
                    "comment": DatabricksModel.zone_display_name(zone),
                }
                for zone in model.zones.values()
                if DatabricksModel.zone_targets_databricks(zone)
            ],
            output_path=Path("schemas", "schema.yml"),
        )
    ]


@register_payload("clusters.yml.jinja2")
def dab_cluster(model: Model, cache: Cache) -> Sequence[IPayload]:
    clusters = [wrapper.entity for wrapper in model.propertyValues.get_many("cluster/")]
    if len(clusters) == 0:
        return []
    return [
        BasePayload(
            data=[
                {
                    "name": cluster.name,
                    "display_name": cluster.displayName or cluster.name,
                    "node_type": getattr(cluster, "node_type", "Standard_D4ds_v5"),
                    "num_workers": getattr(cluster, "num_workers", None),
                    "workload_type": getattr(cluster, "workload_type", "job"),
                    "spark_version": getattr(cluster, "spark_version", "16.4.x-scala2.12"),
                    "autotermination_minutes": getattr(cluster, "autotermination_minutes", 60),
                    "data_security_mode": getattr(
                        cluster, "data_security_mode", "DATA_SECURITY_MODE_DEDICATED"
                    ),
                    "runtime_engine": getattr(cluster, "runtime_engine", "STANDARD"),
                    "variable_name": f"cluster_{create_resource_slug_from_name(cluster.name)}",
                    "is_default": cluster.default or False,
                    "custom_tags": {},
                }
                for cluster in clusters
            ],
            output_path=Path("clusters", "clusters.yml"),
        )
    ]


@register_payload("dml_notebook.jinja2", order=2)
def dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for wrapper in DatabricksModel(model).model_entity_wrappers:
        transformations = DatabricksModel.collect_transformations(wrapper)
        cache.set(f"dml_transformations::{wrapper.locator}", transformations)
        payloads.append(DmlNotebookPayload(wrapper, model, transformations))
    return payloads


@register_payload("dml_external_notebook.jinja2", order=2)
def dml_external_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    external_source_zone = DatabricksModel(model).model_backed_zones[0]
    for wrapper in model.modelEntities.get_many(f"{external_source_zone.entity.localFolderName}/"):
        for source in wrapper.entity.sources or []:
            if not getattr(source, "dataSource", None):
                continue
            payloads.append(DmlExternalNotebookPayload(wrapper, model, source))
    return payloads


@register_payload("dml_function.jinja2", order=2)
def dml_function_scripts(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for wrapper in DatabricksModel(model).model_entity_wrappers:
        zone = model.get_zone_for_entity(wrapper)
        try:
            transformations = cache.get(f"dml_transformations::{wrapper.locator}")
        except KeyError:
            transformations = DatabricksModel.collect_transformations(wrapper)
        for transform in transformations:
            payloads.append(DmlFunctionPayload(wrapper, zone, model, transform))
    return payloads


class DdlColumn:
    def __init__(self, attr: Attribute, model: Model) -> None:
        self.attribute = attr
        self.model = model

    @property
    def type_definition(self) -> DataTypeDefinition:
        return self.model.dataTypes.get(self.attribute.dataType.type).entity

    @property
    def target_type(self) -> str:
        target_type = self.type_definition.targets[TARGET]
        match [
            self.attribute.dataType.precision,
            self.attribute.dataType.scale,
            self.attribute.dataType.charLen,
        ]:
            case [int() as precision, None, None]:
                if target_type.lower() == "decimal":
                    target_type += f"({precision})"
            case [int() as precision, int() as scale, None]:
                if target_type.lower() == "decimal":
                    target_type += f"({precision}, {scale})"
            case [None, None, int()]:
                pass
            case [None, None, None]:
                pass
            case _:
                logger.warning("Invalid combination of precision, scale and charLen")
        return target_type

    @property
    def spark_data_type_expression(self) -> str:
        return f"{self.target_type}".upper()

    @property
    def spark_nullable(self) -> str:
        return " NULL" if self.attribute.dataType.nullable else " NOT NULL"

    @property
    def spark_comment(self) -> str:
        if self.attribute.description is None:
            return ""
        return f" COMMENT '{self.attribute.description}'"

    @property
    def is_surrogate_key(self) -> bool:
        return any(
            ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
            for ref in self.attribute.properties or []
        )

    @property
    def spark_identity(self) -> str:
        return " GENERATED ALWAYS AS IDENTITY" if self.is_surrogate_key else ""

    @property
    def name(self) -> str:
        return self.attribute.name

    @property
    def spark_type_expr(self) -> str:
        return f'DataType.fromDDL("{self.spark_data_type_expression}")'

    @property
    def struct_nullable(self) -> bool:
        return self.attribute.dataType.nullable

    @property
    def metadata_repr(self) -> str:
        metadata: dict[str, Any] = {}
        if self.attribute.description:
            metadata["comment"] = self.attribute.description
        if self.attribute.isBusinessKey:
            metadata["business_key"] = True
        return repr(metadata) if metadata else ""

    @property
    def sql_definition(self) -> str:
        nullable = "" if self.attribute.dataType.nullable else " NOT NULL"
        return f"`{self.name}` {self.spark_data_type_expression}{nullable}{self.spark_comment}"


@dataclasses.dataclass
class RenderedDdlColumn:
    name: str
    spark_data_type_expression: str
    nullable: bool
    comment: str | None = None
    business_key: bool = False

    @property
    def spark_type_expr(self) -> str:
        return f'DataType.fromDDL("{self.spark_data_type_expression}")'

    @property
    def struct_nullable(self) -> bool:
        return self.nullable

    @property
    def metadata_repr(self) -> str:
        metadata: dict[str, Any] = {}
        if self.comment:
            metadata["comment"] = self.comment
        if self.business_key:
            metadata["business_key"] = True
        return repr(metadata) if metadata else ""

    @property
    def sql_definition(self) -> str:
        nullable = "" if self.nullable else " NOT NULL"
        comment = f" COMMENT '{self.comment}'" if self.comment else ""
        return f"`{self.name}` {self.spark_data_type_expression}{nullable}{comment}"


class DdlExternalColumn(DdlColumn):
    @property
    def type_definition(self) -> DataTypeDefinition:
        return DataTypeDefinition(
            name=self.attribute.dataType.type,
            targets={TARGET: self.attribute.dataType.type},
        )

    @property
    def target_type(self) -> str:
        for data_type in self.model.dataTypes.values():
            if data_type.entity.name == self.attribute.dataType.type:
                return data_type.entity.targets[TARGET]
        return self.type_definition.targets[TARGET]


class DdlPayload(ModelEntityPayload):
    imports: list[str] = ["StructType", "StructField", "DataType"]
    is_external = False

    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        super().__init__(wrapper, model)
        self.locator = wrapper.locator
        self.first_folder: EntityWrapper[Folder] = model.folders.get(
            "/".join(self.locator.folders[0:2])
        )

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            DatabricksModel.zone_folder_name(self.zone_wrapper),
            "ddl",
            *self.wrapper.locator.folders[1:],
            f"{self.entity.name or self.locator.entityName}.py",
        )

    @property
    def table_comment(self) -> str:
        return self.entity.description or ""

    @property
    def columns(self) -> Sequence[DdlColumn | RenderedDdlColumn]:
        columns: list[DdlColumn | RenderedDdlColumn] = [
            *self.technical_columns,
            *[DdlColumn(attr, self.model) for attr in self.entity.attributes],
        ]
        if self.has_scd2_history:
            columns.extend(self.scd2_tracking_columns)
        return columns

    @property
    def technical_columns(self) -> list[RenderedDdlColumn]:
        columns = [
            RenderedDdlColumn("__InsertTimestampUTC", "TIMESTAMP", False, "Load timestamp (UTC)"),
            RenderedDdlColumn(
                "__UpdateTimestampUTC", "TIMESTAMP", False, "Last update timestamp (UTC)"
            ),
        ]
        has_external_source = any(
            getattr(source, "dataSource", None) for source in self.entity.sources or []
        )
        has_transformation = bool(self.entity.transformations)
        if has_transformation and not has_external_source:
            columns.append(
                RenderedDdlColumn(
                    "__BusinessFunction", "STRING", False, "Business function identifier"
                )
            )
        if has_external_source:
            columns.append(
                RenderedDdlColumn(
                    "__InsertTimestampExternalUTC", "TIMESTAMP", False, "External load timestamp (UTC)"
                )
            )
            columns.append(
                RenderedDdlColumn("__SourceTable", "STRING", False, "Origin reference for the record")
            )
        return columns

    @property
    def scd2_tracking_columns(self) -> list[RenderedDdlColumn]:
        return [
            RenderedDdlColumn("__ValidFrom", "TIMESTAMP", False, "SCD2 start date"),
            RenderedDdlColumn("__ValidTo", "TIMESTAMP", False, "SCD2 end date"),
            RenderedDdlColumn("__IsCurrent", "BOOLEAN", False, "SCD2 current flag"),
        ]

    @property
    def has_scd2_history(self) -> bool:
        return any([attr.history == HistoryType.SCD2 for attr in self.entity.attributes])

    @property
    def partitions(self) -> list[str]:
        return [attribute.name for attribute in self.entity.attributes if attribute.isBusinessKey]

    @property
    def table_properties(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            match [pv.property, pv.name]:
                case ["table_properties", "column_mapping"]:
                    discovered["delta.columnMapping.mode"] = "name"
                case ["table_properties", "type_widening"]:
                    discovered["delta.enableTypeWidening"] = "true"
                case ["data_retention", str() as name]:
                    interval_value = name.replace("_", " ")
                    if not interval_value.lower().startswith("interval"):
                        interval_value = f"interval {interval_value}"
                    discovered["delta.logRetentionDuration"] = interval_value
                    discovered["delta.deletedFileRetentionDuration"] = interval_value
                case _:
                    pass
        order = [
            "delta.columnMapping.mode",
            "delta.enableTypeWidening",
            "delta.logRetentionDuration",
            "delta.deletedFileRetentionDuration",
        ]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def table_tags(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            if pv.property == "table_properties":
                discovered.setdefault("table_properties", []).append(pv.name)
            elif pv.property in {"business_area", "jobs", "write_mode", "data_retention"}:
                discovered[pv.property] = pv.name
        order = ["business_area", "jobs", "table_properties", "write_mode", "data_retention"]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def table_tags_repr(self) -> str:
        return repr(self.table_tags)

    @property
    def has_table_tags(self) -> bool:
        return bool(self.table_tags)

    @property
    def column_tags(self) -> list[dict[str, str]]:
        tags_by_column: dict[str, dict[str, str]] = {}
        for attr in self.entity.attributes:
            if attr.properties:
                tags_by_column.setdefault(attr.name, {}).update(
                    {ref.property: ref.value for ref in attr.properties}
                )
        for source in self.entity.sources or []:
            for mapping in source.mapping or []:
                if mapping.properties:
                    tags_by_column.setdefault(mapping.targetName, {}).update(
                        {ref.property: ref.value for ref in mapping.properties}
                    )
        return [
            {"column": attr.name, "tags_repr": repr(tags_by_column[attr.name])}
            for attr in self.entity.attributes
            if attr.name in tags_by_column
        ]

    @property
    def refactored_columns(self) -> list[dict[str, str | Sequence[str]]]:
        return [
            {"name": attr.name, "aliases": attr.refactorNames}
            for attr in self.entity.attributes
            if attr.refactorNames is not None and len(attr.refactorNames) > 0
        ]

    @property
    def create_table_sql(self) -> str:
        lines = [
            f"CREATE TABLE IF NOT EXISTS {{catalog_name}}.{{zone}}.{self.full_table_name} (",
        ]
        for index, column in enumerate(self.columns):
            comma = "," if index < len(self.columns) - 1 else ""
            lines.append(f"  {column.sql_definition}{comma}")
        lines.append(")")
        lines.append("USING DELTA")
        if self.table_comment:
            lines.append(f"COMMENT '{self.table_comment}'")
        if self.partitions:
            quoted = ", ".join(f"`{partition}`" for partition in self.partitions)
            lines.append(f"CLUSTER BY ({quoted})")
        if self.table_properties:
            props = ", ".join(f"'{key}'='{value}'" for key, value in self.table_properties.items())
            lines.append(f"TBLPROPERTIES ({props});")
        else:
            lines[-1] = f"{lines[-1]};"
        return "\n".join(lines)

    @property
    def foreign_keys(self) -> list[DdlForeignKey]:
        constraints: list[DdlForeignKey] = []
        for rel in self.entity.relationships:
            remote_entity = self.model.modelEntities.get_by_id(rel.targetLocation)
            constraints.append(
                DdlForeignKey(
                    table=self.full_table_name,
                    columns=[a.sourceName for a in rel.attributes],
                    remote_columns=[a.targetName for a in rel.attributes],
                    remote_table="_".join(
                        [*remote_entity.locator.folders[1:], remote_entity.entity.name]
                    ),
                    remote_zone=DatabricksModel.zone_target_name(self.model.get_zone_for_entity(remote_entity)),
                )
            )
        return constraints

    @property
    def primary_key_attributes(self) -> list[Attribute]:
        return [attr for attr in self.entity.attributes if attr.isBusinessKey]


class DdlExternalPayload(DdlPayload):
    partitions = ["__Year", "__Month", "__Day", "__InsertTimestampUTC"]
    is_external = True

    def __init__(
        self, wrapper: EntityWrapper[ModelEntity], model: Model, source: ExternalModelSource
    ) -> None:
        super().__init__(wrapper, model)
        self.source = source
        self.external_source = ExternalSourcePayload(model, wrapper, source)
        self.zone_wrapper = DatabricksModel(model).external_zone
        self.base_columns = [
            DdlExternalColumn(
                Attribute(
                    ordinalNumber=1000,
                    name=col,
                    dataType=DataType(type=type_, nullable=False),
                    dateAdded=datetime.now(UTC),
                    attributeType="",
                ),
                self.model,
            )
            for col, type_ in [
                ("__Year", "short"),
                ("__Month", "short"),
                ("__Day", "short"),
                ("__InsertTimestampUTC", "datetime"),
            ]
        ]

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            DatabricksModel.zone_folder_name(self.zone_wrapper),
            "ddl",
            *self.wrapper.locator.folders[1:],
            f"{self.external_source.table_name}.py",
        )

    @property
    def full_table_name(self) -> str:
        return self.external_source.full_table_name

    @property
    def data_source(self) -> str:
        return self.source.dataSource or ""

    @property
    def data_source_display(self) -> str:
        data_source = self.model.dataSources.get(self.data_source).entity
        return data_source.displayName or self.data_source

    @property
    def source_name(self) -> str:
        return self.source.sourceAlias or self.full_table_name

    @property
    def table_tags(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for pv in self.wrapper.properties.values():
            if pv.property == "table_properties":
                discovered.setdefault("table_properties", []).append(pv.name)
            elif pv.property in {"business_area", "jobs"}:
                discovered[pv.property] = pv.name
        order = ["business_area", "jobs", "table_properties"]
        return {key: discovered[key] for key in order if key in discovered}

    @property
    def column_tags(self) -> list[dict[str, str]]:
        tags_by_column: dict[str, dict[str, str]] = {}
        source_alias = self.source.sourceAlias
        source_location = self.source.sourceLocation
        entity_json = {}
        candidate_files = [
            self.wrapper.source_file,
            Path(__file__).resolve().parents[3]
            / "Model"
            / Path(*self.locator.folders)
            / f"{self.locator.entityName or self.entity.name}.json",
        ]
        for candidate_file in candidate_files:
            try:
                entity_json = json.loads(candidate_file.read_text(encoding="utf-8"))
                break
            except OSError:
                continue
        for source in entity_json.get("sources", []):
            if source.get("sourceAlias") != source_alias and source.get("sourceLocation") != source_location:
                continue
            for mapping in source.get("mapping", []):
                properties = mapping.get("properties") or []
                if properties:
                    tags_by_column.setdefault(mapping["targetName"], {}).update(
                        {ref["property"]: ref["value"] for ref in properties}
                    )
        for mapping in self.source.mapping or []:
            props = {
                ref.property: ref.value
                for ref in getattr(mapping, "properties", None) or []
                if getattr(ref, "property", None)
            }
            if props:
                tags_by_column.setdefault(mapping.targetName, {}).update(props)
        return [
            {"column": mapping.targetName, "tags_repr": repr(tags_by_column[mapping.targetName])}
            for mapping in self.source.mapping or []
            if mapping.targetName in tags_by_column
        ]

    @property
    def columns(self) -> list[DdlExternalColumn]:
        assert self.source.mapping, "External source should have source mappings"
        column_types: dict[str, DataType] = {}
        for source_column in self.source.mapping:
            if source_column.sourceDataType is None:
                raise Exception(f"Could not get source type of {source_column} in {self.entity.name}")
            column_types[source_column.sourceName] = source_column.sourceDataType
            if source_column.sourceDataType.type in self.external_source.type_mappings:
                column_types[source_column.sourceName].type = self.external_source.type_mappings[
                    source_column.sourceDataType.type
                ]
        return self.base_columns + [
            DdlExternalColumn(
                Attribute(
                    ordinalNumber=1,
                    attributeType="",
                    name=source_column_mapping.targetName,
                    dataType=column_types[source_column_mapping.sourceName],
                    dateAdded=datetime.now(UTC),
                ),
                self.model,
            )
            for source_column_mapping in self.source.mapping
        ]


@dataclasses.dataclass
class DdlForeignKey:
    table: str
    columns: list[str]
    remote_columns: list[str]
    remote_table: str
    remote_zone: str


class JobPayloads:
    def __init__(self, model: Model) -> None:
        self.model = model
        self.databricks = DatabricksModel(model)

    @property
    def entities_by_zone_and_module(
        self,
    ) -> dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]]:
        groups: dict[tuple[str, str, str], list[EntityWrapper[ModelEntity]]] = defaultdict(list)
        for wrapper in self.databricks.model_entity_wrappers:
            zone = self.model.get_zone_for_entity(wrapper)
            product = wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default"
            module = wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default"
            groups[(DatabricksModel.zone_folder_name(zone), product, module)].append(wrapper)
        return groups

    @staticmethod
    def zone_slug(zone: EntityWrapper[Zone]) -> str:
        return DatabricksModel.zone_target_name(zone)

    @staticmethod
    def create_key(zone: EntityWrapper[Zone], *parts: str) -> str:
        suffix = "_".join(part for part in parts if part)
        zone_name = DatabricksModel.zone_target_name(zone)
        if suffix:
            return f"Create_{zone_name}_{suffix}"
        return f"Create_{zone_name}_tables"

    @staticmethod
    def create_name(zone: EntityWrapper[Zone], *parts: str) -> str:
        suffix = " ".join(part for part in parts if part)
        zone_name = DatabricksModel.zone_target_name(zone)
        if suffix:
            return f"Create {zone_name} {suffix}"
        return f"Create {zone_name}"

    @staticmethod
    def notebook_path(
        zone: EntityWrapper[Zone],
        kind: str,
        wrapper: EntityWrapper[ModelEntity],
        *,
        name: str | None = None,
    ) -> str:
        notebook_name = name or wrapper.locator.entityName or wrapper.entity.name
        return Path(
            DatabricksModel.zone_folder_name(zone),
            kind,
            *wrapper.locator.folders[1:],
            notebook_name,
        ).as_posix()

    @staticmethod
    def clusters(cluster_variable: str) -> list[dict[str, str]]:
        return [{"job_cluster_key": cluster_variable}] if cluster_variable else []


@register_payload("jobs/create_module.yml.jinja2")
def jobs_create_modules(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    jobs = JobPayloads(model)
    default_cluster = DatabricksModel(model).default_cluster_variable
    for (zone_folder, product, module), wrappers in jobs.entities_by_zone_and_module.items():
        zone = jobs.databricks.zone_for_folder(zone_folder)
        if zone is None:
            continue
        tasks = [
            {
                "task_key": create_task_key(
                    DatabricksModel.zone_target_name(zone),
                    product,
                    module,
                    wrapper.locator.entityName or wrapper.entity.name,
                ).lower(),
                "notebook_path": jobs.notebook_path(zone, "ddl", wrapper),
            }
            for wrapper in wrappers
        ]
        job_key = jobs.create_key(zone, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": jobs.create_name(zone, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": jobs.clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": tasks,
                },
                output_path=Path("jobs", jobs.zone_slug(zone), product, module, f"{job_key}.yml"),
            )
        )

    external_zone_wrapper = DatabricksModel(model).external_zone
    external_source_zone = DatabricksModel(model).model_backed_zones[0]
    external_groups: dict[
        tuple[str, str], list[tuple[EntityWrapper[ModelEntity], ExternalSourcePayload]]
    ] = defaultdict(list)
    for wrapper in model.modelEntities.get_many(f"{external_source_zone.entity.localFolderName}/"):
        for source in [
            ExternalSourcePayload(model, wrapper, item)
            for item in wrapper.entity.sources or []
            if getattr(item, "dataSource", None)
        ]:
            product = wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default"
            module = wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default"
            external_groups[(product, module)].append((wrapper, source))
    for (product, module), entries in external_groups.items():
        job_key = jobs.create_key(external_zone_wrapper, product, module)
        payloads.append(
            BasePayload(
                data={
                    "job_key": job_key,
                    "job_name": jobs.create_name(external_zone_wrapper, product, module),
                    "cluster_variable": default_cluster,
                    "job_clusters": jobs.clusters(default_cluster),
                    "default_job_cluster_key": default_cluster,
                    "tasks": [
                        {
                            "task_key": create_task_key(
                                DatabricksModel.zone_target_name(external_zone_wrapper),
                                product,
                                module,
                                source.table_name,
                            ).lower(),
                            "notebook_path": jobs.notebook_path(
                                external_zone_wrapper, "ddl", wrapper, name=source.table_name
                            ),
                        }
                        for wrapper, source in entries
                    ],
                },
                output_path=Path(
                    "jobs", jobs.zone_slug(external_zone_wrapper), product, module, f"{job_key}.yml"
                ),
            )
        )
    return payloads


@register_payload("jobs/create_zone.yml.jinja2")
def jobs_create_zones(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    jobs = JobPayloads(model)
    for zone in [DatabricksModel(model).external_zone, *DatabricksModel(model).model_backed_zones]:
        zone_folder = DatabricksModel.zone_folder_name(zone)
        module_jobs = [
            jobs.create_key(zone, product, module)
            for folder, product, module in jobs.entities_by_zone_and_module
            if folder == zone_folder
        ]
        if not zone.entity.localFolderName:
            external_source_zone = DatabricksModel(model).model_backed_zones[0]
            module_jobs = sorted(
                {
                    jobs.create_key(
                        zone,
                        wrapper.locator.folders[1] if len(wrapper.locator.folders) > 1 else "default",
                        wrapper.locator.folders[2] if len(wrapper.locator.folders) > 2 else "default",
                    )
                    for wrapper in model.modelEntities.get_many(
                        f"{external_source_zone.entity.localFolderName}/"
                    )
                    if any(getattr(source, "dataSource", None) for source in wrapper.entity.sources or [])
                }
            )
        payloads.append(
            BasePayload(
                data={
                    "job_key": jobs.create_key(zone),
                    "job_name": jobs.create_name(zone),
                    "tasks": [
                        {
                            "task_key": job_key,
                            "is_notebook_task": False,
                            "job_ref": job_key,
                            "depends_on": [],
                        }
                        for job_key in module_jobs
                    ],
                },
                output_path=Path(
                    "jobs",
                    jobs.zone_slug(zone),
                    f"Create_{DatabricksModel.zone_target_name(zone)}.yml",
                ),
            )
        )
    return payloads


@register_payload("jobs/create_all.yml.jinja2")
def jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    jobs = JobPayloads(model)
    zone_jobs = [
        jobs.create_key(zone)
        for zone in [DatabricksModel(model).external_zone, *DatabricksModel(model).model_backed_zones]
    ]
    return [
        BasePayload(
            data={
                "job_key": "Create_All_Tables",
                "job_name": "Create All Tables",
                "tasks": [
                    {
                        "task_key": job_key,
                        "is_notebook_task": False,
                        "job_ref": job_key,
                        "depends_on": [],
                        "resolved_cluster_ref": None,
                        "resolved_cluster_var": None,
                    }
                    for job_key in zone_jobs
                ],
            },
            output_path=Path("jobs", "create_all_tables.yml"),
        )
    ]


@register_payload("jobs/load_job_group.yml.jinja2")
def jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    jobs = JobPayloads(model)
    grouped: dict[str, list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in DatabricksModel(model).model_entity_wrappers:
        grouped[DatabricksModel.job_property(wrapper)].append(wrapper)

    payloads: list[IPayload] = []
    for job_name, wrappers in grouped.items():
        cluster_variable = DatabricksModel(model).cluster_for_job(job_name)
        external_zone_wrapper = DatabricksModel(model).external_zone
        external_tasks: list[dict[str, Any]] = []
        entity_tasks: list[dict[str, Any]] = []
        complete_dependencies: list[str] = []
        for wrapper in wrappers:
            previous_tasks: list[str] = ["Start_Load"]
            for source in [
                ExternalSourcePayload(model, wrapper, item)
                for item in wrapper.entity.sources or []
                if getattr(item, "dataSource", None)
            ]:
                task_key = create_task_key(
                    DatabricksModel.zone_target_name(external_zone_wrapper),
                    source.table_name,
                    source.table_name,
                ).lower()
                external_tasks.append(
                    {
                        "task_key": task_key,
                        "depends_on": previous_tasks,
                        "notebook_path": jobs.notebook_path(
                            external_zone_wrapper, "dml", wrapper, name=source.table_name
                        ),
                        "libraries": [],
                        "resolved_job_cluster_key": cluster_variable,
                    }
                )
                previous_tasks = [task_key]
            entity_task_key = create_task_key("load", *wrapper.locator.folders, wrapper.entity.name).lower()
            entity_tasks.append(
                {
                    "task_key": entity_task_key,
                    "depends_on": previous_tasks,
                    "notebook_path": jobs.notebook_path(
                        model.get_zone_for_entity(wrapper), "dml", wrapper
                    ),
                    "resolved_job_cluster_key": cluster_variable,
                }
            )
            complete_dependencies.append(entity_task_key)
        payloads.append(
            BasePayload(
                data={
                    "job_key": f"Load_{job_name}",
                    "job_name": f"Load {job_name}",
                    "job_clusters": jobs.clusters(cluster_variable),
                    "default_job_cluster_key": cluster_variable,
                    "schedule": DatabricksModel(model).schedule_for_job(job_name),
                    "external_tasks": external_tasks,
                    "entity_tasks": entity_tasks,
                    "complete_dependencies": complete_dependencies,
                },
                output_path=Path("jobs", f"load_{job_name}.yml"),
            )
        )
    return payloads


@register_payload("jobs/load_all.yml.jinja2")
def jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    job_names = sorted({DatabricksModel.job_property(wrapper) for wrapper in DatabricksModel(model).model_entity_wrappers})
    return [
        BasePayload(
            data={
                "job_key": "Load_All_Tables",
                "job_name": "Load All Tables",
                "schedule": None,
                "tasks": [
                    {
                        "task_key": f"Load_{job_name}",
                        "job_ref": f"Load_{job_name}",
                        "depends_on": [],
                    }
                    for job_name in job_names
                ],
            },
            output_path=Path("jobs", "load_all_tables.yml"),
        )
    ]
