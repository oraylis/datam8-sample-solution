# Databricks table migrations

The classic target uses `Output/databricks-lake/utils/MigrationFramework.py`.
All migration code is in that notebook; it needs no migration service, helper
package or log tables. Stop concurrent writers before calling it.

## Existing DDL notebooks

The four existing arguments remain supported:

```python
result = table_instance.migrate_schema(
    ddl=create_sql,
    schema=schema,
    refactored_columns=refactored_columns,
    new_partitions=partitions,
    target_metadata={
        "owner": owner,
        "table_tags": {"business_area": "sales"},
        "column_tags": {"Email": {"sensitive": "true"}},
    },
    fail_on_manual_migration=False,
)
```

`ddl` must be one explicit Delta `CREATE TABLE` statement. It defines the
physical schema, constraints, comments, layout and properties. `schema` must
agree on column names, order and types; DDL nullability takes precedence over
the older Spark reference schema. The legacy `new_partitions` argument supplies
the layout columns from that statement: clustering and physical partitioning
are distinguished internally.
SQL literals use Spark backslash escaping. The default setting
`spark.sql.parser.escapedStringLiterals=false` is checked before migration.

`refactored_columns` uses the existing shape:

```python
[{"name": "CustomerNumber", "refactorNames": ["CustomerNo", "CustomerID_old"]}]
```

Current names are matched first, then unambiguous historical names. Type changes
are compared after that mapping. Ambiguous mappings never merge or duplicate
source values. Historical aliases do not force a swap between two already
existing target names. Nested aliases use paths such as `Address.PostCode`.

`target_metadata` is optional. When supplied, its tag dictionaries are complete
target sets: omitted tags are removed. Owner is applied last. Without this
argument, existing accessible metadata is preserved. The generated DDL notebooks
pass their existing owner and tags through this argument.

## Strategies and results

The framework first attempts metadata changes. Where necessary it validates a
complete source projection and builds a candidate. It prefers a rewrite that
retains table history when the target supports it. Identity/generated columns
or other incompatible features can require archiving and replacement. Supported
metadata widening follows the [Databricks type-widening rules](https://learn.microsoft.com/en-us/azure/databricks/tables/features/type-widening),
including integral-to-double and sufficiently wide integral-to-decimal changes.
Runtime rejection is handled through the checked replacement path.
New protocol features are prepared on a candidate instead of being enabled on
the original: a later failure must not leave its protocol upgraded. Existing
features still allow metadata-only widening. Planning and execution use the
same snapshot, column mapping, data assessment and strategy selection.

Existing rows are transferred completely or the target is created empty. Invalid
casts, overflow, rounding, missing required values, conflicting historical names
and non-insertable `GENERATED ALWAYS` keys select the empty fallback. Defaults
do not implicitly backfill old rows. Protected sources are not automatically
copied when the framework cannot prove it reads all unmasked values.
That also applies when a row filter hides every source row. ISO date strings and
ISO wall-clock `TIMESTAMP_NTZ` strings can transfer when their round trip is
exact; ambiguous formats or an implicit instant timezone require manual work.
Protected tables still support reversible metadata operations such as comments,
tags and layout settings. These operations leave data files unchanged. Because
Databricks does not support time travel on tables with row filters or column
masks, their recovery reconciles metadata without attempting historical reads or
temporarily removing protection. Changes requiring a data copy use the protected
empty-target fallback.

## Decision matrix: metadata, automatic data transfer, or manual work

This matrix describes the current implementation, including its conservative
fallbacks. A column change alone does not determine the strategy: existing data,
active Delta features, constraints, incoming references and protection policies
also matter. A combination uses metadata operations only if the entire change
can follow that path. Otherwise the framework prepares the complete target on a
candidate table. An incomplete target is not reported as a successful migration;
technical failures and recovery limits are described below.

### Strategy names

| `strategy` | What the framework does | Data transfer | Original/archive |
| --- | --- | --- | --- |
| `NONE` | No schema or catalog changes are necessary. | None. | Existing table remains; `status=NOOP`. |
| `METADATA` | Executes native ALTER/COMMENT/tag/owner operations. Validation can still scan data. | No rewrite of existing data files. | Managed table registration remains; no archive. |
| `REWRITE` | Creates and fills a candidate, verifies carried values, then replaces the existing table from that candidate. | Complete automatic projection into the target schema. | Managed registration remains; the internal Delta reservoir ID can change. Candidate is removed after success; no archive. |
| `ARCHIVE_AND_COPY` | Creates and verifies a populated candidate, archives the original and activates the candidate under the original name. | Complete automatic projection into the target schema. | Original remains as an archive; target has a new registration. |
| `ARCHIVE_AND_CREATE_EMPTY` | Creates the correct empty target, archives the original and activates the empty target. | No partial copy. All source data remains in the archive. | `status=MANUAL_DATA_MIGRATION_REQUIRED`; operator must transfer the data. |

An automatic projection carries every source row, including duplicates, and the
values of the columns retained by the target. Explicitly dropped columns are
absent from the target by design. Metadata-only column removal does not purge
old data files or Delta history.

### Changes that can use metadata operations

These routes require a valid target definition, sufficient permissions and
runtime support. A newly required protocol feature overrides the metadata route:
the framework prepares it on a candidate so recovery cannot leave the original
with an irreversible protocol upgrade.

| Requested change | Metadata route and prerequisites | When that route is insufficient |
| --- | --- | --- |
| Table/column comment: add, change or remove | Native COMMENT operation; quotes, backslashes and Unicode are preserved. | Invalid SQL/permissions are technical errors. |
| Table/column tags: add, change or remove | Native tag operations. Supplied tag dictionaries describe complete target sets, including an empty set. | Governed-tag restrictions or missing permissions are technical errors. |
| Owner change | Native owner operation, applied after the other changes. | Missing rights are technical errors; rights must also permit verification/recovery after transfer. |
| Ordinary table properties | Native SET/UNSET operations. | New feature requirements or unfamiliar `delta.*` settings are handled conservatively through a candidate; invalid settings fail. |
| Add nullable column(s) | ADD COLUMNS; existing rows read `NULL`. | New protocol features, identity or generated expressions can require a candidate. |
| Add a NOT NULL column to an empty table | ADD COLUMNS followed by SET NOT NULL, if no other condition requires rebuilding. | On a populated table, a missing required value selects the empty/manual target. A DEFAULT is not an automatic backfill. |
| Drop column(s) | Effective column-mapping mode must be `name` or `id`; dependent constraints/layout must be reconcilable. | Otherwise automatic rewrite/rebuild is assessed. Incoming references can prevent in-place key changes. |
| Rename a column, including case-only rename | Exactly one source is assigned using current names and `refactorNames`; effective column mapping is `name` or `id`. Temporary names avoid rename collisions. | Ambiguity selects the empty/manual target; unavailable metadata rename uses the checked rewrite/rebuild path. |
| Reorder top-level columns | Native FIRST/AFTER operations; values remain attached to their named columns. | Other combined changes may require a rewrite/rebuild. |
| Drop NOT NULL | Native DROP NOT NULL. | Other combined changes may require a different strategy. |
| Set NOT NULL on an existing column | Existing target values satisfy the constraint; native SET NOT NULL succeeds. | Existing NULLs select the empty/manual target. |
| Add/change/remove DEFAULT | Native default operation when `allowColumnDefaults` is already active. Existing values stay unchanged; later inserts use the new default. | First activation of the feature requires a candidate. |
| Supported type widening | Target DDL requests `delta.enableTypeWidening=true`, the required feature is already active, and native ALTER supports the change. | Otherwise values are assessed for automatic data transfer. |
| VOID/NULL type to a concrete type | Native type alteration can be attempted without the widening flag. | A target type requiring a new feature still uses a candidate. |
| STRUCT field add/drop/rename or supported leaf widening | Recursive native ALTER operations, including paths inside ARRAY/MAP where supported. Nested drop/rename requires column-mapping mode `name`/`id` in target properties. | Unsupported native operations or other nested transformations use a validated projection/rebuild. See the field-order limitation below. |
| Add/change/remove PK, FK, UNIQUE or CHECK | Existing rows satisfy the framework's target checks; affected constraints can be dropped/re-added without breaking incoming references. | Violations select the empty/manual target. First activation of CHECK support can require a candidate. |
| Add/change/remove liquid clustering | Native CLUSTER BY/NONE when clustering support is already active and the table is not physically partitioned. | First activation or a physical partition-layout transition requires a candidate. Changing clustering metadata does not run OPTIMIZE. |
| Change string collation | Native ALTER COLUMN when the collation feature is already active and the runtime accepts it. | First activation uses a candidate. Comparisons verify binary string values so case-insensitive equality cannot conceal changes. |
| Existing row filters or column masks with reversible metadata changes | Comments, properties, clustering settings, top-level order, defaults and nullability can retain the protection; owner/tags are reconciled as catalog metadata. | Schema add/drop/rename, type/collation changes and other operations outside the protected metadata allowlist select the protected empty-target route. Target policy bindings must remain valid. |

The implemented widening families are:

| Source | Recognized widening targets |
| --- | --- |
| TINYINT | SMALLINT, INT, BIGINT, DOUBLE; DECIMAL with at least 10 integer digits. |
| SMALLINT | INT, BIGINT, DOUBLE; DECIMAL with at least 10 integer digits. |
| INT | BIGINT, DOUBLE; DECIMAL with at least 10 integer digits. |
| BIGINT | DECIMAL with at least 20 integer digits. BIGINT to DOUBLE is assessed as a data conversion. |
| FLOAT | DOUBLE. |
| DECIMAL(p,s) | Target scale is at least `s` and target integer capacity is at least `p-s`. |
| DATE | TIMESTAMP_NTZ, subject to the feature prerequisite above. |

For nested widening, container nullability and the relevant field structure
must also match. Pure reordering of STRUCT fields has no dedicated metadata
step in the current planner. Do not rely on it as an automatic metadata case:
without another change forcing a rewrite, target verification can reject it and
restore the original. Top-level column reordering is supported.

Omitting a property is not a request to downgrade the Delta protocol. The
framework preserves these existing engine settings when omitted:
`delta.columnMapping.mode`, `delta.enableTypeWidening`,
`delta.enableDeletionVectors`, `delta.enableRowTracking`,
`delta.checkpointPolicy` and `delta.parquet.format.version`. Metadata widening
and nested rename/drop eligibility still use the target declarations described
above; an omitted prerequisite can therefore select the conservative data path.

### Changes that need automatic data migration

This path is available only when the complete target projection is valid and
lossless for the carried values. No invalid row is silently skipped. The
framework checks invalid casts, additional NULLs, round-trip conversion losses,
required values and target constraints before activation. Candidate values are
also compared in both directions with duplicate-preserving comparisons.

| Requested change | Automatic processing | Manual fallback condition |
| --- | --- | --- |
| Type conversion outside supported metadata widening | Casts every carried value and proves that conversion does not lose information. Examples include exact numeric narrowing and valid string-to-number conversion. | Invalid values, overflow, rounding, changed round-trip values or newly introduced NULLs. |
| String to DATE / TIMESTAMP_NTZ | Accepts strict ISO dates or ISO wall-clock NTZ timestamps when casting and round-trip checks succeed. | Ambiguous formats, invalid values, excess precision or an implicit timezone interpretation. Non-NULL strings to TIMESTAMP/LTZ require manual interpretation in the current implementation. |
| Nested STRUCT/ARRAY/MAP transformation | Builds a recursive projection; preserves NULL containers and checks leaf conversions, required values and map-key uniqueness. | Leaf conversion loss, missing required nested values, NULL map keys or collisions after key conversion. |
| Physical partitioning change | Creates the desired layout and transfers all intended rows. | Data/protection rules prevent a complete verified copy. Liquid clustering to physical partitioning uses `ARCHIVE_AND_COPY`. |
| New Delta protocol feature | Enables it on a candidate and transfers data while leaving the original protocol intact. | Data/protection rules prevent the copy, or the requested feature/definition is invalid. The latter is a technical failure. |
| Add a new identity column | Lets the target generate the new identity while copying existing columns/keys unchanged. | Any other target rule prevents a complete copy. |
| Preserve existing BY DEFAULT identity values during rebuild | Inserts the existing values explicitly and synchronizes the target identity sequence. | Values cannot satisfy the target definition. |
| Existing GENERATED ALWAYS identity during a required rebuild | No automatic explicit insertion of the existing ALWAYS values. Metadata-only changes to an otherwise unchanged identity remain possible. | Selects empty/manual when existing ALWAYS values would have to be carried into an ALWAYS target. |
| Add/change a generated expression | Lets the target compute the expression; ordinary carried columns are copied and verified. | Expression results violate NOT NULL/constraints or cannot be produced correctly. Invalid expression syntax is a technical failure. |
| Remove/change identity or generated-column definitions | Uses a candidate because ALTER cannot reconcile the full definition. | Applies the identity/constraint/data rules above. |

The choice between automatic strategies is explicit:

- `REWRITE` is preferred when there are no new protocol features, incoming FKs,
  source/target identity or generated columns, target protection clauses, or a
  liquid-clustering-to-partitioning transition.
- Otherwise a fully copyable target uses `ARCHIVE_AND_COPY`.
- A supported-operation rejection during rewrite can fall back to
  `ARCHIVE_AND_COPY` only after checking that the original did not change. The
  actual transition is included in `fallbacks`.

Thus **an archive does not by itself mean manual data migration**. With
`ARCHIVE_AND_COPY`, the new table is already populated. Only
`manual_migration_required=True` says that manual data transfer remains.

### Cases that leave an empty target for manual data migration

| Reason / typical case | Framework outcome | What the operator must decide or do |
| --- | --- | --- |
| `AMBIGUOUS_RENAME`: multiple aliases exist, one source serves multiple targets, or current name and an unassigned historical column coexist | Correct empty target plus original archive. | Decide which source values belong to each target column. The framework never merges competing values. |
| No matching source for a new required column on populated data | Correct empty target plus archive. | Define the missing values or an explicit backfill rule. |
| `INVALID_DATA`, `UNSUPPORTED_CONVERSION`, `DATA_TRANSFER_FAILED` or `DATA_CONSTRAINT_FAILURE` | Discards a failed copy candidate; activates a fresh empty target. | Correct/transform the offending values or supply an explicitly agreed conversion. |
| `AMBIGUOUS_TIME_CONVERSION` | Correct empty target plus archive. | Specify format, timezone and precision handling. |
| PK/UNIQUE duplicates, required NULLs, missing FK references or CHECK violations | Correct empty target plus archive. The framework checks informational keys too; CHECK must evaluate TRUE, so NULL does not pass its precheck. | Resolve duplicates, missing references, required values or the business constraint before loading. |
| Map-key conversion creates duplicates/NULL keys | Correct empty target plus archive. | Choose an explicit key mapping or collision-resolution rule. |
| `IDENTITY_VALUES_NOT_INSERTABLE` | Correct empty target plus archive. | Choose a supported identity/key migration and update dependent references as needed; the framework does not silently regenerate existing keys. |
| `NO_INSERTABLE_COLUMNS` on a nonempty source | Correct empty target plus archive. | Define how source rows should be represented when no target column accepts a carried value. |
| `PROTECTED_SOURCE`: a rebuild is required on a table with row filters/masks | Correct protected empty target plus protected archive, provided the target protection definition is valid. Even zero visible rows are not proof of an empty source. | Arrange an authorized transfer of every intended unmasked source value while preserving the protection requirements. The framework does not disable policies to obtain data. |

Current-name matching takes priority over historical aliases. One historical
match is a rename; no match is an add, subject to required-value checks. Aliases
do not force a swap when both current target names already exist. Ambiguity is
never resolved by picking the first alias.

For `MANUAL_DATA_MIGRATION_REQUIRED`, the operational sequence is:

1. Read `archive_table`, `reasons`, `changes` and any `manual_actions` from the
   returned dictionary or exception's `result`. The target already exists and
   is empty; retain the archive.
2. Agree the mapping, conversion, missing-value, key and protection decisions
   identified above. Prepare the explicit INSERT/SELECT or other supported
   loading process for that target. The framework supplies no business-specific
   cleansing/backfill SQL.
3. Load and verify all intended rows, duplicates, carried keys and constraints.
   Keep writers coordinated until the migration is verified.
4. If `manual_actions` contains `REPOINT_FOREIGN_KEY`, explicitly move those
   dependent FKs from the archive to the populated target and verify references.
5. Remove the archive only after the transfer and dependent-object checks have
   succeeded. The framework never deletes a production archive automatically.

Calling the same DDL again against the empty target can return `NOOP`: it checks
the target's current schema, not whether the previous archive has been loaded.
It does not resume copying from that archive. `fail_on_manual_migration=False`
is the default; `True` raises only after the empty target and archive are ready.

### Manual follow-up versus technical failure

Incoming FKs are a separate kind of manual follow-up. A successful
`ARCHIVE_AND_COPY` can already contain every row while dependent FKs still point
to the original registration in the archive. `manual_actions` identifies them;
`manual_migration_required` describes data transfer and can remain `False`.

Some situations cannot safely produce the target and archive at all. These are
technical failures, not successful empty-target migrations:

| Situation | Behavior / required correction |
| --- | --- |
| Invalid DDL, schema/DDL disagreement, duplicate target names or contradictory layout arguments | Preflight failure before changes; correct the input. |
| Missing permissions, invalid owner/tags/properties, unsupported target clauses or invalid policy bindings | Raises `MigrationFailed`; original is retained or compensation is attempted if execution started. Correct the definition or permissions. |
| `ARCHIVE_CONSTRAINT_NAME_CONFLICT` | Original and target cannot coexist with identical schema-wide PK/FK/UNIQUE names. Fails before mutation; choose distinct target key names. Original archive constraints are not renamed. |
| Pipeline-managed source, unsupported non-Delta source, external-table rebuild without independent storage, or changing external storage location | Rejected; use the owning pipeline or an explicit storage migration outside this implementation. |
| Source identity/version changes during planning | Rejects the stale assessment; coordinate writers and replan. |
| Unexpected object identity, lost completion certainty or failed compensation | Retains unconfirmed objects and reports `RECOVERY_REQUIRED` or `recovery` details. Inspect actual registrations/versions before a manual recovery; do not blindly repeat or delete objects. |

Technical errors are raised regardless of `fail_on_manual_migration`. Databricks
has no transaction spanning all these DDL steps: rollback means compensating
restoration, not an atomic multi-statement SQL transaction.

The read-only `plan_schema_migration(...)` is the way to inspect the proposed
`strategy`, `column_mapping`, `feature_changes`, `reasons` and SQL before
execution. After execution, the returned `strategy` and completed `changes`
describe what actually happened, including a runtime fallback.

## Result contract and recovery

The result is a JSON-serializable dictionary, also printed and available as
`table_instance.last_migration_result`. It contains:

- `status`: `NOOP`, `MIGRATED`, `MANUAL_DATA_MIGRATION_REQUIRED`, or `FAILED`.
- `table`, `strategy`, and a readable `message`.
- `changes`: completed actions, including their SQL when applicable.
- `manual_migration_required`, `archive_table`, and `reasons`.
- `source_id` and, after success, `target_id`: the observed catalog registrations.

A manual fallback succeeds by default. `fail_on_manual_migration=True` raises
`ManualDataMigrationRequired` **after** creating the empty target and retaining
the archive. The exception's `result` contains the same information. It does not
undo the successful target creation. Technical failures always raise
`MigrationFailed`, also with a `result` attribute.

`table_instance.plan_schema_migration(...)` accepts the same schema arguments
and optional target metadata. It returns a read-only SQL assessment. Execution
revalidates the source and reconciles target metadata after data operations.

Databricks does not provide a transaction spanning these DDL statements.
Recovery uses the original table identity/version and the in-memory snapshot of
catalog metadata. Lost responses are reconciled against actual object state.
For managed Unity Catalog tables, identity means the stable catalog registration
and storage directory. `CREATE OR REPLACE` can retain that registration while
changing the internal Delta reservoir ID. Delta history and catalog metadata
therefore need separate recovery checks.
Unknown objects are retained for inspection instead of being blindly deleted.
A process crash can require manual recovery; no journal tables or hidden status
properties are created. `NOOP` describes the current call, not historical manual
migration work. Archives are never automatically deleted by the framework.
If a rebuild leaves incoming foreign keys attached to the archive, the result
includes explicit `manual_actions` naming the dependent tables and constraints.

Unity Catalog key names are unique within a schema. When archiving is required,
an original and its new target cannot share a PK/FK/UNIQUE constraint name. The
framework reports `ARCHIVE_CONSTRAINT_NAME_CONFLICT` before changing the table;
choose distinct names in the target definition. It preserves the original
archive's constraints and installs the exact requested names on the target.
CHECK names are scoped to each table and do not have this restriction.

Data verification uses native typed `EXCEPT ALL` in both directions. Maps are
converted recursively to sorted entry arrays; scalar values retain timestamp
precision. Recovery checks object identities before deletion and verifies data,
catalog metadata, Delta features and protocol before reporting restoration.
Collated strings are compared using binary collation so value differences cannot
be hidden by case-insensitive equality. Comments and property values are read
from native metadata rather than the escaped literals in `SHOW CREATE TABLE`.

## Real-table Dev acceptance

The Dev-only `Migration_Framework_Tests` job runs
`utils/Test_MigrationFramework.py` using the configured run service principal.
It selects a populated existing sample table in `dm8_sample_dev_lake.stage`,
checks incoming references and protections, takes a verified independent deep
clone and snapshots catalog metadata. Each scenario calls the real
`Table.migrate_schema`, then restores and checks the original identity, complete
data including duplicates, schema and catalog metadata before the next case.

Special fixtures may temporarily park the original when a test needs to enable
additional protocol features or create an identity definition. The tested
table stays at the selected sample's real name; the original registration is
restored afterwards. Failure to restore aborts the suite and retains the backup.
Delta history naturally contains test/restore commits.
The internal `delta.columnMapping.maxColumnId` high-watermark can also advance;
Delta `RESTORE` does not rewind it. Reports expose that change as
`engine_state_changes`. Restoration verifies all other raw Delta properties,
the managed registration, data, schema, protocol and catalog metadata. An
identical internal Delta history or column-ID counter is not promised.
An absent table comment can also be represented as an empty string instead of
`null` by native APIs; both mean that the table has no comment.
The small selected table is also compared by a separate Python row-multiset
oracle, including duplicates and microseconds. Target values are checked against
a captured source projection independently of the production planner. Failed
assertions fail the Databricks task after cleanup; runtime limitations must have
an explicit classification and never count as successful migrations.

```powershell
uv sync --frozen
uv run python scripts/install_plugins.py --repository PATH_TO_DATAM8_PLUGINS
uv run python scripts/check_generation.py --target databricks
# From Output/databricks-lake:
databricks bundle validate --target dev --profile PROFILE
databricks bundle deploy --target dev --profile PROFILE --auto-approve
# From the repository root:
uv run python scripts/run_migration_tests.py --profile PROFILE
```

Use `--scenarios noop,rename_aliases` to run selected names or comma-separated
glob patterns. Use `--run-id ID` to collect an existing run without resubmitting
it. Results are notebook output and local JSON files under
`Output/e2e-test-reports`; they are not tables. A scenario passes only when both
its migration assertions and its restoration checks pass. Unsupported runtime
features and failed tests must be reported as such, never counted as passed.

`--permission-probe` runs a separate preflight call as the authenticated caller
to verify an actual denied schema permission. `--cleanup-backup FQN=registration-UUID` can remove
an explicitly named earlier test backup after a successful run, after checking
its recorded registration, clone provenance and complete data equality. Failed runs retain their backups.

For interrupted test cleanup, `--recover-baseline PATH_TO_JSON` invokes the
Dev-only recovery notebook. It requires an explicitly captured baseline,
checks the original catalog registration and independent deep-clone provenance,
compares the historical source data with the clone, restores the recorded
version and catalog metadata, and verifies the complete result. It retains the
backup. The recovery job uses serverless compute; migration acceptance tests use
the configured classic runtime. Never resume a stopped suite until restoration
has been verified.
