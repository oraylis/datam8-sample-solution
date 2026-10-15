# Configured Targets and Output Paths

The [solution descriptor](../../ORAYLISDatabricksSample.dm8s) defines three targets.
Names select CLI targets; template directory names and generated subdirectories
are separate concepts.

| Target | Template source | Configured output root | What you can build | Architecture |
| --- | --- | --- | --- | --- |
| databricks | `Generate/databricks-lake` | `Output/databricks-lake/generated` | [Layered lakehouse with notebooks and jobs](../../Generate/databricks-lake/README.md) | [Implementation](../../Generate/databricks-lake/ARCHITECTURE.md) |
| powerbi | `Generate/powerbi-tabular` | `Output/powerbi-tabular/generated` | [Semantic model with tables, relationships and measures](../../Generate/powerbi-tabular/README.md) | [Implementation](../../Generate/powerbi-tabular/ARCHITECTURE.md) |
| docs | `Generate/docs` | `Output/docs` | [Model catalog, entity pages and relationship diagram](../../Generate/docs/README.md) | [Implementation](../../Generate/docs/ARCHITECTURE.md) |

Payload `output_path` is resolved beneath that root. Inspect the payload and real
output before assuming where a deployable notebook, bundle or TMDL file is located.
Only docs generation and validation were checked for this baseline in this update.
Databricks/Power BI generation and deployment require their own acceptance.

Target property interpretation belongs in each architecture document. Field
constraints belong in schemas; CLI/API behavior belongs in the backend.
