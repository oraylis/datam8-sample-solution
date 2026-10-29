# Native Lakeflow Architecture

## Generation

[`dataset_plan.py`](__modules/dataset_plan.py) resolves properties and builds a
single directed dataset graph. It rejects missing sources, cycles, incompatible
dataset/write modes and unsupported streaming inputs before rendering.
[`native_payloads.py`](__modules/native_payloads.py) groups this graph by the
existing model `jobs` assignment, across Raw, Stage, Core and Curated schemas.
It emits one Lakeflow pipeline for each model job/cadence, plus scheduled
orchestration jobs, schemas, runtime files and the generation manifest. The
pipeline source qualifies each dataset with its schema, so a pipeline can own
and update connected datasets across layers. Layer boundaries alone do not
create job-level barriers.

Cross-pipeline edges come from actual dataset dependencies. The graph must
remain acyclic after grouping; otherwise generation reports the cycle instead
of splitting work into order-dependent numeric waves. A shared external
source must be assigned to exactly one model job. If different jobs claim the
same raw table, generation fails and asks the model to place its source entity
in one job and reference that modeled dataset from the others.

Each orchestration job refreshes only its own model pipeline and managed
ingestion pipelines. An upstream dataset assigned to another job is read from
its existing state; its job is not nested into the downstream job. The manifest
keeps cross-job dependencies so the local and CI runner executes each selected
job once in dependency order and stops downstream execution after a failure.
For this sample, the runner refreshes Sales (Daily) before Sales (Weekly),
while the Sunday schedule remains an independent job schedule. There is no
all-datasets job.

Workspace names begin with `[dev]` or `[prod]`. Job names use
`Load: <model job display name>`; pipeline names use
`Pipeline: <model job display name>` so they cannot be confused with their
orchestration jobs. Since each
pipeline spans multiple schemas, no single layer name is appended. The target
appears only in the `platform=databricks-lakeflow` tag. Managed ingestion
pipelines use one pipeline per model job and UC connection and are tasks only
in that model job. Their display names include both the model job display name
and connection family.

## Transformations and history

[`pipeline.py.jinja2`](native/pipeline.py.jinja2) emits ordinary workspace Python
files. Every public dataset is declared explicitly. Business functions remain
DataFrame transformations; the generator rejects actions and imperative writes.
Mappings and explicit dimension lookups are reused for projections. Lakeflow
does not define `__file__` while evaluating these files, so runtime helpers are
imported from the synchronized runtime path supplied through pipeline
configuration rather than resolving paths from the Python module.

Snapshot-backed SCD2 entities receive an internal AUTO CDC streaming history
and a public materialized view. SCD1 changes update the existing version; only
the model's SCD2 columns create a new version. Technical load timestamps are not
part of the history input. The public view computes surrogate keys using the
canonical business-key values and native version beginning. No migration
framework, classic DDL notebooks or custom Delta MERGE fallback is generated.
Every modeled `write_mode=merge` uses AUTO CDC, including SCD1 entities without
surrogate keys. A plain materialized view is reserved for `write_mode=overwrite`.

There is one Lakeflow surrogate rule rather than a model strategy selector.
Databricks does not support identity columns on AUTO CDC targets and warns that
materialized-view identities can be recomputed on updates. See the official
[pipeline limitations](https://docs.databricks.com/aws/en/ldp/limitations).
The classic target keeps Delta identity keys; cross-target checks compare
business values and dimension business keys instead of generated identity values.
The calendar's calculated DateSID alias avoids a second generated date key.

For append processing, the read is genuinely streaming. `write_mode=append`
describes the output and the planner separately verifies the input dataset's
append contract. It never infers a stream from a delta extraction watermark.
No generic `stream_semantics` property is needed for the supported graph.

## Source access and packaging

[`uc_sources.py`](../shared/uc_sources.py) is shared with the classic target.
SQL Server, Oracle, MySQL and PostgreSQL reads use UC `remote_query`. HTTP uses
only the UC connection proxy and its managed OAuth identity. The HTTP reader
checks pagination cursors and totals, bounds retries and converts values to
explicit Spark types. A failed page fails the entire dataset.

The public model stores `.example.invalid` endpoints and `ref://sample/...`
secret references. Environment-specific connection suffixes and database/service
bindings live in [integration configuration](../../tests/integration/environments.json).
Integration applies these non-secret bindings to the local solution through the
CLI and restores its original metadata in a `finally` block. No temporary
solution is used. Source plugins are installed locally from a checksummed lock;
plugin files are Git-ignored.

Bundle resource YAML is included separately from synchronized Python files.
[`bundle_assets.py`](../../scripts/bundle_assets.py) checks resource and `%run`
references against explicit sync includes. Integration also checks the uploaded
workspace paths, deployed pipeline compute against the model's cluster
property, and run-as settings.

## Safety and acceptance

Dev permits a controlled reset of its isolated sample catalogs and runs full
Create, Load and data checks. Prod permits deployment and bounded source smoke
queries only. It cannot run a reset or a full load through this runner.

The runner rejects foreign catalog objects, mixed deployment bindings, active
runs and unexpected resource replacement. A native reset refreshes only the
owned pipeline graph; subsequent runs use no full refresh. All expected datasets
come from generation manifests. Missing tasks, skipped required work, empty
tables, key violations and incomplete HTTP responses fail acceptance.

See the [integration guide](../../docs/integration-tests.md) for the current
live-test status and commands. Generation success alone is not data acceptance.
