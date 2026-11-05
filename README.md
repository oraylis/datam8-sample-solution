# DataM8 Sample Solution

Learn metadata-driven generation with a small AdventureWorks customer, address
and order model. Open it in the DataM8 app or use the CLI to inspect and edit
metadata, then generate model documentation, Databricks notebooks or a Power BI
semantic model. The first exercise runs locally without a database or cloud account.

## Start with your task

| I want to… | Begin here | First result |
| --- | --- | --- |
| Learn visual modeling | [Open the sample in the app](docs/getting-started.md#use-the-app) | Change a Customer description and confirm it survives reload |
| Validate and generate from the command line | [Local CLI setup](docs/getting-started.md#use-the-cli) | Generate and inspect a fresh `output/docs/index.md` |
| Build and deploy my own solution | [Extend the sample](docs/build-your-own-solution.md), then [deploy](docs/quickstart.md) | Expose SourceSystem in Customer and prepare your own Databricks/Power BI environment |
| Change templates or target conventions | [Template development](docs/template-development.md) and [configured targets](docs/reference/targets.md) | Change one template and compare the generated output |
| Understand the example | [Model documentation target](generate/docs/README.md) and [property references](docs/model-properties.md) | Follow Customer through Stage, Core, Curated and Consumer |

**Recommended first result:** generate `docs` and open its index. Use a disposable
copy: autosave writes metadata, and generation can replace a target's output.
Install the [stable app or CLI](https://github.com/oraylis/datam8/blob/main/docs/installation.md)
for product use; the local project below pins a public CLI revision for reproducibility.

## Try the local CLI path

Clone or download the repository, copy the complete solution to an exercise
directory, and run these commands there with uv and a compatible Python:

```powershell
uv sync --frozen
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s
```

Open `output/docs/index.md`; it should contain Customer and links to entity pages
and a relationship diagram. The SQL Server metadata connector is bundled with
the pinned CLI and installed through its `sql` extra. No connector checkout,
download token or source connection is needed for this exercise.

## What is included

| Target | Source | Output |
| --- | --- | --- |
| databricks | `generate/databricks-lake` | `output/databricks` |
| powerbi | `generate/powerbi-tabular` | `output/powerbi` |
| docs | `generate/docs` | `output/docs` |

The model follows AdventureWorks customers, addresses and orders through Stage,
Core and Curated, including DimCustomer, DimDate and FactSalesOrder. Consumer
entities retain Customer, Date, Sales Order and Total Sales. The SQL example
uses the standard SalesLT.Customer table; no custom language-specific views are
required. Data endpoints and secret references are neutral placeholders.

A neutral Databricks bundle under `deployment/` and the [own-deployment guides](docs/quickstart.md)
cover the next steps. Supply your own identity, compute, catalog and source
connection. Credentials and live environment bindings are not included. Local
generation does not establish successful deployment, refresh or processing.

## Learn more and contribute

- [Sample documentation](docs/index.md)
- [Central illustrated handbook](https://github.com/oraylis/datam8/blob/main/docs/user-guide/README.md)
- [Local checks and review requirements](docs/integration-tests.md)
- [Source and credential policy](SECURITY.md)

Follow [repository instructions](AGENTS.md) and run the relevant local checks
during implementation. Propose changes through a feature PR; the
maintainer merges manually. Report product issues in
[DataM8](https://github.com/oraylis/datam8/issues), with no credentials or live
environment details.
