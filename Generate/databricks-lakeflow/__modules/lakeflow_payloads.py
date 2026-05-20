from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from datam8.generate import BasePayload, IPayload
from datam8.model import EntityWrapper, Model
from datam8_model.model import ModelEntity
from payload_common import (
    ExternalSource,
    InternalSource,
    ModelEntityPayload,
    cluster_for_job,
    collect_transformations,
    create_resource_slug_from_name,
    default_cluster_variable,
    get_external_source_wrappers,
    get_external_zone,
    get_model_entity_by_id,
    get_model_entity_wrappers,
    get_property_refs,
    get_zone_for_folder,
    job_property,
    schedule_for_job,
    task_key,
    zone_folder_name,
    zone_target_name,
)


LAKEFLOW_PREFIX = "Lakeflow"


def lakeflow_key(*parts: str) -> str:
    return task_key(LAKEFLOW_PREFIX, *parts)


def lakeflow_resource_key(*parts: str) -> str:
    return create_resource_slug_from_name(lakeflow_key(*parts))


def wrapper_key(wrapper: EntityWrapper[ModelEntity]) -> tuple[tuple[str, ...], str]:
    return (tuple(wrapper.locator.folders), wrapper.locator.entityName or wrapper.entity.name)


def is_transformed(wrapper: EntityWrapper[ModelEntity]) -> bool:
    return bool(collect_transformations(wrapper))


def non_transformed_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    return [wrapper for wrapper in get_model_entity_wrappers(model) if not is_transformed(wrapper)]


def transformed_wrappers(model: Model) -> list[EntityWrapper[ModelEntity]]:
    return [wrapper for wrapper in get_model_entity_wrappers(model) if is_transformed(wrapper)]


def fallback_source_wrapper(
    model: Model,
    target_wrapper: EntityWrapper[ModelEntity],
) -> EntityWrapper[ModelEntity] | None:
    candidates = [
        candidate
        for candidate in get_model_entity_wrappers(model)
        if candidate is not target_wrapper
        and candidate.entity.name == target_wrapper.entity.name
        and not is_transformed(candidate)
    ]
    return candidates[0] if candidates else None


def _source_properties(source: Any) -> dict[str, str]:
    return {ref.property: ref.value for ref in getattr(source, "properties", None) or []}


def extract_mode(source: Any) -> str:
    return str(_source_properties(source).get("extract_mode") or "full").strip().lower()


def parse_source_table(source_location: str) -> tuple[str, str]:
    value = source_location.strip()
    if re.match(r"(?is)^\s*select\b", value):
        raise ValueError(f"SQL query sourceLocation cannot be parsed as a table: {source_location}")

    bracketed = re.fullmatch(r"\[([^\]]+)\]\.\[([^\]]+)\]", value)
    if bracketed:
        return bracketed.group(1), bracketed.group(2)

    dotted = re.fullmatch(r'"?([^".\[]+)"?\."?([^".\]]+)"?', value)
    if dotted:
        return dotted.group(1), dotted.group(2)

    raise ValueError(f"Unsupported source table reference: {source_location}")


def remove_database_qualifier(query: str) -> str:
    return re.sub(r"\[[^\]]+\]\.\[([^\]]+)\]\.\[([^\]]+)\]", r"[\1].[\2]", query)


def source_catalog(source: ExternalSource) -> str:
    return str(source.data_source_extended_properties.get("database") or source.data_source)


def cursor_column(source: Any) -> str | None:
    for mapping in getattr(source, "mapping", None) or []:
        props = _source_properties(mapping)
        if str(props.get("extract_mode") or "").lower() == "delta":
            return getattr(mapping, "sourceName", None)
    return None


def business_key_columns(wrapper: EntityWrapper[ModelEntity]) -> list[str]:
    return [attr.name for attr in wrapper.entity.attributes if attr.isBusinessKey]


def external_select_expressions(wrapper: EntityWrapper[ModelEntity], source: Any, model: Model) -> list[str]:
    mapping_by_target = {
        getattr(mapping, "targetName", None): getattr(mapping, "sourceName", None)
        for mapping in getattr(source, "mapping", None) or []
    }
    expressions: list[str] = []
    for attr in wrapper.entity.attributes:
        expression = getattr(attr, "calculation", None) or getattr(attr, "expression", None)
        if expression:
            expressions.append(f"{expression} AS `{attr.name}`")
            continue
        source_name = mapping_by_target.get(attr.name)
        if not source_name:
            continue
        attr_type = getattr(getattr(attr, "dataType", None), "type", None)
        target_type = "string"
        if attr_type:
            for data_type in model.dataTypes.values():
                if data_type.entity.name == attr_type:
                    target_type = data_type.entity.targets.get("databricks", attr_type)
                    break
        expressions.append(f"try_cast(`{source_name}` as {target_type}) AS `{attr.name}`")
    return expressions


def notebook_path(
    zone: Any,
    kind: str,
    wrapper: EntityWrapper[ModelEntity],
    *,
    name: str | None = None,
) -> str:
    notebook_name = name or wrapper.locator.entityName or wrapper.entity.name
    return Path(
        zone_folder_name(zone),
        kind,
        *wrapper.locator.folders[1:],
        notebook_name,
    ).as_posix()


def pipeline_notebook_path(*parts: str) -> Path:
    return Path("pipelines", "notebooks", *parts)


class LakeflowExternalPipelinePayload(BasePayload):
    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model, source: Any) -> None:
        self.wrapper = wrapper
        self.model = model
        self.source = source
        self.external_source = ExternalSource(model, wrapper, source)
        self.raw_zone = get_external_zone(model)
        self.mode = extract_mode(source)
        self.resource_key = lakeflow_resource_key("external", self.external_source.full_table_name)
        self.task_key = lakeflow_key("external", self.external_source.full_table_name).lower()

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path("pipelines", "external", f"{self.resource_key}.yml")

    @property
    def pipeline_name(self) -> str:
        return f"Lakeflow External {self.external_source.full_table_name}"

    @property
    def connection_name(self) -> str:
        return self.external_source.data_source.lower()

    @property
    def destination_schema(self) -> str:
        return f"${{var.lakeflow_schema_prefix}}{zone_target_name(self.raw_zone)}"

    @property
    def destination_table(self) -> str:
        return self.external_source.full_table_name

    @property
    def is_managed_connect(self) -> bool:
        return self.mode in {"delta", "cdc"}

    @property
    def is_custom_pipeline(self) -> bool:
        return not self.is_managed_connect

    @property
    def notebook_relative_path(self) -> str:
        return Path(
            "pipelines",
            "notebooks",
            "external",
            *self.wrapper.locator.folders[1:],
            self.external_source.table_name,
        ).as_posix()

    @property
    def source_catalog(self) -> str:
        return source_catalog(self.external_source)

    @property
    def source_schema(self) -> str:
        return parse_source_table(str(self.external_source.source_location))[0]

    @property
    def source_table(self) -> str:
        return parse_source_table(str(self.external_source.source_location))[1]

    @property
    def cursor_column(self) -> str:
        column = cursor_column(self.source)
        if self.mode == "delta" and not column:
            raise ValueError(
                f"Source {self.external_source.full_table_name} uses extract_mode=delta "
                "but no mapping column is marked with extract_mode=delta."
            )
        return column or ""

    @property
    def primary_key_columns(self) -> list[str]:
        mapped_by_target = {
            getattr(mapping, "targetName", None): getattr(mapping, "sourceName", None)
            for mapping in getattr(self.source, "mapping", None) or []
        }
        return [
            mapped_by_target.get(column, column)
            for column in business_key_columns(self.wrapper)
        ]

    @property
    def cdc_available(self) -> bool:
        props = _source_properties(self.source)
        return all(props.get(name) for name in ["gateway_id", "staging_catalog", "staging_schema"])

    @property
    def validation_error(self) -> str | None:
        if self.mode == "cdc" and not self.cdc_available:
            return (
                f"Source {self.external_source.full_table_name} uses extract_mode=cdc, "
                "but gateway_id, staging_catalog, and staging_schema properties are missing."
            )
        return None


class LakeflowExternalNotebookPayload(BasePayload):
    def __init__(self, pipeline: LakeflowExternalPipelinePayload) -> None:
        self.pipeline = pipeline
        self.wrapper = pipeline.wrapper
        self.model = pipeline.model
        self.source = pipeline.source
        self.external_source = pipeline.external_source
        self.mode = pipeline.mode

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(f"{self.pipeline.notebook_relative_path}.py")

    @property
    def connection_name(self) -> str:
        return self.pipeline.connection_name

    @property
    def destination_table(self) -> str:
        return self.pipeline.destination_table

    @property
    def source_location(self) -> str:
        return str(self.external_source.source_location)

    @property
    def read_option_name(self) -> str:
        return "query" if self.mode == "query" else "dbtable"

    @property
    def read_option_value(self) -> str:
        return self.source_location

    @property
    def source_query(self) -> str:
        if self.mode == "query":
            return remove_database_qualifier(self.source_location)
        schema, table = parse_source_table(self.source_location)
        return f"SELECT * FROM [{schema}].[{table}]"

    @property
    def remote_query_sql(self) -> str:
        escaped_query = self.source_query.replace("'", "''")
        escaped_database = source_catalog(self.external_source).replace("'", "''")
        return (
            f"SELECT * FROM remote_query('{self.connection_name}', "
            f"database => '{escaped_database}', query => '{escaped_query}')"
        )

    @property
    def select_expressions(self) -> list[str]:
        mappings = {mapping.sourceName: mapping.targetName for mapping in self.source.mapping or []}
        expressions = ["F.current_timestamp().alias('__InsertTimestampUTC')"]
        expressions.extend(
            [
                "F.year(F.current_timestamp()).cast('smallint').alias('__Year')",
                "F.month(F.current_timestamp()).cast('smallint').alias('__Month')",
                "F.dayofmonth(F.current_timestamp()).cast('smallint').alias('__Day')",
            ]
        )
        for source_name, target_name in mappings.items():
            expressions.append(f"F.col({source_name!r}).alias({target_name!r})")
        return expressions


class LakeflowEntityPipelinePayload(ModelEntityPayload):
    def __init__(self, wrapper: EntityWrapper[ModelEntity], model: Model) -> None:
        super().__init__(wrapper, model)
        self.resource_key = lakeflow_resource_key("entity", self.zone_name, self.full_table_name)
        self.task_key = lakeflow_key("entity", *wrapper.locator.folders, wrapper.entity.name).lower()
        self.external_sources = [
            ExternalSource(model, wrapper, source)
            for source in wrapper.entity.sources or []
            if getattr(source, "dataSource", None)
        ]
        self.internal_sources = [
            InternalSource(model, wrapper, source)
            for source in wrapper.entity.sources or []
            if not getattr(source, "dataSource", None)
        ]

    def get_output_path(self) -> Path:
        return Path(
            "pipelines",
            "entities",
            *self.wrapper.locator.folders,
            f"{self.wrapper.locator.entityName or self.entity.name}.yml",
        )

    @property
    def pipeline_name(self) -> str:
        return f"Lakeflow Entity {self.zone_name} {self.full_table_name}"

    @property
    def notebook_relative_path(self) -> str:
        return Path(
            "pipelines",
            "notebooks",
            "entities",
            *self.wrapper.locator.folders,
            self.wrapper.locator.entityName or self.entity.name,
        ).as_posix()

    @property
    def external_source_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for source in self.wrapper.entity.sources or []:
            if not getattr(source, "dataSource", None):
                continue
            source_view = ExternalSource(self.model, self.wrapper, source)
            entries.append(
                {
                    "source_zone": source_view.source_zone,
                    "source_full_table_name": source_view.source_full_table_name,
                    "source_name": source_view.source_name,
                    "select_expressions": external_select_expressions(
                        self.wrapper, source, self.model
                    ),
                }
            )
        return entries


class LakeflowEntityNotebookPayload(BasePayload):
    def __init__(self, pipeline: LakeflowEntityPipelinePayload) -> None:
        self.pipeline = pipeline

    def get_data(self) -> object:
        return self

    def get_output_path(self) -> Path:
        return Path(f"{self.pipeline.notebook_relative_path}.py")


def external_pipeline_payloads(model: Model) -> list[LakeflowExternalPipelinePayload]:
    payloads: list[LakeflowExternalPipelinePayload] = []
    for wrapper in get_external_source_wrappers(model):
        for source in wrapper.entity.sources or []:
            if getattr(source, "dataSource", None):
                payload = LakeflowExternalPipelinePayload(wrapper, model, source)
                if payload.validation_error:
                    raise ValueError(payload.validation_error)
                payloads.append(payload)
    return payloads


def entity_pipeline_payloads(model: Model) -> list[LakeflowEntityPipelinePayload]:
    return [LakeflowEntityPipelinePayload(wrapper, model) for wrapper in non_transformed_wrappers(model)]


def clusters(cluster_variable: str) -> list[dict[str, str]]:
    return [{"job_cluster_key": cluster_variable}] if cluster_variable else []


def create_create_all_payloads(model: Model) -> list[IPayload]:
    default_cluster = default_cluster_variable(model)
    tasks = []
    for wrapper in transformed_wrappers(model):
        zone = get_zone_for_folder(model, wrapper.locator.folders[0]) or model.get_zone_for_entity(wrapper)
        entity_name = wrapper.locator.entityName or wrapper.entity.name
        tasks.append(
            {
                "task_key": lakeflow_key("create", *wrapper.locator.folders, entity_name).lower(),
                "notebook_path": notebook_path(zone, "ddl", wrapper),
                "resolved_job_cluster_key": default_cluster,
            }
        )
    return [
        BasePayload(
            data={
                "job_key": "Lakeflow_Create_All_Tables",
                "job_name": "Lakeflow Create All Tables",
                "job_clusters": clusters(default_cluster),
                "default_job_cluster_key": default_cluster,
                "tasks": tasks,
            },
            output_path=Path("jobs", "lakeflow_create_all_tables.yml"),
        )
    ]


def _external_task_lookup(
    pipelines: list[LakeflowExternalPipelinePayload],
) -> dict[tuple[int | None, str], dict[str, str]]:
    lookup: dict[tuple[int | None, str], dict[str, str]] = {}
    for pipeline in pipelines:
        lookup[(getattr(pipeline.wrapper.entity, "id", None), pipeline.external_source.table_name)] = {
            "task_key": pipeline.task_key,
            "resource_key": pipeline.resource_key,
        }
    return lookup


def create_load_group_payloads(model: Model) -> list[IPayload]:
    grouped: dict[str, list[EntityWrapper[ModelEntity]]] = defaultdict(list)
    for wrapper in get_model_entity_wrappers(model):
        grouped[job_property(wrapper, model)].append(wrapper)

    external_pipelines = external_pipeline_payloads(model)
    external_lookup = _external_task_lookup(external_pipelines)
    entity_pipelines = {wrapper_key(pipeline.wrapper): pipeline for pipeline in entity_pipeline_payloads(model)}

    payloads: list[IPayload] = []
    for job_name, wrappers in grouped.items():
        cluster_variable = cluster_for_job(model, job_name)
        external_tasks: list[dict[str, Any]] = []
        entity_tasks: list[dict[str, Any]] = []
        complete_dependencies: list[str] = []
        def task_key_for_wrapper(source_wrapper: EntityWrapper[ModelEntity]) -> str:
            pipeline = entity_pipelines.get(wrapper_key(source_wrapper))
            if pipeline is not None:
                return pipeline.task_key
            return lakeflow_key(
                "delta", *source_wrapper.locator.folders, source_wrapper.entity.name
            ).lower()

        for wrapper in wrappers:
            external_dependencies: list[str] = []
            for source in wrapper.entity.sources or []:
                if not getattr(source, "dataSource", None):
                    continue
                source_view = ExternalSource(model, wrapper, source)
                external_task = external_lookup.get(
                    (getattr(wrapper.entity, "id", None), source_view.table_name)
                )
                if not external_task:
                    continue
                external_tasks.append(
                    {
                        "task_key": external_task["task_key"],
                        "resource_key": external_task["resource_key"],
                        "depends_on": ["Start_Load"],
                    }
                )
                external_dependencies.append(external_task["task_key"])

            internal_dependencies: list[str] = []
            for source in wrapper.entity.sources or []:
                source_location = getattr(source, "sourceLocation", None)
                if isinstance(source_location, str) and source_location.isdigit():
                    source_location = int(source_location)
                if not isinstance(source_location, int):
                    continue
                try:
                    source_wrapper = get_model_entity_by_id(model, source_location)
                except KeyError:
                    source_wrapper = fallback_source_wrapper(model, wrapper)
                    if source_wrapper is None:
                        continue
                if job_property(source_wrapper, model) != job_name:
                    continue
                dependency_task = task_key_for_wrapper(source_wrapper)
                if dependency_task != task_key_for_wrapper(wrapper):
                    internal_dependencies.append(dependency_task)

            pipeline = entity_pipelines.get(wrapper_key(wrapper))
            if pipeline is not None:
                task = {
                    "task_key": pipeline.task_key,
                    "resource_key": pipeline.resource_key,
                    "depends_on": list(
                        dict.fromkeys(["Start_Load", *external_dependencies, *internal_dependencies])
                    ),
                    "is_pipeline_task": True,
                    "notebook_path": None,
                    "resolved_job_cluster_key": None,
                }
            else:
                zone = get_zone_for_folder(model, wrapper.locator.folders[0]) or model.get_zone_for_entity(wrapper)
                task = {
                    "task_key": lakeflow_key("delta", *wrapper.locator.folders, wrapper.entity.name).lower(),
                    "resource_key": None,
                    "depends_on": list(dict.fromkeys(["Start_Load", *internal_dependencies])),
                    "is_pipeline_task": False,
                    "notebook_path": notebook_path(zone, "dml", wrapper),
                    "resolved_job_cluster_key": cluster_variable,
                }
            entity_tasks.append(task)
            complete_dependencies.append(task["task_key"])

        unique_external_tasks = list({task["task_key"]: task for task in external_tasks}.values())
        payloads.append(
            BasePayload(
                data={
                    "job_key": f"Lakeflow_Load_{job_name}",
                    "job_name": f"Lakeflow Load {job_name}",
                    "job_clusters": clusters(cluster_variable),
                    "default_job_cluster_key": cluster_variable,
                    "schedule": schedule_for_job(model, job_name),
                    "external_tasks": unique_external_tasks,
                    "entity_tasks": entity_tasks,
                    "complete_dependencies": complete_dependencies,
                },
                output_path=Path("jobs", f"lakeflow_load_{job_name}.yml"),
            )
        )
    return payloads


def create_load_all_payloads(model: Model) -> list[IPayload]:
    job_names = sorted({job_property(wrapper, model) for wrapper in get_model_entity_wrappers(model)})
    dependencies_by_job: dict[str, list[str]] = {job_name: [] for job_name in job_names}
    for wrapper in get_model_entity_wrappers(model):
        target_job = job_property(wrapper, model)
        for source in wrapper.entity.sources or []:
            source_location = getattr(source, "sourceLocation", None)
            if isinstance(source_location, str) and source_location.isdigit():
                source_location = int(source_location)
            if not isinstance(source_location, int):
                continue
            try:
                source_wrapper = get_model_entity_by_id(model, source_location)
            except KeyError:
                source_wrapper = fallback_source_wrapper(model, wrapper)
                if source_wrapper is None:
                    continue
            source_job = job_property(source_wrapper, model)
            if source_job != target_job:
                dependencies_by_job[target_job].append(f"Lakeflow_Load_{source_job}")
    return [
        BasePayload(
            data={
                "job_key": "Lakeflow_Load_All_Tables",
                "job_name": "Lakeflow Load All Tables",
                "schedule": None,
                "tasks": [
                    {
                        "task_key": f"Lakeflow_Load_{job_name}",
                        "job_ref": f"Lakeflow_Load_{job_name}",
                        "depends_on": list(dict.fromkeys(dependencies_by_job[job_name])),
                    }
                    for job_name in job_names
                ],
            },
            output_path=Path("jobs", "lakeflow_load_all_tables.yml"),
        )
    ]
