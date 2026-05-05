# Getting Started

This guide gives you the minimum repository context needed before editing
metadata, templates, or payload builders.

## Prerequisites

- Python `>=3.12,<3.14`
- `uv` for dependency management
- Access to the DataM8 Python package configured in [`pyproject.toml`](../pyproject.toml)
- Optional for deployment work: Databricks CLI and Azure access

Install dependencies:

```console
uv sync
```

## Repository Structure

- `ORAYLISDatabricksSample.dm8s`: solution file with base/model/plugin paths and active generator targets.
- `Base/`: shared metadata such as zones, data types, properties, and data sources.
- `Model/`: modeled entities, attributes, sources, relationships, and transformation scripts.
- `Generate/`: generator targets with Python payload builders and Jinja2 templates.
- `Output/`: generated artifacts checked in as examples or deployment input.
- `utils/` and `libraries/`: Databricks runtime helpers and package artifacts.
- `docs/`: user-facing documentation and reference material.

## Active Generator Targets

The solution file defines three active targets:

| Target | Source path | Output path | Purpose |
|---|---|---|---|
| `databricks` | `Generate/databricks` | `Output/databricks` | Databricks notebooks, schemas, clusters, and jobs |
| `powerbi` | `Generate/powerbi-tabular` | `Output/powerbi-tabular` | Power BI Tabular TMDL artifacts |
| `docs` | `Generate/docs` | `Output/docs` | Generated model documentation and diagrams |

## First Generation Run

CI uses the DataM8 CLI action `generate_template`. For a local run, use the same
solution file and the active target paths from `ORAYLISDatabricksSample.dm8s`.

Example shape:

```console
Dm8Data -a generate_template -s ORAYLISDatabricksSample.dm8s
```

If your local DataM8 version requires explicit paths, use the active Databricks target:

```console
Dm8Data -a generate_template -s ORAYLISDatabricksSample.dm8s -src ./Generate/databricks -dest ./Output -m ./Generate/databricks/__modules
```

After generation, inspect `Output/databricks`, `Output/powerbi-tabular`, or
`Output/docs` depending on the selected target.

## What to Read Next

- [Template and Payload Development](./howto-template-and-payload-development.md)
- [Generator Contracts](./reference/generator-contracts.md)
- [Target Overview](./reference/targets.md)
