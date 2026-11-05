# Configured Targets and Output Paths

The solution descriptor contains exactly three generate-only targets.

| Target | Template source | Configured output root |
| --- | --- | --- |
| databricks | `generate/databricks-lake` | `output/databricks` |
| powerbi | `generate/powerbi-tabular` | `output/powerbi` |
| docs | `generate/docs` | `output/docs` |

Each target writes files locally. The sample includes no deployment runner,
environment bindings or live integration workflow. Review the
[deployment boundary](../quickstart.md) before using generated artifacts elsewhere.
