# Configured Targets and Output Paths

The solution descriptor contains exactly three local generation targets.

| Target | Template source | Configured output root |
| --- | --- | --- |
| databricks | `generate/databricks-lake` | `output/databricks` |
| powerbi | `generate/powerbi-tabular` | `output/powerbi` |
| docs | `generate/docs` | `output/docs` |

Each target writes only inside its own output folder. The authored runtime
notebooks in `utils/` and the neutral bundle in `deployment/databricks/` survive
clean generation. Supply your own environment settings and follow the
[deployment guides](../quickstart.md) after reviewing generated artifacts.

## Databricks quality artifacts

Entity quality rules generate explicit DDL in the entity's `ddl` notebook,
enforcement steps in its `dml` notebook and a separate `quality` notebook for
monitoring. Native rule YAML and an audit manifest are under
`output/databricks/quality/<entity-id>/`. The readable notebooks show the DQX
calls, valid/invalid split, metrics and threshold decision. The shared
`utils/QualityFramework.py` contains technical validation and idempotent audit I/O.

The shared quality schema stores open definitions without a tool catalogue. This
target passes native function names and JSON arguments directly to DQX
0.16.0; there is no DataM8 function allow-list. Reference DataFrames and additional
PyPI dependencies come from the entity model. The self-contained
[native fixture](../../tests/fixtures/quality/QualityNativeProbe.json) demonstrates
per-column expansion, list membership, uniqueness, filters, warnings and foreign
keys without Python code per rule. Named entity references become table bindings
and dependencies on their load tasks when they run in the same job. References
outside that job must already exist. Bindings can be limited to monitoring or
enforcement. Editing, adding or removing model rules takes effect after clean
regeneration and deployment of notebooks, manifests and job resources together.

Monitoring-only entities initialize DQX only in their monitoring task. For mixed
entities monitoring uses `ALL_DONE` with an attempt-specific guard: after a failed
load it evaluates the target only if valid rows were committed before the quality
threshold raised. Technical failures and failed loads without committed valid rows
exit before DQX initialization. Successful empty loads retain their existing
monitoring behavior. Load failures still stop dependent entity loads.
