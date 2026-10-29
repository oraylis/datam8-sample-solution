# Databricks Lakeflow Target

This target publishes native Lakeflow materialized views and streaming tables.
The classic notebook target remains independently deployable.

Pipeline compute is selected by the `cluster` reference nested in each model
`jobs` property. The sample currently uses the `extra_small` classic cluster for
processing and managed-ingestion pipelines. Query-based connector support for
classic pipeline compute is currently Beta in Databricks; Serverless remains an
available model choice by setting the job's nested cluster value to `serverless`.

```powershell
uv run python scripts/check_generation.py --target databricks-lakeflow
```

Artifacts are generated locally into `Output/databricks-lakeflow/generated`.
The adjacent [bundle](../../Output/databricks-lakeflow/databricks.yml) deploys
these files to the selected Dev or Prod workspace. Generated files are ignored
by Git and explicitly included in bundle synchronization.

Workspace display names start with `[dev]` or `[prod]`. A scheduled job uses
`Load: <model job display name>`; its Lakeflow pipeline uses
`Pipeline: <model job display name>`. Processing pipelines group datasets by
the model's `jobs` assignment and span physical layer schemas. Managed
ingestion is grouped by model job plus UC connection. Each load job refreshes
only its own processing and ingestion pipelines. Cross-job dependencies stay
in the manifest for ordered local/CI execution; a downstream job does not
start its upstream job. Jobs and pipelines carry only the target tag
`platform=databricks-lakeflow`.

In this sample, the local/CI runner updates the daily job before the weekly
Sales job. The weekly cloud job refreshes only the weekly pipeline and reads
the existing daily outputs; its Sunday 02:00 schedule does not invoke the daily
job. Database tables use managed query-based ingestion grouped by model job
and UC connection; views, custom queries and the shipping API use explicit UC
snapshot readers. Each ingestion pipeline is a task only in its owning job.
There is no Load All Tables job. Schedules come from the model job properties
and remain paused by default.

## Model contract

- `dataset_type` selects `materialized_view` or `streaming_table`. Entity settings
  override the closest folder, then its parents. The sample sets it explicitly.
- Source-level `extract_mode` selects `full`, `delta` or `query`. Delta requires
  one source-mapping `extract_column=delta` cursor. A missing cursor is a
  generation error.
- `write_mode=append` requires a real append-only streaming input. An external
  database or HTTP snapshot cannot become an append stream by changing this flag.
- `write_mode=merge` always uses native AUTO CDC. It defaults to SCD1; only
  attributes marked `SCD2` create historical versions. Full snapshots use
  `create_auto_cdc_from_snapshot_flow`; ordered event feeds use
  `create_auto_cdc_flow` with explicit sequencing and deletion metadata.
- `StockMovement` demonstrates append without a business key in Stage, with
  PostgreSQL delta extraction using `modifiedat`. Raw ingestion uses `APPEND_ONLY`:
  an observed change with a later cursor becomes another appended row. Core uses
  `overwrite` as a materialized view of the accumulated Stage contents. This
  example does not interpret hard deletes or reconstruct changes below the cursor.
- Surrogate-key behavior is a target rule, with no strategy property. Classic
  Delta notebooks retain identity columns. Native history targets cannot use
  identity columns, so Lakeflow projects a deterministic signed 64-bit hash of
  the canonical business key and history version. Acceptance rejects collisions.
- The calendar has `DateID` as its stable key. `DateSID` is a calculated
  compatibility alias defined using the existing attribute-expression contract.

All five external source families use Unity Catalog connections. Credentials and
hosts are absent from generated artifacts. HTTP snapshots use the shared UC
proxy reader, with complete pagination and strict failure on partial responses.

The current sample has 22 Raw, 21 Stage, 15 Core and 11 Curated public objects.
Internal history streaming tables are listed separately in `manifest.json`.
The data products are MasterData, Sales, Procurement, Inventory, Commerce and
Shipping; their names form part of the generated physical table names.

See [architecture](ARCHITECTURE.md), [Lakeflow properties](PROPERTIES.md), and
the [deployment guide](DEPLOYMENT.md) for environment-specific bindings. The
[integration guide](../../docs/integration-tests.md) covers shared runner
behavior and acceptance checks.
