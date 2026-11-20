# SQL Quality Runtime Reference

The shared DataM8 schema has a fixed SQL contract. Checks have `id`, `execution`
and `expression`, with optional `severity` (default `error`), `description`,
monitoring-only `sql` and `onEmpty` (default `evaluate`, only with `sql`). The
entity-wide gate is `quality.maxFailureRatePct`; `quality.references` binds aliases
to active model `entityId` values. Unknown fields and older formats are rejected.
There is no converter, migration, check-type catalogue or compatibility path.

Only this solution's payloads and templates translate model SQL into Databricks
SQL and native `databricks-labs-dqx==0.16.0` metadata. Model, CLI and the shared UI
have no DQX mapping. Technical validation and audit I/O remain in
`utils/QualityFramework.py`; it does not interpret alternate rule dialects.

## Supported SQL profile

The pinned SQLGlot parser and an explicit AST allow-list support literals,
ANSI-quoted identifiers, arithmetic and comparisons, Boolean operators, NULL
checks, IN, BETWEEN, LIKE and null-safe equality; CASE, CAST, COALESCE, NULLIF,
TRIM, LENGTH and REGEXP_LIKE; COUNT, SUM, MIN and MAX. Row expressions may use
COUNT/SUM windows with PARTITION BY, without ORDER BY or explicit frames.
Non-windowed aggregates belong in monitoring queries, not row expressions.

Monitoring SQL supports SELECT, nonrecursive CTEs, subqueries, DISTINCT, filters,
grouping and INNER/LEFT JOIN. It must select exactly `checked_rows` and
`measured_value`. Unsupported functions, UDFs, statements, query shapes and table
bindings fail explicitly. This is a bounded adapter, not a general SQL transpiler.

`CURRENT_TIMESTAMP` binds to the notebook's fixed evaluation instant. The public
`TIMESTAMPDIFF(unit, start, end)` supports SECOND and MICROSECOND. The adapter
normalizes argument order explicitly. Freshness uses MICROSECOND / 1000000.0,
preserving subsecond resolution and rejecting missing/future timestamps through
the model's Boolean condition. There is no freshness-specific runtime function.

`{target}` and declared `{references.alias}` occur only as query relations. The
payload turns them into bound `IDENTIFIER(:parameter)` clauses. Quoted strings
containing placeholder text remain literals. Physical table names are prohibited;
CTE names are resolved within their scope. Reference bindings and job dependencies
are generated from model entities. Extra packages belong in job/bundle libraries,
not the entity's Quality definition.

## Enforcement and uniqueness

All row expressions are checked against the complete prepared input before valid
and invalid rows are split and before SCD/merge staging. For example:

```sql
Id IS NULL OR COUNT(*) OVER (PARTITION BY Id) = 1
```

This preserves DQX's default NULL-distinct uniqueness: every non-NULL duplicate
is invalid, and unique/NULL rows pass this check. For composite keys, OR together
the key NULL guards. To treat NULLs as equal, omit the guards. Filtered uniqueness
uses a conditional SUM window and passes rows outside the filter explicitly.
No deduplication, representative-row selection or implicit row filtering occurs.

The original compiled expression must resolve to BOOLEAN, even for empty data.
The payload emits DQX `sql_expression` with `COALESCE((expression), FALSE)` so only
TRUE passes. Error rows enter `<target>_quarantine`; warnings remain valid. Empty
or all-invalid output preserves existing target data. The gate counts distinct
error rows once and fails strictly above the configured percentage after valid
target writes and metric persistence.

## Monitoring contract

Without `sql`, expressions evaluate the complete committed target; empty input
reports NO_DATA. With `sql`, the query must return exactly one row and two columns:

- `checked_rows`: a nonnegative, non-NULL integer fitting BIGINT.
- `measured_value`: a finite numeric value or NULL.

Wrong schemas, zero/multiple result rows, negative/NULL/overflow counts and
nonfinite measures are technical failures. Original expression type validation
always precedes the on-empty decision. `onEmpty: no_data` reports NO_DATA when
`checked_rows = 0` without evaluating the business condition; `evaluate` evaluates
normally. Aggregate `failed_rows` is NULL; the two fixed columns supply the other
metrics. Monitoring violations are results; technical errors fail the task.

The [fixture](../../tests/fixtures/quality/QualityProbe.json) models completeness,
freshness and row count with this contract. A
[second fixture](../../tests/fixtures/quality/QualityNativeProbe.json) uses windows
and a [model entity reference](../../tests/fixtures/quality/QualityReferenceProbe.json).
Reference keys are deduplicated before joining so reference duplicates cannot
multiply checked rows.

## Storage and jobs

Generated notebooks show nullable quarantine/metric DDL, SQL, native DQX calls,
counts, writes and gate decisions in named cells. Whole business records are not
automatically displayed. Quarantine columns omit target identity, NOT NULL and PK
constraints and add `__dm8_dq_audit`. Metrics remain in
`<catalog>.quality.dqx_metrics` with their existing schema. Parameters record the
fixed check fields. Run/attempt transaction identities make audit writes idempotent.
Target, quarantine and metrics remain separate Delta transactions.

Monitoring-only DML has no DQX initialization or quality library dependencies.
Mixed jobs use ALL_DONE and an attempt-specific committed-gate signal. Technical
failures, failed reference loads and failed all-invalid loads skip monitoring
quality evaluation; successful empty loads retain monitoring behavior. Repairs
cannot reuse earlier attempt signals. Schedules and ordinary load dependencies
remain unchanged. Quality tasks require classic compute; serverless is rejected.

## Verification and deployment

Use disposable copies for local generation and tests. Acceptance notebooks under
`tests/fixtures/quality` require explicit isolated `dm8_quality_test_*` catalogs and
classic compute. Generate and upload all matching notebooks, utilities, manifests
and YAMLs together while affected jobs are stopped. Deleted checks remove obsolete
generated assets/tasks; they do not delete historical audit data or tables.

No metadata or database migration is performed. MigrationFramework, existing live
schemas and audit history remain unchanged. The SQL source reader requires DBR
18.3 remote_query support; verify the actual runtime and source connectivity.
Never commit private workspace bindings or credentials.
