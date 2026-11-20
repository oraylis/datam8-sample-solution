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
monitoring. Native DQX rules and audit configuration are embedded directly in
the notebooks, alongside calls, valid/invalid split, metrics and the gate decision.
There are no Quality manifests or rule YAML files. The shared
`utils/QualityFramework.py` contains result validation and idempotent audit I/O.

The shared quality schema has fixed SQL fields. This solution's payloads and
templates resolve entity references and emit DQX 0.16.0 `sql_expression` rules
without changing the model expressions. SQL syntax is checked only by the runtime. There is no DataM8 check-type catalogue or free
native definition object. The [SQL fixture](../../tests/fixtures/quality/QualityNativeProbe.json)
uses combined required fields, list conditions, window uniqueness, warnings and
reference monitoring without Python implementations per check.

References use model entity IDs and become bound query relations and load-task
dependencies when their entities run in the same job. References outside that job
must already exist. Extra packages belong in job/bundle configuration. Editing,
adding or removing rules takes effect after clean regeneration and deployment of
notebooks, helpers and job resources together. Old rule formats are rejected;
there is no converter or migration.

NULL handling is explicit in model expressions. Runtime errors may be unobservable
on empty inputs. Arbitrary monitoring SQL runs with task permissions and is not
guaranteed read-only; use trusted models and least-privilege principals. See the
[Quality runtime reference](../../generate/databricks-lake/quality.md).

Monitoring-only entities initialize DQX only in their monitoring task. For mixed
entities monitoring uses `ALL_DONE` with an attempt-specific guard: after a failed
load it evaluates the target only if valid rows were committed before the quality
threshold raised. Technical failures and failed loads without committed valid rows
exit before DQX initialization. Successful empty loads retain their existing
monitoring behavior. Load failures still stop dependent entity loads.
