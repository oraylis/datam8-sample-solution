# Databricks Lake Generator Architecture

## Purpose
This target generates Databricks notebooks and bundle resources for:
- table DDL
- table DML
- function script copy-through
- bundle schemas/clusters/jobs

## Generation Flow
1. `__modules/payload.py` registers payload builders via `@register_payload(...)`.
2. Each payload builder reads model metadata through `MetadataResolver` in `__modules/metadata_utils.py`.
3. Payload-shaping helper functions are grouped in `__modules/payload_helpers.py`.
4. Jinja templates in this target render output files from payload dictionaries.

## Payload to Template Mapping
- `generate_ddl_notebooks` -> `ddl_notebook.py.jinja2`
- `generate_external_ddl_notebooks` -> `ddl_notebook_external.py.jinja2`
- `generate_dml_notebooks` -> `dml_notebook.py.jinja2`
- `generate_external_dml_notebooks` -> `dml_notebook_external.py.jinja2`
- `generate_dml_function_scripts` -> `dml_function.py.jinja2`
- `generate_schema_resources` -> `schema.yml.jinja2`
- `generate_cluster_resources` -> `clusters/clusters.yml.jinja2`
- `generate_jobs_create_all` -> `jobs/create_all.yml.jinja2`
- `generate_jobs_create_zones` -> `jobs/create_zone.yml.jinja2`
- `generate_jobs_create_modules` -> `jobs/create_module.yml.jinja2`
- `generate_jobs_load_all` -> `jobs/load_all.yml.jinja2`
- `generate_jobs_load_groups` -> `jobs/load_job_group.yml.jinja2`

## Property-Driven Behavior

The Databricks target actively interprets the following properties.

| Property | Scope | Output impact |
|---|---|---|
| `target` | zone (`Base/Zones.json`) | Selects zones for this target (`target=databricks`). Controls which zones produce notebooks and schema resources. |
| `jobs` | entity + folder (inherited) | Groups entities into load jobs (`jobs/load_<group>.yml`) and controls which entities are chained together. |
| `schedules` (via `jobs` value) | property value | Sets Quartz cron schedule in generated load jobs (and `load_all` fallback schedule). |
| `cluster` (via `jobs` value) | property value | Selects cluster variable/definition used for generated Databricks load jobs. |
| `write_mode` | entity | Drives modeled DML write logic (`merge` vs write modes like `overwrite`/`append`) and generated merge behavior. |
| `extract_mode` | external source properties | Controls external extraction strategy. `delta` enables incremental filter logic; `query` treats `sourceLocation` as full SQL query text; otherwise `sourceLocation` is treated as table/object name. |
| `extract_column` | mapping/column properties | Marks source delta column(s) and influences incremental extraction metadata in external DML notebooks. |
| `table_properties` (`column_mapping`, `type_widening`) | entity + folder (inherited, multi-value) | `column_mapping` emits `delta.columnMapping.mode=name`; `type_widening` emits `delta.enableTypeWidening=true` in DDL notebooks. |
| `data_retention` | entity | Emits Delta table properties `delta.logRetentionDuration` and `delta.deletedFileRetentionDuration`. |
| `attribute_type=sk` | attribute properties | Marks surrogate keys and affects merge assignment behavior / dimension lookup handling. |

Property precedence follows resolver logic:
1. entity value (if allowed by scope)
2. inherited folder value (if allowed by scope)
3. backward-compatible entity fallback

## Important Internal Contracts
- Product/module name fallback logic is centralized in `_resolve_product_module_context`.
- Merge assignment and schema-column shaping must keep key names consumed by `dml_notebook.py.jinja2`.
- External extraction mapping projection is centralized in `_external_mapping_projection`.
- Job planning shape comes from `JobsPlanner.build()` and is cached under `("databricks_jobs_plan",)`.

## Template Style
- Templates are intentionally kept close to generated notebook/YAML output.
- Avoid extracting large shared Jinja partials for core job/notebook templates.
- Prefer reuse in Python payload/helper modules over template indirection.

## Extending Safely
1. Add new payload fields in `payload.py` first.
2. Reference them in templates only after field names are stable.
3. Reuse existing helpers before adding new inline metadata logic.
4. Keep notebook/job output paths unchanged unless a migration is planned.

## Validation Checklist
1. Run lint: `ruff check Generate/databricks-lake/__modules`
2. Validate template rendering in local generation run.
3. Run parity check against baseline output:
   `scripts/verify_generation_parity.ps1`
