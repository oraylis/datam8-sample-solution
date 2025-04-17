from dm8gen.Factory import Model, StageEntityFactory, RawEntityFactory
from dm8gen.Generated.StageModelEntry import StageEntity, Type as StageType, StageFunction
from dm8gen.Generated.RawModelEntry import RawEntity
from dm8gen.Generated.DataTypes import DataType
from helper import Helper
from system_properties import SystemProperties
from dataclasses import dataclass
from typing import cast


class Payload:
    def __init__(self, model: Model):
        self.model = model

    @dataclass
    class StagePayload:
        table: StageEntity
        locator: str
        layer_name: str
        full_table_name: str
        layer_full_table_name: str
        file_path: str
        raw_table: RawEntity | None = None

    def get_payload_ddl_stage(self) -> list[StagePayload]:
        entity_list: list[tuple[StageEntity, StageType, str]] = [
            (entity.model_object.entity, entity.model_object.type, entity.locator)
            for entity in self.model.get_stage_entity_list()
            if entity.model_object.entity is not None
        ]

        payload: list[Payload.StagePayload] = []

        for _table, _type, _locator in entity_list:
            layer_name = _type.value
            full_table_name = _table.dataProduct + "_" + _table.dataModule + "_" + _table.name
            layer_full_table_name = layer_name + "." + full_table_name
            file_path = Helper.build_path(
                "notebooks", SystemProperties().stage_folder, "ddl", _table.dataProduct, _table.dataModule, _table.name
            )

            payload.append(
                Payload.StagePayload(_table, _locator, layer_name, full_table_name, layer_full_table_name, file_path)
            )

        return payload

    def get_payload_dml_stage(self) -> list[StagePayload]:
        entity_list: list[tuple[StageEntity, StageType, StageFunction, str]] = [
            (
                entity.model_object.entity,
                entity.model_object.type,
                cast(StageFunction, entity.model_object.function),
                entity.locator,
            )
            for entity in self.model.get_stage_entity_list()
            if entity.model_object.entity is not None
        ]

        payload: list[Payload.StagePayload] = []

        for _table, _type, _function, _locator in entity_list:
            layer_name = _type.value
            full_table_name = _table.dataProduct + "_" + _table.dataModule + "_" + _table.name
            layer_full_table_name = layer_name + "." + full_table_name
            file_path = Helper.build_path(
                "notebooks", SystemProperties().stage_folder, "dml", _table.dataProduct, _table.dataModule, _table.name
            )
            raw_table = cast(
                RawEntity, self.model.lookup_entity(cast(str, _function.sourceLocation)).model_object.entity
            )

            payload.append(
                Payload.StagePayload(
                    table=_table,
                    locator=_locator,
                    layer_name=layer_name,
                    full_table_name=full_table_name,
                    layer_full_table_name=layer_full_table_name,
                    file_path=file_path,
                    raw_table=raw_table,
                )
            )

        return payload

    @dataclass
    class StageColumnDDL:
        name: str
        name_escaped: str
        type: str
        nullable: bool
        nullability: str
        parquet_type: str

    def get_ddl_stage_column(self, locator: str) -> list[StageColumnDDL]:
        entity = cast(StageEntityFactory, self.model.lookup_entity(locator))
        assert entity is not None

        payload: list[Payload.StageColumnDDL] = []

        for column in entity.model_object.entity.attribute:
            data_type = cast(DataType, self.model.data_types.get_data_type(column.type))
            _parquet_type = data_type.parquetType
            nullabiltiy = "" if column.nullable else " NOT NULL"

            type_details = ""
            precision = ""
            scale = ""

            if data_type.hasPrecision:
                precision = "38" if column.precision is None else column.precision

                if data_type.hasScale:
                    scale = "18" if column.scale is None else column.scale

                type_details = "(%s%s)" % (precision, scale)

            _type = _parquet_type + type_details

            payload.append(
                Payload.StageColumnDDL(
                    name=column.name,
                    name_escaped="`%s`" % column.name,
                    type=_type,
                    nullable=cast(bool, column.nullable),
                    nullability=nullabiltiy,
                    parquet_type=_parquet_type,
                )
            )

        return payload

    @dataclass
    class StageColumnDML(StageColumnDDL):
        source_name: str

    def get_dml_stage_column(self, locator: str) -> list[StageColumnDML]:
        entity = cast(StageEntityFactory, self.model.lookup_entity(locator))
        payload_ddl = self.get_ddl_stage_column(locator)
        payload: list[Payload.StageColumnDML] = []

        attribute_mapping = Helper.attribute_mapping_to_dict(entity.model_object.function.attributeMapping)

        for column in payload_ddl:
            source_name = attribute_mapping[column.name] if column.name in attribute_mapping else column.name

            payload.append(
                Payload.StageColumnDML(
                    name=column.name,
                    name_escaped=column.name_escaped,
                    type=column.type,
                    nullable=column.nullable,
                    nullability=column.nullability,
                    parquet_type=column.parquet_type,
                    source_name=source_name,
                )
            )

        return payload


def get_dict_modules() -> dict:
    return {
        "Payload": Payload,
    }
