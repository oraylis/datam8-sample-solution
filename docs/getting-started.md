# Getting Started with DataM8 2.0.0

Choose how you want to work with the sample:

- **DataM8 app 2.0.0:** create and edit model entities, then generate output in the
  application. The app includes the generator and its runtime.
- **DataM8 CLI 2.0.0:** edit the model and templates in your preferred editor, then
  validate and generate from the command line.

## Get the sample

[Download the sample as a ZIP](https://github.com/oraylis/datam8-sample-solution/archive/refs/heads/main.zip)
and extract it, or clone the repository:

```sh
git clone https://github.com/oraylis/datam8-sample-solution.git datam8-sample
cd datam8-sample
```

Use a working copy for your changes. Keep Base, Model, Plugins, Generate and the
supporting configuration alongside `ORAYLISDatabricksSample.dm8s`. Copy the whole
solution when creating another exercise directory. Autosave writes your edits to
disk, and generation can replace files in a target output directory.

## Option 1: Use the DataM8 app

Install **DataM8 app 2.0.0** from the
[desktop release](https://github.com/oraylis/datam8-frontend/releases/tag/v2.0.0).
The app bundles generator functionality; you can work with the model and generate
output without installing Python or the CLI separately.

1. Launch DataM8 and choose **Open**.
2. Choose **Open Solution...** and select `ORAYLISDatabricksSample.dm8s` in your
   working copy.
3. Explore Base and Model. Create entities or edit existing ones; for a first
   change, edit the Stage Customer description and wait for autosave to finish.
4. Reload the solution and confirm that your change was saved.
5. Open **Toggle generator**, select **docs**, and choose **Generate**.
6. Open `Output/docs/index.md` and inspect the generated model documentation.

Follow the [illustrated user guide](https://github.com/oraylis/datam8/blob/codex/documentation-v2/docs/user-guide/README.md)
for the model editors, relationships, sources and generation workflow.

## Option 2: Use the DataM8 CLI

Use Python 3.13 or newer and uv. This sample pins the verified CLI 2.1.0
source revision and model dependency in its project and lockfile.
From the local sample checkout:

```powershell
uv sync --frozen
uv run python scripts/install_plugins.py
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s
```

The CLI operates directly on the persisted local solution. Installed plugins
remain local dependencies. See [integration tests](integration-tests.md) for
exact revisions, checksums, target selection and deployment commands.

Check the exit codes, then open `Output/docs/index.md`. It should contain Customer
and links to entity pages and the relationship diagram. Edit the model or templates
in your editor, then validate and generate again to inspect your changes.

## Inspect the generated output

Both routes use the targets configured in `ORAYLISDatabricksSample.dm8s` and write
files beneath their configured output roots. Start with **docs**; it works with
the local metadata and does not require a database connection or cloud account.
See [configured targets](reference/targets.md) for Databricks and Power BI output
paths. Deployment is a separate step after generation.

## Next steps

Read [targets](reference/targets.md), [template development](template-development.md)
and, only when needed, [deployment preparation](quickstart.md).
