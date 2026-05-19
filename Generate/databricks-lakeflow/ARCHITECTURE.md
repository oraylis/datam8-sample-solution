# Databricks Generator Architecture

## Purpose

This target generates Databricks notebooks and Databricks Asset Bundle resources:

- table DDL notebooks
- table DML notebooks
- external extraction notebooks
- transformation function files
- schema, cluster, and job YAML resources

## Generation Flow

1. `__modules/payload.py` registers payload builders via `@register_payload(...)`.
2. `payload_common.py` centralizes target naming, zone handling, property lookup, source wrappers, and shared payload classes.
3. `ddl_payloads.py`, `dml_payloads.py`, and `jobs_payloads.py` shape template-facing payload contracts.
4. Jinja2 templates under `notebooks/`, `jobs/`, and the target root render files from prepared payload objects.

## Payload to Template Mapping

- `ddl_notebooks` -> `notebooks/ddl_notebook.jinja2`
- `ddl_external_notebooks` -> `notebooks/ddl_notebook.jinja2`
- `dml_notebooks` -> `notebooks/dml_notebook.jinja2`
- `dml_external_notebooks` -> `notebooks/dml_external_notebook.jinja2`
- `dml_function_scripts` -> `notebooks/dml_function.jinja2`
- `dab_schemas` -> `schema.yml.jinja2`
- `dab_cluster` -> `clusters.yml.jinja2`
- `jobs_create_all` -> `jobs/create_all.yml.jinja2`
- `jobs_create_zones` -> `jobs/create_zone.yml.jinja2`
- `jobs_create_modules` -> `jobs/create_module.yml.jinja2`
- `jobs_load_all` -> `jobs/load_all.yml.jinja2`
- `jobs_load_groups` -> `jobs/load_job_group.yml.jinja2`

## Property-Driven Behavior

| Property | Scope | Output impact |
|---|---|---|
| `target` | zone (`Base/Zones.json`) | Selects zones where `target=databricks`. Controls schemas and model-backed notebook generation. |
| `jobs` | entity and inherited folder properties | Groups entities into generated load jobs. Defaults to `daily` when omitted. |
| `schedules` | property value referenced by `jobs` | Adds Quartz cron schedules to generated load jobs. |
| `cluster` | property value referenced by `jobs` | Selects the Databricks cluster variable for generated jobs. |
| `business_area` | entity and inherited folder properties | Emits business-area metadata as Databricks table tags. |
| `write_mode` | entity or inherited folder property | Controls DML write behavior such as `merge`, `overwrite`, or `append`. |
| `extract_mode` | source and mapping properties | Controls extraction behavior and delta column handling. |
| `table_properties` | entity and inherited folder properties | Emits Delta table properties and table-tag metadata such as column mapping and type widening. |
| `data_retention` | entity and inherited folder properties | Emits Delta retention properties. |
| `attribute_type=sk` | attribute properties | Marks surrogate key columns and affects generated DDL/DML behavior. |

## Important Internal Contracts

- `ModelEntityPayload` is the base class for model-entity notebook payloads.
- `ExternalSource` and `InternalSource` are template-facing wrappers for source definitions.
- Output paths are calculated in payload classes, not in templates.
- Zone folder names use `localFolderName`, then `targetName`, then zone name.
- Databricks table properties and tags are derived in DDL payload classes from resolved entity and folder properties.
- DML transformation metadata is cached under `dml_transformations::<locator>` for reuse by function payloads.

## Template Style

- Keep Jinja templates close to the generated Databricks notebook or YAML syntax.
- Add fallback, inheritance, naming, and mapping logic in Python payloads.
- Prefer explicit template fields over deep object traversal.
- Keep output deterministic by sorting and grouping in Python where needed.

## Extending Safely

1. Define the desired output and output path.
2. Add or extend the payload field in Python.
3. Render the field in Jinja only after the payload contract is clear.
4. Update this architecture file when adding interpreted properties or new artifact families.

## Validation Checklist

```console
ruff check Generate/databricks/__modules
```

Then run generation and inspect `Output/databricks`.

For behavior-preserving refactors, compare output directories with:

```console
pwsh ./scripts/verify_generation_parity.ps1 -BaselineRoot ./Output/databricks -CandidateRoot <candidate-output>
```
