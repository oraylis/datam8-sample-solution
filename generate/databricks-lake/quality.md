# Batch Quality Runtime Reference

Quality metadata belongs to the pinned DataM8 Model; validation belongs to the
Generator. This target translates it directly into native DQX checks without an
ODCS dependency. The runtime dependency is `databricks-labs-dqx==0.16.0` on
**classic compute**. Quality-enabled jobs reject serverless configuration.

## Artifacts and execution

Each entity with checks emits `quality/<entity ID>/manifest.json` plus native
`enforcement.yaml`, `monitoring_rows.yaml` and `monitoring_summary.yaml`. The
manifest retains source requirements, target mapping and a deterministic rule
hash. Bundle synchronization includes these runtime assets; they are not bundle
resource definitions. The notebooks expose the complete execution flow in named Markdown/code cells.
DDL contains the full nullable quarantine and central-metrics SQL. DML shows native
DQX execution, error/warning routing, distinct error-row counts and the gate after
the target write. Monitoring has its own template with a readable SQL aggregate,
DQX calls, status calculation and a compact result table.

`utils/QualityFramework.py` provides only manifest loading, execution context,
input/schema validation, metric formatting and idempotent audit writers. The old
`ensure_tables`, `enforce`, `monitor` and `finish_enforcement` entry points have
been removed. Regenerate and deploy notebooks and utilities together; do not mix
old generated notebooks with the new helper. Existing table names, metric schema,
rule hashes and Delta transaction identities are preserved.

Enforcement runs on prepared input before SCD/merge staging. Error rows enter
`<target>_quarantine`; warning-only rows remain valid. The target receives only
original input columns. Quarantine is persisted before target writes, followed by
rule metrics. A configured failure percentage stops the DML task after valid
rows have been written, only when the distinct error-row percentage is strictly
greater than the threshold. No configured threshold means no quality gate.
Empty valid input skips target writes, including overwrite.

Monitoring has a separate dependent notebook task and reads the entire target.
Not Null, numeric Range and SQL Expression run on records; Completeness,
Freshness and Row Count use a common aggregate input. SQL TRUE passes and
FALSE/NULL fails. Completeness counts non-NULL values. Freshness evaluates the
latest timestamp, rejecting future timestamps. Empty record input and empty
Completeness yield `NO_DATA`; Freshness fails and Row Count evaluates zero.
Monitoring violations do not fail the task; technical execution errors do.
The runtime resolves SQL expressions and referenced columns against the input
schema before invoking DQX, and requires Boolean SQL results. Invalid syntax,
missing columns and non-Boolean expressions fail even on empty input; they cannot
be silently reported as skipped checks or `NO_DATA` metrics.

## Storage and recovery

DDL initializes nullable quarantine columns without target identity/NOT NULL
constraints, plus a JSON audit column containing rule violations and run, attempt,
time and version information. Metrics are stored centrally in
`<catalog>.quality.dqx_metrics`, one row per rule and execution attempt.

The executing identity needs access to target tables and permission to create the
quality schema, create/alter/write quarantine and metrics tables, and read all
monitoring input. Retention and grants are operator-managed. No automatic cleanup
is performed. Reserve `__dm8_dq_*`, `_errors`, `_warnings` and `_dq_info`.

Audit appends use Delta transaction identities for idempotence within the same
run/attempt. Quality DML has zero automatic retries. These writes and the target
write are separate transactions: a failed target write can leave quarantine, and
a failed metrics write can follow a committed target. A new run follows the
existing append/overwrite/merge semantics; this is not a cross-table transaction
or an exactly-once recovery system.

## Acceptance fixtures

The synthetic entity and function in `tests/fixtures/quality` are opt-in fixtures
for a disposable solution. Run `uv sync --frozen` to use the locked CLI revision
and its matching Model schema, including quality validation.
They are not part of the public AdventureWorks model. `acceptance.py` executes
generated DDL, DML and Monitoring notebooks against a caller-provided isolated
`dm8_quality_test_*` catalog on classic compute. It never reads a live source.
Generate the monitoring-only variants QualityMonitorProbe (9005, all checks),
QualityRowsProbe (9006, first three checks) and QualitySummaryProbe (9007, last
three checks), with all their checks set to monitoring. Keep overwrite mode and
place `QualityProbe.py` beside the entity JSON files: transformation source paths
are relative to that directory, not an implicit entity subdirectory. Acceptance executes these real generated notebooks, including
invalid native YAML in a disposable workspace, and restores those files afterward.
Upload only the fixture artifacts, shared utilities and acceptance notebook; pass
`catalog_name`, `owner` and `workspace_root` explicitly. Do not commit real
workspace identifiers or credentials.

The public sample's SQL reader requires `remote_query` support (DBR 18.3).
Current Runtime 18 LTS is selected with `18.x-scala2.13`; check the actual runtime
and execute a bounded source query rather than looking only for an explicit
`18.3` key in the versions API. Synthetic Quality acceptance can run on classic
DBR 16.4; that result does not validate the SQL reader.

The additional `merge_acceptance.py` fixture covers append, SCD1 merge and SCD2
history with the same rules. Its module docstring specifies the three variants
to generate from `QualityProbe.json` on the disposable solution.
