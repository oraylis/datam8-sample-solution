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

from collections.abc import Sequence
from pathlib import Path

from datam8.generate import BasePayload, IPayload, register_payload
from datam8.model import Model
from datam8.utils.cache import Cache
from ddl_payloads import DdlExternalPayload, DdlPayload
from dml_payloads import DmlExternalPayload, DmlFunctionPayload, DmlPayload
from jobs_payloads import (
    create_all_job_payloads,
    create_load_all_payloads,
    create_load_group_payloads,
    create_module_job_payloads,
    create_zone_job_payloads,
)
from payload_common import (
    collect_transformations,
    create_resource_slug_from_name,
    get_external_source_wrappers,
    get_many,
    get_model_entity_wrappers,
    zone_display_name,
    zone_target_name,
    zone_targets_databricks,
)


@register_payload("notebooks/ddl_notebook.jinja2")
def ddl_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    """Create DDL notebook payloads for all modeled Databricks entities.

    DataM8 calls this function and renders one table-creation notebook for each
    entity returned by `get_model_entity_wrappers`.
    """
    payloads: list[DdlPayload] = []

    for wrapper in get_model_entity_wrappers(model):
        payloads.append(DdlPayload(wrapper, model))

    return payloads


@register_payload("notebooks/ddl_notebook.jinja2")
def ddl_external_notebooks(model: Model, cache: Cache) -> Sequence[DdlPayload]:
    """Create DDL notebook payloads for external source tables.

    These payloads create the raw landing tables that external extraction
    notebooks write into.
    """
    payloads: list[DdlPayload] = []

    for wrapper in get_external_source_wrappers(model):
        for source in wrapper.entity.sources or []:
            if not getattr(source, "dataSource", None):
                continue
            payloads.append(DdlExternalPayload(wrapper, model, source))

    return payloads


@register_payload("schema.yml.jinja2")
def dab_schemas(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create the Databricks Asset Bundle schema resource payload.

    The generated YAML defines one Databricks schema for each zone that targets
    Databricks.
    """
    return [
        BasePayload(
            data=[
                {
                    "resource_key": f"schema_{create_resource_slug_from_name(zone_target_name(zone))}",
                    "name": zone_target_name(zone),
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
    """Create the Databricks Asset Bundle cluster resource payload.

    Cluster definitions come from `cluster` property values in the metadata
    model and become reusable job cluster variables.
    """
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
    """Create DML notebook payloads and cache transformation script metadata.

    DML notebooks load data into modeled tables. Transformation metadata is
    cached here so `dml_function_scripts` can reuse it without re-reading files.
    """
    payloads: list[IPayload] = []

    for wrapper in get_model_entity_wrappers(model):
        transformations = collect_transformations(wrapper)
        cache.set(f"dml_transformations::{wrapper.locator}", transformations)
        payloads.append(DmlPayload(wrapper, model, transformations))

    return payloads


@register_payload("notebooks/dml_external_notebook.jinja2", order=2)
def dml_external_notebooks(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create DML extraction notebook payloads for external sources.

    These notebooks read from source systems and write into external landing
    tables.
    """
    payloads: list[IPayload] = []

    for wrapper in get_external_source_wrappers(model):
        for source in wrapper.entity.sources or []:
            if not getattr(source, "dataSource", None):
                continue
            payloads.append(DmlExternalPayload(wrapper, model, source))

    return payloads


@register_payload("notebooks/dml_function.jinja2", order=2)
def dml_function_scripts(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create payloads for Python transformation function files.

    The rendered files are copied next to DML notebooks so Databricks can import
    the model-defined transformation functions.
    """
    payloads: list[IPayload] = []

    for wrapper in get_model_entity_wrappers(model):
        zone = model.get_zone_for_entity(wrapper)
        try:
            transformations = cache.get(f"dml_transformations::{wrapper.locator}")
        except KeyError:
            transformations = collect_transformations(wrapper)
        for transform in transformations:
            payloads.append(DmlFunctionPayload(wrapper, zone, model, transform))

    return payloads


@register_payload("jobs/create_module.yml.jinja2")
def jobs_create_modules(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create DDL module job payloads.

    Module jobs run the DDL notebooks for one zone, data product, and module.
    """
    return create_module_job_payloads(model)


@register_payload("jobs/create_zone.yml.jinja2")
def jobs_create_zones(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create DDL zone orchestration job payloads.

    Zone jobs call all module-level create jobs for one Databricks zone.
    """
    return create_zone_job_payloads(model)


@register_payload("jobs/create_all.yml.jinja2")
def jobs_create_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create the top-level DDL orchestration job payload.

    This is the root job that triggers all table creation jobs.
    """
    return create_all_job_payloads(model)


@register_payload("jobs/load_job_group.yml.jinja2")
def jobs_load_groups(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create load job payloads grouped by the `jobs` property.

    Each group becomes a Databricks job such as `Load_daily` or `Load_weekly`.
    """
    return create_load_group_payloads(model)


@register_payload("jobs/load_all.yml.jinja2")
def jobs_load_all(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Create the top-level load orchestration job payload.

    This is the root job that triggers all grouped load jobs.
    """
    return create_load_all_payloads(model)
