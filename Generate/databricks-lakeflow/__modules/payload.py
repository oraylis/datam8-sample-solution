from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import Model
from datam8.utils.cache import Cache
from ddl_payloads import DdlPayload
from dml_payloads import DmlFunctionPayload, DmlPayload
from lakeflow_payloads import (
    LakeflowEntityNotebookPayload,
    LakeflowExternalNotebookPayload,
    create_create_all_payloads,
    create_load_all_payloads,
    create_load_group_payloads,
    entity_pipeline_payloads,
    external_pipeline_payloads,
    transformed_wrappers,
)
from payload_common import (
    collect_transformations,
    create_resource_slug_from_name,
    get_many,
    zone_display_name,
    zone_target_name,
    zone_targets_databricks,
)


@register_payload("notebooks/ddl_notebook.jinja2")
def ddl_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    payloads: list[DdlPayload] = []
    for wrapper in transformed_wrappers(model):
        payloads.append(DdlPayload(wrapper, model))
    return payloads


@register_payload("schema.yml.jinja2")
def dab_schemas(model: Model, cache: Cache) -> Sequence[IPayload]:
    return [
        BasePayload(
            data=[
                {
                    "resource_key": (
                        f"lakeflow_schema_{create_resource_slug_from_name(zone_target_name(zone))}"
                    ),
                    "name": f"${{var.lakeflow_schema_prefix}}{zone_target_name(zone)}",
                    "comment": zone_display_name(zone),
                }
                for zone in model.zones.values()
                if zone_targets_databricks(zone)
            ],
            output_path=Path("schemas", "schema.yml"),
        )
    ]


@register_payload("clusters.yml.jinja2")
def dab_cluster(model: Model, cache: Cache) -> Sequence[IPayload]:
    clusters = [wrapper.entity for wrapper in get_many(model.propertyValues, "cluster/")]
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


@register_payload("notebooks/dml_notebook.jinja2", order=2)
def dml_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for wrapper in transformed_wrappers(model):
        transformations = collect_transformations(wrapper)
        cache.set(f"dml_transformations::{wrapper.locator}", transformations)
        payloads.append(DmlPayload(wrapper, model, transformations))
    return payloads


@register_payload("notebooks/dml_function.jinja2", order=2)
def dml_function_scripts(model: Model, cache: Cache) -> Sequence[IPayload]:
    payloads: list[IPayload] = []
    for wrapper in transformed_wrappers(model):
        zone = model.get_zone_for_entity(wrapper)
        try:
            transformations = cache.get(f"dml_transformations::{wrapper.locator}")
        except KeyError:
            transformations = collect_transformations(wrapper)
        for transform in transformations:
            payloads.append(DmlFunctionPayload(wrapper, zone, model, transform))
    return payloads


@register_payload("pipelines/external_pipeline.yml.jinja2", order=3)
def lakeflow_external_pipelines(model: Model, cache: Cache) -> Sequence[IPayload]:
    pipelines = external_pipeline_payloads(model)
    cache.set("lakeflow_external_pipelines", pipelines)
    return pipelines


@register_payload("pipelines/external_notebook.py.jinja2", order=4)
def lakeflow_external_pipeline_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    try:
        pipelines = cache.get("lakeflow_external_pipelines")
    except KeyError:
        pipelines = external_pipeline_payloads(model)
    return [LakeflowExternalNotebookPayload(pipeline) for pipeline in pipelines if pipeline.is_custom_pipeline]


@register_payload("pipelines/entity_pipeline.yml.jinja2", order=3)
def lakeflow_entity_pipelines(model: Model, cache: Cache) -> Sequence[IPayload]:
    pipelines = entity_pipeline_payloads(model)
    cache.set("lakeflow_entity_pipelines", pipelines)
    return pipelines


@register_payload("pipelines/entity_notebook.py.jinja2", order=4)
def lakeflow_entity_pipeline_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    try:
        pipelines = cache.get("lakeflow_entity_pipelines")
    except KeyError:
        pipelines = entity_pipeline_payloads(model)
    return [LakeflowEntityNotebookPayload(pipeline) for pipeline in pipelines]


@register_payload("jobs/lakeflow_create_all.yml.jinja2")
def jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    return create_create_all_payloads(model)


@register_payload("jobs/lakeflow_load_job_group.yml.jinja2")
def jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    return create_load_group_payloads(model)


@register_payload("jobs/lakeflow_load_all.yml.jinja2")
def jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    return create_load_all_payloads(model)
