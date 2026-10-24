# Lakeflow Target Architecture

The [target overview](README.md) describes generation and deployment. This target
is isolated from the existing Databricks payloads, model metadata and bundle.

## Payload Contracts

- `payload.py` registers schema, cluster, notebook, runtime, pipeline and job payloads.
- `payload_common.py` resolves zones, inherited properties, types, source mappings
  and transformation paths. Missing optional folders are skipped independently of
  the backend repository's lookup exception behavior.
- `ddl_payloads.py` and `dml_payloads.py` generate modeled table notebooks including
  identity metadata, SCD merges and dimension lookups.
- `lakeflow_payloads.py` selects materialized overwrite entities, builds external
  ingestion definitions and calculates dependencies within and between job groups.
- Templates render prepared payload data. Runtime notebooks are copied through
  `runtime_file.jinja2` and referenced relative to the generated notebook location.

When zones have an explicit `target`, that value controls selection. Otherwise
the existing `raw`, `stage`, `core`, and `curated` zones are selected. Schema names
use `targetName`; notebook folders use `localFolderName` when present. Both old
and new cursor markers and table-property spellings are supported. Existing job
groups and property values do not require renaming.

Materialized entity pipelines are used only for overwrite entities without
transformations, SCD0/SCD2 history or surrogate keys. Other entities receive
DDL/DML notebooks. Full snapshots and managed ingestion retain source column
names; downstream mappings are applied once. Managed ingestion is not assumed
to provide synthetic extraction timestamps.

Transformation paths are normalized to basenames for generated function modules.
An AST pass relocates recognized modeled table references inside string literals
in copied scripts. Original model files and the existing target's output are
unchanged. Expressions outside those literals are not rewritten.

## Verification

The generation workflow checks two pinned backend/schema pairs:

| Backend | Schema submodule |
| --- | --- |
| `d53fd5561a254385412fb109585475cbba00287d` (existing dependency tag) | `e8c24f32971a9e4f1cd2b90526e213b209a91dd0` |
| `3e3d89cdf404d1d4d2335c7736a85427f0f07931` (2.0.0 runtime) | `beaea1839810dcd535d87d0a973e67b8e9959e3e` |

With either runtime installed, run from the repository root:

```sh
python scripts/check_lakeflow.py --baseline-ref main
```

The check creates disposable full solutions and runs real generation in fresh
processes. It verifies notebook paths, Python/YAML syntax, job dependencies,
source mappings, legacy/new delta markers, Oracle options, identity metadata,
SCD2 generation, and dimension lookup contracts. It compares the existing target
outputs with `main`; documentation generation timestamps are normalized.

The 2.0.0 runtime exposes an existing Power BI incompatibility on `main`:
`relationships_payload` calls the removed `Model.get_model_entity_by_id` API.
The check reports that specific baseline failure and verifies the candidate has
the same failure and partial output. Other generation failures fail the check.
The existing Power BI target is outside this change.

Run documentation checks with:

```sh
node --test scripts/check-docs.test.mjs
node scripts/check-docs.mjs
```

Generation checks are offline with respect to source databases and Databricks.
Deployment and actual Spark/Delta execution require separate environment acceptance.
