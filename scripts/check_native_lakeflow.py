"""Structural contracts for generated native Lakeflow pipelines."""
from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path

from databricks_jobs import execution_plan, generated_resources


def check_output(output: Path):
    manifest = json.loads((output / "manifest.json").read_text())
    datasets = manifest["datasets"]
    known = {item["key"]: item for item in datasets}
    expected = {"raw": 22, "stage": 21, "core": 15, "curated": 11}
    if Counter(item["zone"] for item in datasets) != expected:
        raise AssertionError("Public dataset inventory differs from the reviewed sample")
    keys = {item["key"] for item in datasets}
    if len(keys) != len(datasets):
        raise AssertionError("Duplicate dataset ownership")
    for item in datasets:
        if item["kind"] not in {"materialized_view", "streaming_table"}:
            raise AssertionError("Non-declarative public dataset: " + item["key"])
        if set(item["dependencies"]) - keys:
            raise AssertionError("Unresolved dataset dependency: " + item["key"])
        for relationship in item.get("relationships", []):
            if relationship["dataset"] not in keys or not relationship.get("attributes"):
                raise AssertionError("Manifest contains an unresolved or empty modeled relationship: " + item["key"])
        if item["write_mode"] == "merge" and item["kind"] == "materialized_view" and not item.get("helper"):
            raise AssertionError("Every materialized-view merge must use a private AUTO CDC history: " + item["key"])
    if not any(item.get("relationships") for item in datasets):
        raise AssertionError("Manifest does not expose modeled relationships for foreign-key validation")
    pipelines = list((output / "pipelines").glob("*.py"))
    if not pipelines:
        raise AssertionError("No native pipeline files")
    for path in pipelines:
        source = path.read_text(encoding="utf-8")
        if "# COMMAND ----------" in source or "# Databricks notebook source" in source:
            raise AssertionError("Notebook cell markers cannot be embedded in pipeline source: " + path.name)
        if 'sys.path.insert(0, spark.conf.get("sample.runtime_path"))' not in source or "Path(__file__)" in source:
            raise AssertionError("Pipeline must import runtime helpers using its configured workspace path: " + path.name)
        tree = ast.parse(source)
        if any(item["write_mode"] == "merge" and item["kind"] == "materialized_view" and item["pipeline"] == path.stem for item in datasets):
            if "create_auto_cdc_from_snapshot_flow" not in source:
                raise AssertionError("Materialized-view merge must generate snapshot AUTO CDC: " + path.name)
            if "validate_unique_keys(frame," not in source:
                raise AssertionError("Snapshot merge must validate non-null, unique business keys before AUTO CDC: " + path.name)
        if path.stem == "pipeline_sales_daily":
            if 'spark.readStream.table(catalog_name + "." + "raw.postgresqlwarehouse_aw_warehouse_stockmovement")' not in source:
                raise AssertionError("StockMovement Stage must use a streaming read from its append-only raw source")
            if 'spark.read.table(catalog_name + "." + "stage.postgresqlwarehouse_aw_warehouse_stockmovement")' not in source:
                raise AssertionError("StockMovement Core must read the complete Stage snapshot")
            if '@dp.table(name="stage.postgresqlwarehouse_aw_warehouse_stockmovement")' not in source or '@dp.materialized_view(name="core.inventory_stock_stockmovement")' not in source:
                raise AssertionError("StockMovement must publish an append Stage and an overwrite Core MV")
        if path.stem == "pipeline_sales_weekly":
            function_position = source.find("business_function = spark.sql(")
            lookup_position = source.find("business_function = apply_dimension_lookups(")
            if function_position < 0 or lookup_position < function_position:
                raise AssertionError("FactSalesOrder must execute its model function before the step-ordered dimension lookup")
            if "apply_lookups=False" not in source[source.find("def publish_curated_sales_orders_factsalesorder"):] :
                raise AssertionError("FactSalesOrder lookup is applied twice instead of at its modeled transformation step")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"saveAsTable", "merge", "write", "execute", "collect", "toPandas"}:
                raise AssertionError("Imperative action in pipeline: " + path.name)
            if not (isinstance(node, ast.FunctionDef) and node.decorator_list):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute) or decorator.func.attr not in {"materialized_view", "table"}:
                    continue
                name = next((keyword.value.value for keyword in decorator.keywords if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)), None)
                if not name or "." not in name:
                    raise AssertionError("Dataset publication must name its model schema explicitly: " + path.name)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_streaming_table"):
                continue
            name = next((keyword.value.value for keyword in node.keywords if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)), None)
            if name and name.startswith("__history_"):
                private = next((keyword.value.value for keyword in node.keywords if keyword.arg == "private" and isinstance(keyword.value, ast.Constant)), False)
                if private is not True:
                    raise AssertionError("AUTO CDC history helpers must remain private to their pipeline: " + path.name)
    expected_pipelines = {item["pipeline"] for item in datasets}
    resources = generated_resources(output.parent)
    stock = next(item for item in datasets if item["key"] == "raw.postgresqlwarehouse_aw_warehouse_stockmovement")
    if stock["keys"] or stock["write_mode"] != "append":
        raise AssertionError("StockMovement ingestion must support append without a business key")
    postgres = resources["pipelines"][stock["pipeline"]]["ingestion_definition"]["objects"]
    config = next(item["table"]["table_configuration"] for item in postgres if item["table"]["destination_table"] == stock["name"])
    if config.get("scd_type") != "APPEND_ONLY" or "primary_keys" in config:
        raise AssertionError("StockMovement must use native APPEND_ONLY ingestion without primary keys")
    expected_python_pipelines = {item["pipeline"] for item in datasets if not item.get("managed_ingestion")}
    if {path.stem for path in pipelines} != expected_python_pipelines:
        raise AssertionError("Model pipeline files must use stable model-job keys")
    resources = generated_resources(output.parent)
    mysql = resources.get("pipelines", {}).get("ingest_sales_daily_mysql", {}).get("ingestion_definition", {})
    mysql_tables = [item.get("table", {}) for item in mysql.get("objects", [])]
    if not mysql_tables or any("source_catalog" in item for item in mysql_tables):
        raise AssertionError("MySQL uses a two-level source namespace; omit source_catalog")
    if any(item.get("source_schema") != "aw_webshop" for item in mysql_tables):
        raise AssertionError("MySQL source database must be represented by source_schema")
    customer = next((item for item in datasets if item["key"] == "stage.adventureworks_saleslt_customer"), None)
    if not customer or customer["write_mode"] != "merge" or customer["scd2"] != ["Nachname"]:
        raise AssertionError("Combined Stage Customer must retain its SCD2 merge model")
    customer_pipeline = output / "pipelines/pipeline_sales_daily.py"
    customer_source = customer_pipeline.read_text(encoding="utf-8")
    for expected in (
        'spark.read.table(catalog_name + "." + "raw.adventureworks_saleslt_customer_de")',
        'spark.read.table(catalog_name + "." + "raw.adventureworks_saleslt_customer_en")',
        'F.col("CustomerID").alias("KundenID")',
        'F.col("SourceSystem").alias("SourceSystem")',
        'validate_unique_keys(frame, ["KundenID", "SourceSystem"]',
    ):
        if expected not in customer_source:
            raise AssertionError("Combined Customer must preserve both source keys and reject duplicate key pairs before CDC: " + expected)
    if customer_source.count('F.col("SourceSystem").alias("SourceSystem")') != 2:
        raise AssertionError("Both Customer snapshots must map their SourceSystem column")
    sqlserver = resources.get("pipelines", {}).get("ingest_sales_daily_sqlserver", {}).get("ingestion_definition", {})
    sqlserver_objects = {item.get("table", {}).get("destination_table"): item.get("table", {}) for item in sqlserver.get("objects", [])}
    if not {"adventureworks_saleslt_customer_de", "adventureworks_saleslt_customer_en"} <= sqlserver_objects.keys():
        raise AssertionError("Both Customer source snapshots must be available before the modeled CDC pipeline")
    if "query_based_connector_config" in sqlserver_objects["adventureworks_saleslt_customer_de"].get("table_configuration", {}):
        raise AssertionError("Customer_DE must use full managed ingestion so the uniqueness guard reads a fresh source snapshot")
    if sqlserver_objects["adventureworks_saleslt_customer_en"].get("table_configuration", {}).get("query_based_connector_config", {}).get("cursor_columns") != ["ModifiedDate"]:
        raise AssertionError("Customer_EN must preserve its modeled delta cursor")
    for customer_table in ("adventureworks_saleslt_customer_de", "adventureworks_saleslt_customer_en"):
        table_config = sqlserver_objects[customer_table].get("table_configuration", {})
        if "SourceSystem" not in table_config.get("include_columns", []) or "SourceSystem" not in table_config.get("primary_keys", []):
            raise AssertionError(f"{customer_table} ingestion must include SourceSystem in its selected columns and keys")
    pipeline_names = []
    for definition in resources["pipelines"].values():
        if definition.get("serverless") is not False:
            raise AssertionError("Lakeflow pipeline must use the model-selected classic compute")
        clusters = definition.get("clusters", [])
        if len(clusters) != 1 or clusters[0].get("label") != "default" or not clusters[0].get("node_type_id") or not clusters[0].get("num_workers"):
            raise AssertionError("Lakeflow pipeline must receive its model job's cluster configuration")
        if definition.get("tags", {}).get("platform") != "databricks-lakeflow" or set(definition.get("tags", {})) != {"platform"}:
            raise AssertionError("Lakeflow pipeline must have only the platform target tag")
        if not definition.get("name", "").startswith("[${var.environment}] ") or "databricks-lakeflow" in definition["name"]:
            raise AssertionError("Lakeflow pipeline name does not follow the environment-first naming convention")
        if definition.get("configuration", {}).get("sample.runtime_path") != "${workspace.root_path}/${var.lakeflow_output_path}/runtime":
            if not definition.get("ingestion_definition"):
                raise AssertionError("Lakeflow pipeline does not expose the synchronized runtime helper path")
        if definition.get("ingestion_definition"):
            if any(field in definition for field in ("libraries", "schema")):
                raise AssertionError("Managed ingestion must not include Python pipeline settings")
            if definition.get("catalog") != "${var.catalog_name}" or definition.get("target") != "raw":
                raise AssertionError("Managed ingestion must declare its direct-publishing catalog and target")
        pipeline_names.append(definition["name"])
    if len(pipeline_names) != len(set(pipeline_names)):
        raise AssertionError("Lakeflow display names are not unique")
    if any(not name.startswith("[${var.environment}] Pipeline: ") for name in pipeline_names):
        raise AssertionError("Lakeflow pipeline names must be distinct from orchestration job names")
    jobs = resources["jobs"]
    if "Lakeflow_Create_All_Tables" in jobs:
        raise AssertionError("Lakeflow must create datasets during its first pipeline refresh, without a separate Create job")
    if "load_all_tables" in jobs:
        raise AssertionError("Lakeflow must expose only its modeled daily/weekly load jobs")
    job_names = []
    for name, definition in jobs.items():
        tags = definition.get("tags", {})
        if tags.get("platform") != "databricks-lakeflow" or set(tags) != {"platform"}:
            raise AssertionError("Lakeflow job must have only the platform target tag: " + name)
        if not definition.get("name", "").startswith("[${var.environment}] ") or "databricks-lakeflow" in definition["name"]:
            raise AssertionError("Lakeflow job name does not follow the environment-first naming convention: " + name)
        job_names.append(definition["name"])
        for task in definition.get("tasks", []):
            if "pipeline_task" not in task:
                raise AssertionError("Lakeflow jobs must invoke pipeline tasks directly: " + name)
    if len(job_names) != len(set(job_names)):
        raise AssertionError("Lakeflow job display names are not unique")
    if any(not name.startswith("[${var.environment}] Load: ") for name in job_names):
        raise AssertionError("Lakeflow job names must retain the model job display name")
    if set(job_names) & set(pipeline_names):
        raise AssertionError("Lakeflow job and pipeline display names must be distinct")
    if any(" - " in name for name in pipeline_names):
        raise AssertionError("Pipelines must not be split into fixed per-layer resources")
    scheduled = {name for name, definition in jobs.items() if definition.get("schedule")}
    if not scheduled:
        raise AssertionError("Model job schedules were not carried into Lakeflow orchestration")
    for key in scheduled:
        if len(jobs[key]["tasks"]) < 1:
            raise AssertionError("Scheduled Lakeflow job has no pipeline tasks: " + key)
    pipeline_dependencies = {key: set() for key in expected_pipelines}
    for item in datasets:
        for parent in item["dependencies"]:
            upstream = known[parent]["pipeline"]
            if upstream != item["pipeline"] and upstream.startswith("pipeline_") and item["pipeline"].startswith("pipeline_"):
                pipeline_dependencies[item["pipeline"]].add(upstream)
    if set(resources["pipelines"]) != expected_pipelines:
        raise AssertionError("Bundle pipeline resources differ from the model and managed source inventory")

    job_by_pipeline = {
        "pipeline_" + item["model_job"].lower().replace("-", "_"): item["job"]
        for item in manifest["execution_plan"]["load"]
    }
    for job, cron in manifest.get("job_schedules", {}).items():
        key = "load_" + job.lower().replace("-", "_")
        if key not in jobs or jobs[key].get("schedule", {}).get("quartz_cron_expression") != cron:
            raise AssertionError("Model schedule was not preserved for " + job)
        task_pipelines = {
            task["pipeline_task"]["pipeline_id"].split(".")[2]
            for task in jobs[key]["tasks"]
        }
        expected_task_pipelines = {"pipeline_" + job.lower().replace("-", "_")}
        expected_task_pipelines.update(
            item["pipeline"] for item in datasets
            if item.get("model_job") == job and item.get("managed_ingestion")
        )
        if task_pipelines != expected_task_pipelines:
            raise AssertionError("Scheduled job refreshes pipelines outside its model job: " + job)
        processing_task = next(task for task in jobs[key]["tasks"] if task["pipeline_task"]["pipeline_id"].endswith("pipeline_" + job.lower().replace("-", "_") + ".id}"))
        expected_ingestion_tasks = {
            "refresh_" + item["pipeline"]
            for item in datasets
            if item.get("model_job") == job and item.get("managed_ingestion")
        }
        actual_ingestion_tasks = {item["task_key"] for item in processing_task.get("depends_on", [])}
        if actual_ingestion_tasks != expected_ingestion_tasks:
            raise AssertionError("Processing pipeline must wait for its own managed ingestion tasks: " + job)
        entry = next(item for item in manifest["execution_plan"]["load"] if item["model_job"] == job)
        expected_dependencies = {job_by_pipeline[value] for value in pipeline_dependencies["pipeline_" + job.lower().replace("-", "_")]}
        if set(entry["depends_on"]) != expected_dependencies:
            raise AssertionError("Execution manifest lost the modeled cross-job dependencies: " + job)
    execution_plan(resources, manifest, required_phases=manifest["lifecycle"])
    print(f"PASS native Lakeflow: {len(datasets)} public datasets, {len(pipelines)} pipelines")
