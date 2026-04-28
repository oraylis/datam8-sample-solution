from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from datam8.model import EntityWrapper, Model
from datam8_model.attribute import HistoryType
from datam8_model.model import ExternalModelSource, ModelEntity
from datam8_model.zone import Zone

from payload_common import (
    ModelEntityPayload,
    get_external_zone,
    get_one,
    task_key,
    zone_display_name,
    zone_folder_name,
    zone_target_name,
)


class ExternalSource:
    """Template-facing view of one external source definition."""

    def __init__(
        self,
        model: Model,
        wrapper: EntityWrapper[ModelEntity],
        source: ExternalModelSource,
    ) -> None:
        self.model = model
        self.wrapper = wrapper
        self.source = source
        self.source_zone = zone_target_name(get_external_zone(model))
        self.data_source_entry = get_one(model.dataSources, source.dataSource).entity

    @property
    def table_name(self) -> str:
        return self.source.sourceAlias or self.wrapper.entity.name

    @property
    def full_table_name(self) -> str:
        return "_".join([self.data_product, self.data_module, self.table_name])

    @property
    def key(self) -> str:
        return task_key(self.source_zone, self.full_table_name)

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
        data_source_type = get_one(self.model.dataSourceTypes, self.data_source_entry.type).entity
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
    """Small container for merge, SCD, and assignment details used by DML templates."""

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


class DmlPayload(ModelEntityPayload):
    """Render payload for the main DML notebook of a model entity."""

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
            zone_folder_name(self.zone_wrapper),
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
    def external_source_items(self) -> list[ExternalSource]:
        return [
            ExternalSource(self.model, self.wrapper, source)
            for source in self.wrapper.entity.sources or []
            if getattr(source, "dataSource", None)
        ]

    @property
    def external_sources(self) -> list[ExternalSource]:
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


class DmlExternalPayload(ModelEntityPayload):
    """Render payload for an external-source extraction notebook."""

    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        model: Model,
        source: ExternalModelSource,
    ) -> None:
        super().__init__(wrapper, model)
        self.source = source
        self.external_source = ExternalSource(model, wrapper, source)
        self.zone_wrapper = get_external_zone(model)
        self.current = ExternalSource(model, wrapper, source)
        self.data_source_entry = get_one(model.dataSources, self.current.data_source).entity

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
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
        return zone_target_name(self.zone_wrapper)

    @property
    def zone_display(self) -> str:
        return zone_display_name(self.zone_wrapper)

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
    """Render payload for a Python transformation function file."""

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
            zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.wrapper.locator.entityName}_functions",
            self.transform["script_name"],
        )

    @property
    def content(self) -> str:
        return self.transform["script_content"]


