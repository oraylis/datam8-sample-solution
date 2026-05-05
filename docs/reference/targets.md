# Target Overview

Active generator targets are declared in
[`ORAYLISDatabricksSample.dm8s`](../../ORAYLISDatabricksSample.dm8s).

| Target | Source path | Output path | Architecture |
|---|---|---|---|
| `databricks` | `Generate/databricks` | `Output/databricks` | [Databricks](../../Generate/databricks/ARCHITECTURE.md) |
| `powerbi` | `Generate/powerbi-tabular` | `Output/powerbi-tabular` | [Power BI Tabular](../../Generate/powerbi-tabular/ARCHITECTURE.md) |
| `docs` | `Generate/docs` | `Output/docs` | [Documentation](../../Generate/docs/ARCHITECTURE.md) |

## Choosing Where to Document Changes

- Put beginner workflow documentation in `docs/`.
- Put shared generator contracts in `docs/reference/`.
- Put target-specific payload/template contracts in `Generate/<target>/ARCHITECTURE.md`.
- Put deployment and environment instructions in `docs/quickstart.md`.
