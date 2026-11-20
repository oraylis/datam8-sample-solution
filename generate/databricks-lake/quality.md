# SQL Quality Runtime Reference

The shared DataM8 schema is a fixed SQL contract: `id`, `execution`, `expression`,
optional `severity` (default `error`), `description`, monitoring-only `sql` and
`onEmpty` (`evaluate` by default, only with `sql`). `quality.maxFailureRatePct`
controls the entity gate; `quality.references` binds aliases to active entity IDs.
Unknown fields and older formats are rejected. There is no migration or converter.

## Literal SQL and native execution

This solution generates native `databricks-labs-dqx==0.16.0` `sql_expression` rules
in the notebooks. The model's `expression` is passed byte-for-byte unchanged as
`check.arguments.expression`: no COALESCE wrapper, parentheses, SQL parsing,
function substitution, clock binding, optimization or dialect translation.
`CURRENT_TIMESTAMP` and `TIMESTAMPDIFF` retain their native Databricks semantics.
Use the SQL dialect supported by the selected runtime. Model, CLI and frontend
validate the structure, not SQL syntax, resolution or Boolean types.

The DQX rule `name` is the DataM8 check ID. Severity selects native `error` or
`warn`; a description supplies `msg`. Without a description, DQX generates its own
message. There is no custom check-ID metadata or catalogue of check types.

NULL handling belongs to the model and the native engine. To fail a nullable
comparison explicitly, use `COALESCE(Amount >= 0, FALSE)`. For freshness with a
nullable measurement use `COALESCE(measured_value BETWEEN 0 AND 300, FALSE)`.
The generator never inserts that logic. Rules, SQL and run/audit configuration
appear directly in the DML and monitoring notebooks; no Quality manifests or
rule YAML files are generated or loaded.

## Monitoring bindings and result contract

Monitoring SQL is also unchanged except for `{target}` and declared
`{references.alias}` placeholders. A small scanner skips SQL strings, quoted
identifiers (including doubled quotes), [raw SQL literals](https://docs.databricks.com/aws/en/sql/language-manual/data-types/string-type)
and comments, then binds real placeholders through
`IDENTIFIER(:dm8_target)` and `IDENTIFIER(:dm8_ref_alias)` parameters. Table names
are resolved from the model and safely quoted. Unknown aliases are binding errors.
Only references actually used outside quotes/comments add job dependencies.
This is table binding, not a SQL parser or a SQL capability allow-list. Native
physical SQL table names are not blocked and are subject to runtime permissions.

Without `sql`, row monitoring evaluates the complete committed target; empty input
reports NO_DATA. An aggregate query must return exactly one row and exactly:

- `checked_rows`: a nonnegative, non-NULL integer fitting BIGINT.
- `measured_value`: a finite numeric value or NULL.

The technical helper validates this result's shape, types and values, not its SQL.
`onEmpty: no_data` reports NO_DATA when `checked_rows = 0` and skips the DQX
condition after result validation; `evaluate` executes the condition. Aggregate
`failed_rows` stays NULL. Monitoring violations become results; observable
technical errors or DQX skips fail the task.

The [basic fixture](../../tests/fixtures/quality/QualityProbe.json) expresses
completeness, freshness and row count directly in SQL. The
[window/reference fixture](../../tests/fixtures/quality/QualityNativeProbe.json)
uses a [model entity reference](../../tests/fixtures/quality/QualityReferenceProbe.json).
Its SQL explicitly deduplicates reference keys and defines NULL/filter semantics.

## Enforcement, audit and jobs

Enforcement runs on the full prepared input before splitting or SCD/merge staging.
For example, `Id IS NULL OR COUNT(*) OVER (PARTITION BY Id) = 1` marks every
non-NULL duplicate and preserves unique rows and all row copies. NULL guards,
composite keys and filtered conditional SUM windows belong to the expression.
The generator does not deduplicate or filter rule inputs.

Error rows enter quarantine; warnings remain in the valid stream. Empty and
all-invalid outputs preserve existing targets. The gate counts each erroneous
row once and fails strictly above its configured percentage, after valid target
writes and metric persistence. These remain separate Delta transactions.

Only entities with enforcement checks receive a nullable quarantine table with
`__dm8_dq_audit`, without target identity, NOT NULL or PK constraints. Every
configured entity receives central metric DDL. The existing metric and audit
schemas, rule-set hashes, run/attempt IDs and idempotent transaction identities
remain in use. Whole business records are not automatically displayed.

Monitoring-only DML has no Quality/DQX imports or library dependency. Mixed jobs
retain ALL_DONE and the attempt-specific committed-gate signal: technical failures,
failed all-invalid loads and failed reference loads skip monitoring evaluation;
successful empty loads retain their normal monitoring behavior. Repairs cannot
reuse an earlier attempt's signal. Cycle detection, schedules and ordinary job
orchestration are unchanged. Quality jobs require classic compute.

## Runtime and permission boundaries

SQL validity is determined by Databricks/DQX during execution. Generation can
succeed with invalid SQL. The framework rejects skipped checks when DQX exposes
skip results; on empty input certain invalid rules may not produce any error or
skip rows and cannot reliably be detected. NO_DATA is not proof of rule validity.
An aggregate `no_data` condition is intentionally not executed.

Monitoring SQL is **not guaranteed read-only**. Arbitrary model SQL executes with
the task principal's permissions, and side effects can occur before result-shape
validation fails. Use only trusted model configurations. Parameterized table
bindings protect those names; they do not sandbox the surrounding SQL.
Operators must constrain Unity Catalog and compute permissions: monitor principals
need SELECT on targets/references and metric-write permissions, not target/reference
write or schema-management permissions. DML needs its intended target/quarantine
writes; DDL requires separate creation/management rights. A shared principal with
broader rights retains those rights inside model SQL. The framework does not
change principals, grants or existing job orchestration.

## Verification and deployment

Run local tests and clean generation on disposable copies. Acceptance notebooks
under `tests/fixtures/quality` require an explicitly isolated `dm8_quality_test_*`
catalog and classic compute. Generate and upload the matching notebooks, functions
and technical helper together while affected jobs are stopped. Clean generation
removes old Quality manifests/YAMLs; keep the general solution manifest, job YAMLs
and bundle. Deleted checks do not remove historical audit data or existing tables.

Do not change MigrationFramework, migrate databases or reset live data for this
cleanup. Never commit private workspace bindings or credentials.
