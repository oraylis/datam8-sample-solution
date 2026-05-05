# DataM8 Sample Solution Documentation

This documentation is organized by the job you are trying to do.

## Start Here

Read these pages in order when you are new to the repository:

1. [Getting Started](./getting-started.md)
2. [Quickstart Deployment](./quickstart.md)
3. [Template and Payload Development](./howto-template-and-payload-development.md)

## Maintainer Path

Use these pages when changing generator behavior:

- [Generator Contracts](./reference/generator-contracts.md)
- [Properties Reference](./reference/properties.md)
- [Output Structure](./reference/output-structure.md)
- [Target Overview](./reference/targets.md)

Target-specific architecture lives next to each active generator:

- [Databricks Architecture](../Generate/databricks/ARCHITECTURE.md)
- [Power BI Tabular Architecture](../Generate/powerbi-tabular/ARCHITECTURE.md)
- [Documentation Target Architecture](../Generate/docs/ARCHITECTURE.md)

## Operator Path

Use the [Quickstart Deployment](./quickstart.md) for Azure resources, Databricks
workspace setup, Key Vault secrets, and CI/CD configuration.

Use the repository root [`databricks.yml`](../databricks.yml) for Databricks Asset
Bundle settings and environment-specific deployment targets.
