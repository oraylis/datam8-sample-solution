<img src="./docs/assets/images/dm8_logo.png" width="300" alt="DataM8 Logo">

# ORAYLIS _DataM8_ Sample Solution for Azure Databricks

_DataM8_ is an exceptional open-source data automation tool available for free!

Its primary goal is to streamline the setup of data warehouses on different platforms,
catering to a wide range of users, from small to enterprise-scale data warehouses. Inspired by
ORAYLIS' best practices and driven by a passion for data engineering, _DataM8_ focuses on
elevating data platform quality while significantly minimizing repetitive tasks. With its
expandable solution, users can effortlessly automate data warehouse workflows on their preferred
target platform, making it a valuable asset for data engineers and organizations alike.

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

## Comprehensive Documentation for the Azure Databricks Sample Solution

This section provides a wealth of detailed information on the architecture, functionalities, and
varied features of the Azure Databricks sample solution. It is designed to be a vital resource for
both newcomers and seasoned users, offering clear guidance and insights on how to harness the full
potential of the _DataM8_ sample solution:

1. **Solution Structure:** _DataM8_ is structured to efficiently organize and manage your data
   warehouse project. For an in-depth understanding, explore this 📜[Solution Structure Guide].
2. **Quick Start Guide:** This guide covers the essentials for setting up Azure Databricks
   prerequisites, whether in the ORAYLIS IT-DEV environment or your own setup. Navigate through
   the setup process with this 📜[Quick Start Guide].
3. **Template Generation:** Discover templates for generating a sample Azure Databricks solution
   (databricks-lake), providing a practical starting point for your projects. Learn more with this
   📜[Template Generation Guide].

[Solution Structure Guide]: https://github.com/oraylis/automation/blob/main/docs/DataM8.md
[Quick Start Guide]: ./docs/quickstart.md
[Template Generation Guide]: ./Generate/databricks-lake/README.md

## Template Parity Check

When refactoring generator templates, use the parity script to ensure generated output stays
text-identical (with EOL and trailing EOF whitespace normalization).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_generation_parity.ps1 `
  -BaselineRoot .\Output\baseline `
  -CandidateRoot .\Output\candidate `
  -ReportPath .\Output\parity-report.json
```

The script returns exit code `1` when differences are found (unless `-AllowDifferences` is set).
