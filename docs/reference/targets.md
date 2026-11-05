# Configured Targets and Output Paths

The solution descriptor contains exactly three generate-only targets.

| Target | Template source | Configured output root |
| --- | --- | --- |
| databricks | `Generate/databricks-lake` | `Output/databricks-lake/generated` |
| powerbi | `Generate/powerbi-tabular` | `Output/powerbi-tabular/generated` |
| docs | `Generate/docs` | `Output/docs` |

Each target writes files locally. The sample includes no deployment runner,
environment bindings or live integration workflow. Review the
[deployment boundary](../quickstart.md) before using generated artifacts elsewhere.
