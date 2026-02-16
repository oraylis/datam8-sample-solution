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
- `generate_raw_ddl_notebooks` -> `ddl_notebook_raw.py.jinja2`
- `generate_dml_notebooks` -> `dml_notebook.py.jinja2`
- `generate_raw_dml_notebooks` -> `dml_notebook_raw.py.jinja2`
- `generate_dml_function_scripts` -> `dml_function.py.jinja2`
- `generate_schema_resources` -> `schema.yml.jinja2`
- `generate_cluster_resources` -> `clusters/clusters.yml.jinja2`
- `generate_jobs_create_all` -> `jobs/create_all.yml.jinja2`
- `generate_jobs_create_zones` -> `jobs/create_zone.yml.jinja2`
- `generate_jobs_create_modules` -> `jobs/create_module.yml.jinja2`
- `generate_jobs_load_all` -> `jobs/load_all.yml.jinja2`
- `generate_jobs_load_groups` -> `jobs/load_job_group.yml.jinja2`

## Important Internal Contracts
- Product/module name fallback logic is centralized in `_resolve_product_module_context`.
- Merge assignment and schema-column shaping must keep key names consumed by `dml_notebook.py.jinja2`.
- Raw extraction mapping projection is centralized in `_raw_mapping_projection`.
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
