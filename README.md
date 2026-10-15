# DataM8 Sample Solution

This repository supplies a v2 metadata model, Python payloads and Jinja templates
for Databricks, Power BI and generated model documentation.

Use **DataM8 app 2.0.0** to create and edit the model and generate output with its
bundled generator. Alternatively, use **DataM8 CLI 2.0.0** for validation and
generation from the command line. Both routes are covered in
[getting started](docs/getting-started.md).

- [Local getting started](docs/getting-started.md)
- [Documentation index](docs/index.md)
- [Template and payload development](docs/template-development.md)
- [Configured targets and output paths](docs/reference/targets.md)
- [Optional deployment preparation](docs/quickstart.md)
- [Central illustrated handbook](https://github.com/oraylis/datam8/blob/codex/documentation-v2/docs/user-guide/README.md)

The solution includes three targets: **databricks**, **powerbi** and **docs**.
Start on a complete working copy and keep secrets out of committed JSON and
generated output. Local model editing and docs generation need no cloud account.

## What the targets build

| Target | Result |
| --- | --- |
| [Databricks](Generate/databricks-lake/README.md) | A layered lakehouse with Raw, Stage, Core and Curated notebooks, table definitions and creation/load jobs |
| [Power BI](Generate/powerbi-tabular/README.md) | A consumer semantic model with tables, relationships, DAX measures and Databricks queries |
| [Documentation](Generate/docs/README.md) | A browsable model catalog, entity reference pages and a draw.io relationship diagram |

## Checks

```sh
node scripts/check-docs.mjs
```

Node 24 runs the documentation check without a backend. For real generation,
use the setup and file assertions in [getting started](docs/getting-started.md).
The existing parity script compares two generated output directories; use
`scripts/verify_generation_parity.ps1` when preserving target output intentionally.

The existing Azure pipeline references superseded tooling and environment settings;
it is not a supported copy-and-run v2 recipe. Its replacement is a separate
[follow-up](docs/documentation-handoff.md), not part of documentation generation.
