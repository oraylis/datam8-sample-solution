# Databricks Lakeflow Target

This optional target adds Lakeflow ingestion and snapshot pipelines to the sample.
It uses the existing Base and Model metadata. The default `databricks` target,
its generated paths, and its deployment example remain available independently.

## Generate

Use the DataM8 app's generator selection or run:

```sh
datam8 generate databricks-lakeflow --solution ./ORAYLISDatabricksSample.dm8s
```

Output is written to `Output/databricks-lakeflow/generated` and is ignored by Git.
The adjacent [bundle example](../../Output/databricks-lakeflow/databricks.yml)
deploys only this target. Generated notebooks and runtime files are self-contained.

## Generated Processing

- External sources with `extract_mode=delta` use query-based Lakeflow Connect
  ingestion. A single mapping must mark the cursor with `extract_mode=delta` or
  the existing `extract_column=delta`. Source business keys are mapped back to
  physical source column names.
- Full and query sources use pipeline notebooks with `remote_query` and produce
  materialized snapshots. SQL Server uses its configured database; Oracle uses
  `service_name`, `service`, or the existing `connection` setting.
- Simple modeled overwrite entities use Lakeflow materialized tables. Internal
  sources are read as snapshots so updates are included.
- Transformations, merges, history, surrogate keys, and append processing use
  regular DDL/DML notebooks. SCD2 columns and current-record filters are retained.
  Overwrite entities with surrogate keys use a merge that preserves matching
  identities and deletes rows absent from the new snapshot.
  Append directly from an external snapshot is rejected because it would replay
  the entire snapshot on every run.

Raw landing tables retain physical source column names for both ingestion paths;
the modeled load applies column mappings and calculations once. Notebook merges
read the current landing snapshot on each run, rather than assuming managed
ingestion creates the sample's synthetic extraction timestamps. History records
changes visible at modeled load time, not every intermediate source change.

The target supports `full`, `query`, and query-based `delta` extraction. Gateway
CDC ingestion requires a separate implementation and is rejected during generation.

## Configure Deployment

1. Configure your Databricks CLI profile or deployment environment. The example
   contains no workspace URL or credentials.
2. Create Unity Catalog connections named after the data source in lowercase,
   for example `adventureworks` and `oracledev`, and grant the execution identity
   the necessary connection and catalog permissions.
3. Set `catalog_name` and review cluster variables and the `lf_` schema prefix.
   Generated schemas use each zone's `targetName`, for example `lf_bronze`.
   The personal development target adds your short user name to the prefix.
4. From `Output/databricks-lakeflow`, validate the bundle in your environment,
   deploy it, run **Lakeflow Create All Tables**, and then **Lakeflow Load All Tables**.

`remote_query` requires a compatible Databricks runtime. The pipeline examples
use the preview channel. See Databricks' [remote query reference](https://docs.databricks.com/aws/en/query-federation/remote-queries)
and [query-based ingestion guide](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/query-based-pipeline)
for connector requirements.

Existing job names such as `sales_daily` and `sales_weekly` are preserved. A
schedule is emitted only when the selected schedule value explicitly defines
`quartz_cron_expression`; the old abbreviated `cron` example is not guessed.
Schedules are paused by default. Per-run catalog/schema overrides must agree
with deployed pipeline settings; pipeline destinations are deployment settings.

Model transformation files remain unchanged. When copying functions, this target
relocates recognized literal references to modeled tables to the chosen catalog,
schema prefix, and zone `targetName`. Custom dynamically constructed references
must use the notebook's `catalog_name` and `schema_prefix` themselves.

Generated DDL refuses automatic identity-table rebuilds that could change existing
surrogate keys. Schema changes on those tables require a manual migration that
preserves key values. DDL errors propagate to the job.

For contracts, scope and verification, see [ARCHITECTURE.md](ARCHITECTURE.md).
