<img src="./docs/assets/images/dm8_logo.png" width="300" alt="DataM8 Logo">

# ORAYLIS _DataM8_ Sample Solution for Azure Databricks

_DataM8_ is an open-source data automation tool for building metadata-driven data platforms.
This sample solution demonstrates end-to-end generation for:
- Databricks Lake assets
- Power BI Tabular (TMDL) assets
- model documentation output

> [!IMPORTANT]
> The main branch may contain active development, which could contain a broken solution.
> Always use [releases] or their respective [version tags] or commit hashes directly when
> referencing the schema.

[releases]: https://github.com/oraylis/datam8-sample-solution/releases
[version tags]: https://github.com/oraylis/datam8-sample-solution/tags

## Contributors

This sample solution for _DataM8_ is made possible with contributions from the following
individuals:

- Michael Kuhlen (ORAYLIS GmbH)
- Lasse Jenzen (ORAYLIS GmbH)
- Jan Degenhard (ORAYLIS GmbH)
- Markus Riehle (ORAYLIS GmbH)
- Marco Wotruba (ORAYLIS GmbH)

## Documentation

1. **Solution Structure:** _DataM8_ is structured to efficiently organize and manage your data
   warehouse project. For an in-depth understanding, see [Solution Structure Guide].
2. **Quick Start Guide:** Covers setup prerequisites for Databricks and related infrastructure.
   See [Quick Start Guide].
3. **Template Generation:** Overview for generated Databricks assets. See
   [Template Generation Guide].
4. **Template Development How-To:** Architecture and implementation guide for creating/extending
   generator targets, including property-driven behavior by target. See
   [Template Development How-To].
5. **Target Architectures:** Target-specific payload contracts, behavior, and extension guidance:
   [Databricks], [Power BI], [Docs].

[Solution Structure Guide]: https://github.com/oraylis/automation/blob/main/docs/DataM8.md
[Quick Start Guide]: ./docs/quickstart.md
[Template Generation Guide]: ./Generate/databricks-lake/README.md
[Template Development How-To]: ./docs/template-development-howto.md
[Databricks]: ./Generate/databricks-lake/ARCHITECTURE.md
[Power BI]: ./Generate/powerbi-tabular/ARCHITECTURE.md
[Docs]: ./Generate/docs/ARCHITECTURE.md
