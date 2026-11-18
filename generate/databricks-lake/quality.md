# Batch Quality Runtime Reference

The shared DataM8 schema stores opaque rule definitions and open target options.
It has no tool or check catalogue. This target interprets definitions as native
DQX metadata and runs `databricks-labs-dqx==0.16.0` on classic compute. Other targets
can interpret different definition formats without changes to Model, CLI or the
shared editor. Quality-enabled jobs reject serverless configuration.

## Native definitions and artifacts

A check has `id`, `execution`, `definition`, and optional `description`. For this
target the definition contains the native DQX envelope: `check.function`, optional
arguments, criticality, filters, per-column expansion, messages and metadata.
There is no function allow-list or translation of DataM8 check types. DQX validates
function names and signatures. `user_metadata.datam8_check_id` is injected for
stable audit attribution and must not be supplied in the model.

Each entity emits `quality/<entity ID>/manifest.json`, `enforcement.yaml` and a
YAML file for each configured monitoring input. Rules without an input option use
the complete target; native row and dataset checks share the same DQX API.

Notebooks expose the flow in named cells. DDL shows complete nullable quarantine
and metrics SQL. DML shows DQX execution, the valid/invalid split, quarantine,
target writes, metrics and the strictly-greater-than threshold decision. Monitoring
shows target reads, declared input SQL, DQX calls, metric projections and writes.
`utils/QualityFramework.py` contains technical loading, context, input validation,
metric formatting and idempotent audit I/O. It has no check implementations.

## Declarative SQL inputs and metrics

Additional settings are target-owned. `settings.dependencies` declares PyPI
requirements for tasks that execute quality; monitoring-only DML has no DQX
initialization or quality libraries. Named `settings.inputs` declare read-only SQL
for monitoring. `{target_table}` expands to the quoted target; `:evaluated_at` binds
a single fixed evaluation time. SQL is generated visibly in the notebook and
validated before execution. SQL commands that modify data are rejected.

A rule's optional `definition.datam8` is consumed by this target before passing
the remaining native envelope to DQX. `input` selects a named input. An optional
`metrics` object declares scalar SQL expressions `checked_rows`, `measured_value`,
`failed_rows` and `no_data_when` (`checked_rows` is required). A metric projection
requires exactly one result row; `no_data_when` must be Boolean. Without metric
projections, metrics count checked/failed rows and record their failure ratio.
These options are generic and do not infer behavior from function names or IDs.

The [fixture](../../tests/fixtures/quality/QualityProbe.json) models a shared SQL
aggregate for completeness, latest-timestamp age and row count. Its native SQL
checks and metric expressions explicitly retain these policies: empty completeness
is `NO_DATA`; missing/future timestamps fail freshness; row count evaluates zero.
The calculations and policies are model data, not runtime check categories.

## Execution and storage

Enforcement checks original prepared input before SCD/merge staging. Error rows
enter `<target>_quarantine`; warning-only rows remain valid. Empty/all-invalid
output does not overwrite the target. Audit metrics are written before a gate
failure; the gate counts distinct error rows once. Monitoring violations are
results; technical errors fail the task, including on empty inputs.

After a gate failure with committed valid rows, monitoring can run via `ALL_DONE`
and an attempt-specific signal. Technical failures, failed reference loads and
failed all-invalid loads exit before quality evaluation. Successful empty loads
retain monitoring behavior. Dependent entity loads still depend on DML success.

Quarantine columns are nullable without target identity, NOT NULL or PK constraints,
plus `__dm8_dq_audit`. Central metrics use `<catalog>.quality.dqx_metrics`, one row
per rule, execution, run and attempt. Delta transaction identities prevent repeated
audit writes for the same identity. Target, quarantine and metrics writes are
separate transactions; a new run follows normal append/overwrite/merge behavior.
Reserve `__dm8_dq_*`, `_errors`, `_warnings` and `_dq_info` for runtime output.
No automatic retention cleanup is performed.

## Metadata conversion and acceptance

Legacy check shapes require explicit conversion. Preview selected entity files:

```sh
python scripts/convert_quality_definitions.py path/to/Entity.json
python scripts/convert_quality_definitions.py path/to/Entity.json --write
```

The converter is a one-time metadata utility, never called by generation/runtime.
It preserves IDs and turns old aggregate semantics into declared SQL and metric
projections. New hashes are expected; existing audit history and table schemas
remain intact. No database migration or MigrationFramework change is needed.

Use disposable copies for local generation and tests. Acceptance notebooks under
`tests/fixtures/quality` run only with explicit isolated `dm8_quality_test_*`
catalogs and classic clusters. Place the function `QualityProbe.py` beside entity
JSON files. Upload generated assets, utilities and fixtures together; do not mix
old notebooks with new helpers. Tests cover native definitions, declared aggregates,
thresholds, warnings, empty/all-invalid input, append/SCD1/SCD2 and repair isolation.

The public SQL reader requires DBR 18.3 `remote_query` support. The Runtime 18 LTS
selector is `18.x-scala2.13`; verify the actual runtime and source connectivity.
Do not commit workspace/source bindings or credentials. Database schema changes
are performed explicitly in SQL; the existing MigrationFramework is unchanged.
