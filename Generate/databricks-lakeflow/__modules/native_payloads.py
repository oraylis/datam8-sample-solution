"""Native pipeline, job and schema resources derived from one dataset DAG."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import yaml
from datam8.generate import BasePayload, register_payload

from dataset_plan import build_plan, slug


def plan(model, cache):
    try:
        return cache.get("native_dataset_plan")
    except KeyError:
        datasets = build_plan(model)
        cache.set("native_dataset_plan", datasets)
        return datasets


def pipeline_groups(datasets):
    datasets = [item for item in datasets if not (item.external and item.external.get("managed_ingestion"))]
    groups = defaultdict(list)
    lookup = {dataset.key: dataset for dataset in datasets}
    for dataset in datasets:
        groups[dataset.pipeline_key].append(dataset)
    if any(len({item.job for item in values}) != 1 for values in groups.values()):
        raise ValueError("Distinct model jobs resolve to the same technical pipeline key")
    slugs = [key.removeprefix("pipeline_") for key in groups]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Distinct model jobs resolve to the same technical pipeline key")
    dependencies = {key: set() for key in groups}
    for dataset in datasets:
        dependencies[dataset.pipeline_key].update(lookup[key].pipeline_key for key in dataset.dependencies if key in lookup and lookup[key].pipeline_key != dataset.pipeline_key)
    ordered, active, path = [], set(), []

    def visit(key):
        if key in active:
            start = path.index(key)
            raise ValueError("Pipeline grouping creates a cycle: " + " -> ".join([*path[start:], key]))
        if key in ordered:
            return
        active.add(key)
        path.append(key)
        for parent in sorted(dependencies[key]):
            visit(parent)
        path.pop()
        active.remove(key)
        ordered.append(key)

    for key in sorted(groups):
        visit(key)
    for key, values in groups.items():
        if len({value.job_display for value in values}) > 1:
            raise ValueError(f"Inconsistent display names for model job {key}")
    return [(key, groups[key], dependencies[key]) for key in ordered]


def yaml_payload(resources, path):
    return BasePayload(data={"content": yaml.safe_dump({"resources": resources}, sort_keys=False)}, output_path=Path(path))


def job_schedules(model):
    """Resolve each model job's schedule without inventing target defaults."""
    schedules = {
        wrapper.entity.name: getattr(wrapper.entity, "cron", None)
        for wrapper in model.propertyValues.values()
        if getattr(wrapper.entity, "property", None) == "schedules"
    }
    result = {}
    for wrapper in model.propertyValues.values():
        job = wrapper.entity
        if getattr(job, "property", None) != "jobs":
            continue
        for prop in getattr(job, "properties", []) or []:
            if getattr(prop, "property", None) == "schedules":
                cron = schedules.get(getattr(prop, "value", None))
                if cron:
                    parts = str(cron).split()
                    if len(parts) == 2:
                        minute, hour = parts
                        cron = f"0 {minute} {hour} * * ?"
                    result[job.name] = cron
    return result


def job_compute(model, job_name):
    """Resolve a Lakeflow pipeline's compute from its model job cluster property."""
    job = next(
        (
            wrapper.entity
            for wrapper in model.propertyValues.values()
            if getattr(wrapper.entity, "property", None) == "jobs"
            and getattr(wrapper.entity, "name", None) == job_name
        ),
        None,
    )
    if job is None:
        raise ValueError(f"No model job property value for {job_name!r}")
    cluster_name = next(
        (
            reference.value
            for reference in getattr(job, "properties", []) or []
            if reference.property == "cluster"
        ),
        None,
    )
    if not cluster_name:
        raise ValueError(f"Model job {job_name!r} must reference a cluster property")
    cluster = next(
        (
            wrapper.entity
            for wrapper in model.propertyValues.values()
            if getattr(wrapper.entity, "property", None) == "cluster"
            and getattr(wrapper.entity, "name", None) == cluster_name
        ),
        None,
    )
    if cluster is None:
        raise ValueError(f"Model job {job_name!r} references unknown cluster {cluster_name!r}")
    if getattr(cluster, "serverless", False):
        return {"serverless": True}
    node_type = getattr(cluster, "node_type", None)
    num_workers = getattr(cluster, "num_workers", None)
    if not node_type or num_workers is None:
        raise ValueError(f"Cluster property {cluster_name!r} requires node_type and num_workers")
    cluster_spec = {
        "label": "default",
        "node_type_id": node_type,
        "num_workers": num_workers,
    }
    driver_type = getattr(cluster, "driver_node_type", None)
    if driver_type:
        cluster_spec["driver_node_type_id"] = driver_type
    policy_id = getattr(cluster, "policy_id", None)
    if policy_id:
        cluster_spec["policy_id"] = policy_id
    return {"serverless": False, "clusters": [cluster_spec]}


def _pipeline_task_key(pipeline_key):
    return "refresh_" + pipeline_key.removeprefix("pipeline_")


def ingestion_groups(datasets):
    groups = defaultdict(list)
    for dataset in datasets:
        ingestion = (dataset.external or {}).get("managed_ingestion")
        if ingestion:
            groups["ingest_" + slug(dataset.job) + "_" + slug(dataset.external["connection_suffix"])].append((dataset, ingestion))
    for key, values in groups.items():
        if len({dataset.job for dataset, _ in values}) != 1 or len({dataset.external["connection_suffix"] for dataset, _ in values}) != 1:
            raise ValueError(f"{key}: ingestion pipeline must have one model job and one Unity Catalog connection")
    return groups


def ingestion_task_groups(datasets, groups):
    by_dataset = {}
    for key, items in groups.items():
        for dataset, _spec in items:
            by_dataset[dataset.key] = key
    result = defaultdict(set)
    for key, values, _dependencies in pipeline_groups(datasets):
        for dataset in values:
            result[key].update(by_dataset[parent] for parent in dataset.dependencies if parent in by_dataset)
    return result


def load_tasks(pipeline, datasets, *, full_refresh):
    tasks = []
    ingestion_dependencies = ingestion_task_groups(datasets, ingestion_groups(datasets))
    ingestion_keys = sorted(ingestion_dependencies.get(pipeline, set()))
    ingestion_tasks = []
    for key in ingestion_keys:
        task_key = "refresh_" + key
        ingestion_tasks.append(task_key)
        tasks.append({"task_key": task_key, "pipeline_task": {"pipeline_id": "${resources.pipelines." + key + ".id}", "full_refresh": full_refresh}})
    pipeline_task = {"task_key": _pipeline_task_key(pipeline), "pipeline_task": {"pipeline_id": "${resources.pipelines." + pipeline + ".id}", "full_refresh": full_refresh}}
    if ingestion_tasks:
        pipeline_task["depends_on"] = [{"task_key": task_key} for task_key in ingestion_tasks]
    tasks.append(pipeline_task)
    return tasks


@register_payload("native/pipeline.py.jinja2", order=1)
def native_notebooks(model, cache):
    return [BasePayload(data={"datasets": values}, output_path=Path("pipelines", key + ".py")) for key, values, _ in pipeline_groups(plan(model, cache))]


@register_payload("native/text.jinja2", order=2)
def native_resources(model, cache):
    datasets = plan(model, cache)
    groups = pipeline_groups(datasets)
    managed = ingestion_groups(datasets)
    resources = []
    for key, values, _ in groups:
        job_display = values[0].job_display
        definition = {
            "name": "[${var.environment}] Pipeline: " + job_display,
            "tags": {"platform": "databricks-lakeflow"},
            "permissions": [
                {"service_principal_name": "${var.deploy_service_principal}", "level": "IS_OWNER"},
                {"service_principal_name": "${var.run_as_service_principal}", "level": "CAN_RUN"},
            ],
            **job_compute(model, values[0].job),
            "edition": "ADVANCED",
            "channel": "CURRENT",
            "development": False,
            "continuous": False,
            "catalog": "${var.catalog_name}",
            "schema": "raw",
            "configuration": {"catalog_name": "${var.catalog_name}", "connection_prefix": "${var.connection_prefix}", "sample.date_start": "${var.date_start}", "sample.date_end": "${var.date_end}", "sample.runtime_path": "${workspace.root_path}/${var.lakeflow_output_path}/runtime"},
            "libraries": [{"file": {"path": "${workspace.root_path}/${var.lakeflow_output_path}/pipelines/" + key + ".py"}}],
            "environment": {"dependencies": ["databricks-sdk==0.75.0"]},
        }
        resources.append(yaml_payload({"pipelines": {key: definition}}, "pipelines/" + key + ".yml"))
    for key, items in managed.items():
        plugin = items[0][0].external["plugin"]
        job_display = items[0][0].job_display
        connection_display = {"sqlserver": "SQL Server", "oracle": "Oracle", "mysql": "MySQL", "postgresql": "PostgreSQL", "http_api": "Shipping API"}.get(plugin, plugin)
        connection_variable = "${var." + ("shipping_api" if plugin == "http_api" else plugin) + "_connection}"
        objects = []
        for dataset, spec in items:
            table_configuration = {
                "scd_type": "APPEND_ONLY" if dataset.write_mode == "append" else "SCD_TYPE_1",
                "include_columns": spec["include_columns"],
            }
            if dataset.write_mode != "append":
                table_configuration["primary_keys"] = spec["primary_keys"]
            if spec["extract_mode"] == "delta":
                table_configuration["query_based_connector_config"] = {"cursor_columns": [spec["cursor_column"]]}
            source = {
                "source_schema": spec["schema"],
                "source_table": spec["table"],
            }
            if plugin != "mysql":
                source["source_catalog"] = spec["source_catalog"]
            objects.append({"table": {
                **source,
                "table_configuration": table_configuration,
                "destination_catalog": "${var.catalog_name}",
                "destination_schema": "raw",
                "destination_table": dataset.name,
            }})
        definition = {
            "name": "[${var.environment}] Pipeline: Ingest " + job_display + " / " + connection_display,
            "tags": {"platform": "databricks-lakeflow"},
            "permissions": "${var.ingestion_permissions}",
            **job_compute(model, items[0][0].job),
            "edition": "ADVANCED",
            "channel": "CURRENT",
            "development": False,
            "continuous": False,
            "catalog": "${var.catalog_name}",
            "target": "raw",
            "ingestion_definition": {"connection_name": connection_variable, "objects": objects},
        }
        resources.append(yaml_payload({"pipelines": {key: definition}}, "pipelines/" + key + ".yml"))
    schemas = {"lakeflow_schema_" + zone: {"name": zone, "catalog_name": "${var.catalog_name}"} for zone in ("raw", "stage", "core", "curated")}
    resources.append(yaml_payload({"schemas": schemas}, "schemas/schema.yml"))

    jobs = {}
    schedules = job_schedules(model)
    for pipeline, values, dependencies in groups:
        key = "load_" + slug(values[0].job)
        job_display = values[0].job_display
        definition = {
            "name": "[${var.environment}] Load: " + job_display,
            "tags": {"platform": "databricks-lakeflow"},
            "permissions": [
                {"service_principal_name": "${var.deploy_service_principal}", "level": "IS_OWNER"},
                {"service_principal_name": "${var.run_as_service_principal}", "level": "CAN_MANAGE_RUN"},
            ],
            "max_concurrent_runs": 1,
            "timeout_seconds": 5400,
            "tasks": load_tasks(pipeline, datasets, full_refresh="${var.pipeline_full_refresh}"),
        }
        if schedules.get(values[0].job):
            definition["schedule"] = {
                "quartz_cron_expression": schedules[values[0].job],
                "timezone_id": "Europe/Amsterdam",
                "pause_status": "${var.unpause_schedules}",
            }
        jobs[key] = definition
    resources.append(yaml_payload({"jobs": jobs}, "jobs/lakeflow_jobs.yml"))
    for name in ("uc_sources.py", "dataset_frames.py"):
        source = Path(__file__).resolve().parents[2] / "shared" / name if name == "uc_sources.py" else Path(__file__).resolve().parent.parent / "runtime" / name
        content = source.read_text(encoding="utf-8")
        resources.append(BasePayload(data={"content": content}, output_path=Path("runtime", name)))
    load_job_by_pipeline = {pipeline: "load_" + slug(values[0].job) for pipeline, values, _ in groups}
    load_jobs = [
        {
            "job": load_job_by_pipeline[pipeline],
            "model_job": values[0].job,
            "depends_on": [load_job_by_pipeline[parent] for parent in sorted(dependencies)],
        }
        for pipeline, values, dependencies in groups
    ]
    manifest = {
        "target": "databricks-lakeflow",
        "lifecycle": ["load"],
        "execution_plan": {"load": load_jobs},
        "job_schedules": schedules,
        "datasets": [
            {
                "key": dataset.key,
                "name": dataset.name,
                "zone": dataset.zone,
                "kind": dataset.kind,
                "model_job": dataset.job,
                "write_mode": dataset.write_mode,
                "columns": dataset.columns,
                "keys": dataset.keys,
                "scd2": dataset.scd2,
                "surrogates": dataset.surrogates,
                "dependencies": sorted(dataset.dependencies),
                "relationships": dataset.relationships,
                "pipeline": "ingest_" + slug(dataset.job) + "_" + slug(dataset.external["connection_suffix"]) if dataset.external and dataset.external.get("managed_ingestion") else dataset.pipeline_key,
                "managed_ingestion": bool(dataset.external and dataset.external.get("managed_ingestion")),
                "helper": dataset.history_name,
                "external": dataset.external,
            }
            for dataset in datasets
        ],
    }
    resources.append(BasePayload(data={"content": json.dumps(manifest, indent=2) + "\n"}, output_path=Path("manifest.json")))
    return resources
