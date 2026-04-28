from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datam8 import logging
from datam8.model import EntityWrapper, Model
from datam8_model.attribute import Attribute, HistoryType
from datam8_model.data_type import DataType, DataTypeDefinition
from datam8_model.folder import Folder
from datam8_model.model import ExternalModelSource, ModelEntity

from dml_payloads import ExternalSource
from payload_common import (
    TARGET,
    ModelEntityPayload,
    get_external_zone,
    get_model_entity_by_id,
    get_one,
    get_property_refs,
    zone_folder_name,
    zone_target_name,
)

logger = logging.getLogger(__name__)


class DdlColumn:
    """Template-facing column wrapper for modeled DDL columns."""

    def __init__(self, attr: Attribute, model: Model) -> None:
        self.attribute = attr
        self.model = model

    @property
    def type_definition(self) -> DataTypeDefinition:
        return get_one(self.model.dataTypes, self.attribute.dataType.type).entity

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
    """Simple rendered column for technical columns not present in the model."""

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
    """Column wrapper for external source mappings with source-provided data types."""

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
    """Render payload for a table DDL notebook."""

    imports: list[str] = ["StructType", "StructField", "DataType"]
    is_external = False

    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        super().__init__(wrapper, model)
        self.locator = wrapper.locator
        self.first_folder: EntityWrapper[Folder] = get_one(
            model.folders,
            "/".join(self.locator.folders[0:2])
        )

    def get_output_path(self) -> Path:
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
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
        for ref in get_property_refs(self.model, self.wrapper):
            match [ref.property, ref.value]:
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
        for ref in get_property_refs(self.model, self.wrapper):
            if ref.property == "table_properties":
                discovered.setdefault("table_properties", []).append(ref.value)
            elif ref.property in {"business_area", "jobs", "write_mode", "data_retention"}:
                discovered[ref.property] = ref.value
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
            remote_entity = get_model_entity_by_id(self.model, rel.targetLocation)
            constraints.append(
                DdlForeignKey(
                    table=self.full_table_name,
                    columns=[a.sourceName for a in rel.attributes],
                    remote_columns=[a.targetName for a in rel.attributes],
                    remote_table="_".join(
                        [*remote_entity.locator.folders[1:], remote_entity.entity.name]
                    ),
                    remote_zone=zone_target_name(self.model.get_zone_for_entity(remote_entity)),
                )
            )
        return constraints

    @property
    def primary_key_attributes(self) -> list[Attribute]:
        return [attr for attr in self.entity.attributes if attr.isBusinessKey]


class DdlExternalPayload(DdlPayload):
    """Render payload for a DDL notebook that creates an external extracted table."""

    partitions = ["__Year", "__Month", "__Day", "__InsertTimestampUTC"]
    is_external = True

    def __init__(
        self, wrapper: EntityWrapper[ModelEntity], model: Model, source: ExternalModelSource
    ) -> None:
        super().__init__(wrapper, model)
        self.source = source
        self.external_source = ExternalSource(model, wrapper, source)
        self.zone_wrapper = get_external_zone(model)
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
            zone_folder_name(self.zone_wrapper),
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
        data_source = get_one(self.model.dataSources, self.data_source).entity
        return data_source.displayName or self.data_source

    @property
    def source_name(self) -> str:
        return self.source.sourceAlias or self.full_table_name

    @property
    def table_tags(self) -> dict[str, Any]:
        discovered: dict[str, Any] = {}
        for ref in get_property_refs(self.model, self.wrapper):
            if ref.property == "table_properties":
                discovered.setdefault("table_properties", []).append(ref.value)
            elif ref.property in {"business_area", "jobs"}:
                discovered[ref.property] = ref.value
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
            {
                "column": mapping.targetName,
                "tags_repr": repr(tags_by_column[mapping.targetName]),
            }
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
    """Simple container for a Databricks foreign key constraint."""

    table: str
    columns: list[str]
    remote_columns: list[str]
    remote_table: str
    remote_zone: str


