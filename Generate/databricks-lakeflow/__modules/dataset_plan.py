"""Explicit, validated plans for native Lakeflow datasets.

This module shapes metadata only. Rendering and runtime Spark operations are
separate; no target selection depends on transformation complexity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from payload_common import display_names, get_property_refs, target_data_type


def slug(value):
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def enum_value(value):
    return getattr(value, "value", value)


def properties(model, wrapper):
    values = {}
    for reference in get_property_refs(model, wrapper):
        values.setdefault(reference.property, reference.value)
    return values


def full_name(wrapper):
    return "_".join([*wrapper.locator.folders[1:], wrapper.entity.name]).lower()


def source_alias(source):
    if source.sourceAlias:
        return source.sourceAlias
    value = source.sourceLocation.strip().rstrip(']"`')
    if re.match(r"(?i)^select\s", value):
        raise ValueError("SQL query sources require an explicit sourceAlias")
    return re.split(r"[./]", value)[-1].strip('["`')


def is_surrogate(attribute):
    return any(reference.property == "attribute_type" and reference.value == "SK" for reference in attribute.properties or [])


def source_property(source, name, default=None):
    return next((enum_value(reference.value) for reference in source.properties or [] if reference.property == name), default)


def source_extract_column(source):
    matches = [
        mapping.sourceName
        for mapping in source.mapping or []
        if any(
            reference.property == "extract_column"
            and enum_value(reference.value) == "delta"
            for reference in mapping.properties or []
        )
    ]
    if len(matches) > 1:
        raise ValueError("delta extraction requires exactly one marked cursor column per source")
    return matches[0] if matches else None


def source_table(location, plugin):
    if re.match(r"(?is)^\s*select\b", location):
        return None
    identifier = r'(?:\[[^\]]+\]|"[^"]+"|`[^`]+`|[A-Za-z_][A-Za-z0-9_$]*)'
    match = re.fullmatch(r"\s*(" + identifier + r")\s*\.\s*(" + identifier + r")\s*", location)
    if not match:
        return None
    def unquote(value):
        if value[0] in "[\"`" and value[-1] == ({"[": "]", "\"": "\"", "`": "`"}[value[0]]):
            return value[1:-1]
        return value
    return {"schema": unquote(match[1]), "table": unquote(match[2])}


def extraction_plan(mode, plugin, location, cursor):
    if mode not in {"full", "delta", "query"}:
        raise ValueError(f"unsupported extract_mode {mode!r}")
    table = source_table(location, plugin) if plugin in {"sqlserver", "oracle", "mysql", "postgresql"} and mode != "query" else None
    if mode == "delta" and (table is None or not cursor):
        raise ValueError("delta extraction needs a physical query-based source table and exactly one mapped extract_column=delta cursor")
    return {**table, "extract_mode": mode, "cursor_column": cursor} if table else None


@dataclass
class Dataset:
    key: str
    name: str
    zone: str
    job: str
    kind: str
    write_mode: str
    columns: list
    keys: list = field(default_factory=list)
    scd2: list = field(default_factory=list)
    surrogates: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    functions: list = field(default_factory=list)
    lookups: list = field(default_factory=list)
    transformation_steps: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    dependencies: set = field(default_factory=set)
    external: dict | None = None
    sequence_by: str | None = None
    delete_condition: str | None = None
    entity_name: str | None = None
    job_display: str | None = None

    @property
    def history_name(self):
        return self.zone + ".__history_" + self.name if self.kind == "materialized_view" and self.write_mode == "merge" else None

    @property
    def qualified_name(self):
        return self.zone + "." + self.name

    @property
    def pipeline_key(self):
        # The existing model job assignment is the operational pipeline
        # boundary. It groups related datasets across schemas/layers without
        # inventing a second grouping property or unstable dependency waves.
        return "pipeline_" + slug(self.job)

    @property
    def frame_spec_repr(self):
        return repr({"columns": self.columns, "keys": self.keys, "surrogates": self.surrogates, "lookups": self.lookups})

    @property
    def external_columns_repr(self):
        return repr(self.external["columns"])

    def validate(self):
        if self.kind not in {"materialized_view", "streaming_table"}:
            raise ValueError(f"{self.zone}.{self.name}: explicit dataset_type is required")
        if not self.job:
            raise ValueError(f"{self.zone}.{self.name}: explicit jobs assignment is required")
        if self.write_mode not in {"overwrite", "merge", "append"}:
            raise ValueError(f"{self.name}: unsupported write_mode {self.write_mode}")
        if self.kind == "materialized_view" and self.write_mode == "append":
            raise ValueError(f"{self.name}: append requires a streaming table")
        if self.write_mode == "merge" and not self.keys:
            raise ValueError(f"{self.name}: merge/AUTO CDC requires business keys")
        if self.surrogates and not self.keys:
            raise ValueError(f"{self.name}: deterministic surrogate keys require business keys")
        if any(column["name"] in self.surrogates and column["type"].lower() != "bigint" for column in self.columns):
            raise ValueError(f"{self.name}: Lakeflow surrogate keys must use bigint")
        if self.kind == "streaming_table":
            if self.surrogates:
                raise ValueError(f"{self.name}: surrogate projections require a materialized view over native history")
            if self.write_mode == "overwrite":
                raise ValueError(f"{self.name}: streaming_table requires append or merge")
            if self.sequence_by and self.write_mode != "merge":
                raise ValueError(f"{self.name}: sequence_by applies only to an AUTO CDC merge")
            if self.delete_condition and not self.sequence_by:
                raise ValueError(f"{self.name}: delete_condition requires sequence_by and a CDC feed")
        elif self.sequence_by or self.delete_condition:
            raise ValueError(f"{self.name}: sequence_by/delete_condition are only valid for streaming-table CDC")
        if self.sequence_by and self.sequence_by not in {column["name"] for column in self.columns}:
            raise ValueError(f"{self.name}: sequence_by column {self.sequence_by!r} is not modeled")
        if self.scd2 and self.write_mode != "merge":
            raise ValueError(f"{self.name}: SCD2 requires merge/AUTO CDC")



def function_sources(wrapper):
    functions = []
    for transformation in sorted(wrapper.entity.transformations or [], key=lambda item: item.stepNo):
        if enum_value(transformation.kind) == "builtin":
            if transformation.name != "lookup_dimensions":
                raise ValueError(f"{wrapper.entity.name}: unsupported builtin {transformation.name}")
            continue
        if enum_value(transformation.kind) != "function" or not transformation.function:
            raise ValueError(f"{wrapper.entity.name}: unsupported transformation kind")
        relative = Path(transformation.function.source)
        candidates = [wrapper.source_file.parent / relative, wrapper.source_file.parent / wrapper.entity.name / relative]
        existing = list(dict.fromkeys(path for path in candidates if path.is_file()))
        if not existing:
            raise ValueError(f"Missing transformation source for {wrapper.entity.name}")
        if len(existing) > 1:
            raise ValueError(f"Ambiguous transformation source for {wrapper.entity.name}: {existing}")
        source = existing[0].read_text(encoding="utf-8")
        # Notebook cell delimiters are harmless Python comments in a regular
        # file, but Databricks treats them as notebook cell boundaries even
        # when the function source is nested inside a generated pipeline.
        source = re.sub(r"(?m)^\s*#\s*(?:Databricks notebook source|COMMAND ----------)\s*$\n?", "", source)
        import ast
        tree = ast.parse(source)
        forbidden = {"collect", "collectAsList", "count", "first", "head", "take", "toLocalIterator", "toPandas", "show", "display", "save", "saveAsTable", "insertInto", "merge", "start", "toTable", "execute", "createOrReplaceTempView", "createTempView", "dropTempView", "dropTable", "createTable", "alterTable"}
        has_action = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
            and not (isinstance(node.func.value, ast.Name) and node.func.value.id in {"F", "functions"})
            for node in ast.walk(tree)
        )
        has_writer = any(isinstance(node, ast.Attribute) and node.attr in {"write", "writeStream"} for node in ast.walk(tree))
        def is_unsafe_spark_sql(node):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sql"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "spark"):
                return False
            if not node.args:
                return True
            statement = node.args[0]
            if isinstance(statement, ast.Constant) and isinstance(statement.value, str):
                prefix = statement.value
            elif isinstance(statement, ast.JoinedStr):
                prefix = "".join(part.value for part in statement.values if isinstance(part, ast.Constant))
            else:
                return True
            # Sample business functions use SQL only as a read-only SELECT.
            # Reject unknown/dynamic prefixes instead of trying to infer that
            # an arbitrary SQL expression cannot mutate a target.
            return not re.match(r"(?is)^\s*(?:SELECT|WITH)\b", prefix)

        has_mutating_sql = any(is_unsafe_spark_sql(node) for node in ast.walk(tree))
        if has_action or has_writer or has_mutating_sql:
            raise ValueError(f"{wrapper.entity.name}: business function contains an action or write")
        functions.append(source)
    return functions


def build_plan(model):
    wrappers = [wrapper for wrapper in model.modelEntities.values() if wrapper.locator.folders and wrapper.locator.folders[0] in {"010-Stage", "020-Core", "030-Curated"}]
    entities = {wrapper.entity.id: wrapper for wrapper in wrappers}
    sources = {wrapper.entity.name: wrapper.entity for wrapper in model.dataSources.values()}
    source_types = {wrapper.entity.name: wrapper.entity for wrapper in model.dataSourceTypes.values()}
    zones = {"010-Stage": "stage", "020-Core": "core", "030-Curated": "curated"}
    job_names = display_names(model, "jobs")
    datasets = {}
    raw_consumers = {}
    raw_consumer_modes = {}
    for wrapper in wrappers:
        entity = wrapper.entity
        settings = properties(model, wrapper)
        name = full_name(wrapper)
        zone = zones[wrapper.locator.folders[0]]
        key = zone + "." + name
        columns = [{"name": attribute.name, "type": target_data_type(model, attribute.dataType), "nullable": attribute.dataType.nullable, "expression": getattr(attribute, "expression", None)} for attribute in entity.attributes]
        dataset = Dataset(key, name, zone, settings.get("jobs"), settings.get("dataset_type"), settings.get("write_mode", "overwrite"), columns,
                          keys=[attribute.name for attribute in entity.attributes if attribute.isBusinessKey],
                          scd2=[attribute.name for attribute in entity.attributes if enum_value(attribute.history) == "SCD2"],
                          surrogates=[attribute.name for attribute in entity.attributes if is_surrogate(attribute)],
                          functions=function_sources(wrapper),
                          sequence_by=settings.get("sequence_by"), delete_condition=settings.get("delete_condition"))
        function_index = 0
        for transformation in sorted(entity.transformations or [], key=lambda item: item.stepNo):
            if enum_value(transformation.kind) == "function":
                dataset.transformation_steps.append({"kind": "function", "function_index": function_index})
                function_index += 1
            elif transformation.name == "lookup_dimensions":
                dataset.transformation_steps.append({"kind": "lookup"})
        dataset.entity_name = entity.name
        if dataset.job not in job_names:
            raise ValueError(f"{key}: unresolved model job assignment {dataset.job!r}")
        dataset.job_display = job_names[dataset.job]
        for source in entity.sources or []:
            mapping = [{"source": item.sourceName, "target": item.targetName} for item in source.mapping or []]
            if isinstance(source.sourceLocation, int):
                upstream = entities.get(source.sourceLocation)
                if upstream is None:
                    raise ValueError(f"{key}: unresolved source {source.sourceLocation}")
                source_key = zones[upstream.locator.folders[0]] + "." + full_name(upstream)
            else:
                data_source = sources[source.dataSource]
                source_type = source_types[data_source.type]
                plugin = getattr(source_type, "pluginId", None)
                if plugin not in {"sqlserver", "oracle", "mysql", "postgresql", "http_api"}:
                    raise ValueError(f"{key}: unsupported source plugin {plugin}")
                raw_name = "_".join([*wrapper.locator.folders[1:], source_alias(source)]).lower()
                source_key = "raw." + raw_name
                extended = data_source.extendedProperties or {}
                raw_columns = []
                for item in source.mapping or []:
                    target = next((column for column in columns if column["name"] == item.targetName), None)
                    if target is not None:
                        raw_columns.append({"name": item.sourceName, "type": target["type"], "nullable": True})
                external = {"source": data_source.name, "connection_suffix": extended.get("unityCatalogConnection", plugin if plugin != "http_api" else "shipping_api"), "plugin": plugin, "location": source.sourceLocation, "database": extended.get("database"), "service_name": extended.get("service_name"), "columns": raw_columns}
                extract_mode = source_property(source, "extract_mode", "full")
                cursor = source_extract_column(source)
                try:
                    managed_table = extraction_plan(extract_mode, plugin, source.sourceLocation, cursor)
                except ValueError as error:
                    raise ValueError(f"{key}: {error}") from None
                if dataset.write_mode == "append" and (extract_mode != "delta" or managed_table is None):
                    raise ValueError(f"{key}: append requires an explicitly incremental managed source")
                external.update({"extract_mode": extract_mode, "cursor_column": cursor})
                if managed_table:
                    external["managed_ingestion"] = {
                        **managed_table,
                        "source_catalog": extended.get("database") or extended.get("service_name"),
                        "include_columns": [item["name"] for item in raw_columns],
                        "primary_keys": [mapping.sourceName for mapping in source.mapping or [] if any(attribute.name == mapping.targetName and attribute.isBusinessKey for attribute in entity.attributes)],
                        "cursor_column": cursor,
                        "extract_mode": extract_mode,
                    }
                    if not external["managed_ingestion"]["primary_keys"]:
                        raise ValueError(f"{key}: managed query-based ingestion requires mapped business keys")
                if source_key in datasets:
                    if datasets[source_key].external != external:
                        raise ValueError(f"Conflicting external definitions for {source_key}")
                else:
                    raw_dataset = Dataset(source_key, raw_name, "raw", dataset.job, "streaming_table" if external.get("managed_ingestion") else "materialized_view", "merge" if external.get("managed_ingestion") else "overwrite", raw_columns,
                                          keys=external.get("managed_ingestion", {}).get("primary_keys", []), external=external)
                    raw_dataset.job_display = job_names.get(dataset.job, dataset.job)
                    datasets[source_key] = raw_dataset
                raw_consumers.setdefault(source_key, set()).add(dataset.job)
                raw_consumer_modes.setdefault(source_key, set()).add(dataset.write_mode)
            dataset.sources.append({"dataset": source_key, "mapping": mapping})
            dataset.dependencies.add(source_key)
        for relation in entity.relationships or []:
            if relation.targetLocation not in entities:
                raise ValueError(f"{key}: unresolved relationship {relation.targetLocation}")
            target = entities[relation.targetLocation]
            target_key = zones[target.locator.folders[0]] + "." + full_name(target)
            dataset.relationships.append({"dataset": target_key, "attributes": [{"source": item.sourceName, "target": item.targetName} for item in relation.attributes]})
            target_surrogates = [attribute.name for attribute in target.entity.attributes if is_surrogate(attribute)]
            if target_surrogates and any(enum_value(item.kind) == "builtin" and item.name == "lookup_dimensions" for item in entity.transformations or []):
                business_keys = [attribute.name for attribute in target.entity.attributes if attribute.isBusinessKey]
                joins = [{"source": item.sourceName, "target": item.targetName} for item in relation.attributes if item.targetName in business_keys]
                if joins:
                    dataset.lookups.append({"dataset": target_key, "joins": joins, "columns": target_surrogates, "current_filter": "__IsCurrent" if properties(model, target).get("dataset_type") == "materialized_view" else "__END_AT IS NULL" if any(enum_value(attribute.history) == "SCD2" for attribute in target.entity.attributes) else None})
                    dataset.dependencies.add(target_key)
        dataset.validate()
        datasets[key] = dataset
    for raw_key, consumers in raw_consumers.items():
        if len(consumers) != 1:
            raise ValueError(f"{raw_key}: external raw data is assigned to multiple model jobs; model the source in one job and reference its modeled dataset from other jobs")
        owner = next(iter(consumers))
        raw_dataset = datasets[raw_key]
        raw_dataset.job = owner
        raw_dataset.job_display = job_names[owner]
        modes = raw_consumer_modes[raw_key]
        if "append" in modes:
            if modes != {"append"}:
                raise ValueError(f"{raw_key}: an append-only raw source cannot also feed a mutable model dataset")
            if not (raw_dataset.external or {}).get("managed_ingestion") or (raw_dataset.external or {}).get("extract_mode") != "delta":
                raise ValueError(f"{raw_key}: append requires an incremental managed source")
            raw_dataset.write_mode = "append"
    for dataset in datasets.values():
        if dataset.kind == "streaming_table" and (dataset.write_mode == "append" or dataset.sequence_by):
            if dataset.external and dataset.external.get("managed_ingestion"):
                if dataset.write_mode == "append" and dataset.external.get("extract_mode") != "delta":
                    raise ValueError(f"{dataset.key}: append ingestion requires an incremental managed source")
            else:
                parents = [datasets[parent] for parent in dataset.dependencies]
                if not parents or any(parent.kind != "streaming_table" or parent.write_mode != "append" for parent in parents):
                    raise ValueError(f"{dataset.key}: streaming input requires an append-only streaming source; snapshots and mutable tables are not append streams")
            if dataset.functions:
                raise ValueError(f"{dataset.key}: streaming business functions need an explicit supported streaming source contract")
    ordered, visiting, visited = [], set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("Cycle in dataset graph at " + key)
        if key in visited:
            return
        visiting.add(key)
        for dependency in sorted(datasets[key].dependencies):
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
        ordered.append(datasets[key])

    for key in sorted(datasets):
        visit(key)
    return ordered
