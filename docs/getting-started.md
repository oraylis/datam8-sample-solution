# Get Started with the Public Sample

Choose how you want to work with the sample:

- **DataM8 app:** create and edit model entities, then generate output in the
  application. The app includes the generator and its runtime.
- **DataM8 CLI:** edit the model and templates in your preferred editor, then
  validate and generate from the command line.

## Get the sample

[Download the sample as a ZIP](https://github.com/oraylis/datam8-sample-solution/archive/refs/heads/main.zip)
and extract it, or clone the repository:

```sh
git clone https://github.com/oraylis/datam8-sample-solution.git datam8-sample
cd datam8-sample
```

Use a working copy for your changes. Keep `base`, `model`, `plugins`, `generate`, `utils`, `deployment` and the
supporting configuration alongside `ORAYLISDatabricksSample.dm8s`. Copy the whole
solution when creating another exercise directory. Autosave writes your edits to
disk, and generation can replace files in a target output directory.

## Use the app

Install the app from the
[current stable desktop release](https://github.com/oraylis/datam8-frontend/releases/latest),
following its [installation and verification guide](https://github.com/oraylis/datam8-frontend/blob/main/docs/desktop-installation.md).
The app bundles generator functionality; you can work with the model and generate
output without installing Python or the CLI separately.

1. Launch DataM8 and choose **Open**.
2. Choose **Open Solution...** and select `ORAYLISDatabricksSample.dm8s` in your
   working copy.
3. Explore Base and Model. Create entities or edit existing ones; for a first
   change, edit the Stage Customer description and wait for autosave to finish.
4. Reload the solution and confirm that your change was saved.
5. Open **Toggle generator**, select **docs**, and choose **Generate**.
6. Open `output/docs/index.md` and inspect the generated model documentation.

Follow the [illustrated user guide](https://github.com/oraylis/datam8/blob/main/docs/user-guide/README.md)
for the model editors, relationships, sources and generation workflow.

## Use the CLI

Use uv and a Python version supported by [the project](../pyproject.toml). The
lockfile pins a public CLI revision and its SQL extra for `builtin:SQLServer`.
The app has its own bundled runtime; consult its release compatibility notes.
From the local sample checkout:

```powershell
uv sync --frozen
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s
```

The CLI operates directly on the persisted local solution. No separately
installed solution connector or repository-access token is required. See
[local checks](integration-tests.md) for contributor verification. Source import and preview need your own source settings; local
metadata validation and generation do not need a source connection.

Check the exit codes, then open `output/docs/index.md`. It should contain Customer
and links to entity pages and the relationship diagram. Edit the model or templates
in your editor, then validate and generate again to inspect your changes.

## Inspect the generated output

Both routes use the targets configured in `ORAYLISDatabricksSample.dm8s` and write
files beneath their configured output roots. Start with **docs**; it works with
the local metadata and does not require a database connection or cloud account.
See [configured targets](reference/targets.md) for Databricks and Power BI output
paths. Deployment is a separate step after generation.

## Next steps

[Build your own solution](build-your-own-solution.md): extend entities, attributes
and mappings, validate and regenerate, then follow [deployment](quickstart.md). For generator work,
read [targets](reference/targets.md) and [template development](template-development.md).
