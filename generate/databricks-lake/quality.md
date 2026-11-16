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
resource definitions. `utils/QualityFramework.py` contains shared execution logic.

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
for a disposable solution running the matching Model/Generator feature branches.
They are not part of the public AdventureWorks model. `acceptance.py` executes
generated DDL, DML and Monitoring notebooks against a caller-provided isolated
`dm8_quality_test_*` catalog on classic compute. It never reads a live source.
Upload only the fixture artifacts, shared utilities and acceptance notebook; pass
`catalog_name`, `owner` and `workspace_root` explicitly. Do not commit real
workspace identifiers or credentials.

The public sample's SQL reader requires DBR 18.3 or later. Synthetic Quality
acceptance can run on classic DBR 16.4; that result does not validate the SQL reader.

The additional `merge_acceptance.py` fixture covers append, SCD1 merge and SCD2
history with the same rules. Its module docstring specifies the three variants
to generate from `QualityProbe.json` on the disposable solution.
