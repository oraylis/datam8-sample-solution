# Configured Targets and Output Paths

The solution descriptor contains exactly three generate-only targets.

| Target | Template source | Configured output root |
| --- | --- | --- |
| databricks | `Generate/databricks-lake` | `Output/databricks-lake/generated` |
| powerbi | `Generate/powerbi-tabular` | `Output/powerbi-tabular/generated` |
| docs | `Generate/docs` | `Output/docs` |

Lakeflow and all deployment/integration operations moved to the private
[Solutions repository](https://github.com/oraylis/datam8-solutions).
