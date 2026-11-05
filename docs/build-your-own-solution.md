# Build Your Own Solution

Start with a complete fork or copy of this repository, including `base`, `model`,
`generate`, `plugins`, `utils`, `deployment` and the solution descriptor. Keep your
own solution in source control and make changes on a branch. Local model editing,
validation and generation do not require a source connection or cloud account.

## Establish a reproducible starting point

Follow [local setup](getting-started.md#use-the-cli), then commit your starting
point. Keep `pyproject.toml` and `uv.lock` together: the lockfile binds the public
CLI and schema dependencies. The editor schemas in `.vscode/settings.json` match
that dependency. For the app, use a release compatible with the solution schema;
its bundled runtime is independent of the uv environment. When upgrading, review
compatibility notes and regenerate on a branch before updating these pins.

```powershell
uv sync --frozen
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s --clean-output
uv run datam8 generate databricks --solution ./ORAYLISDatabricksSample.dm8s --clean-output
uv run datam8 generate powerbi --solution ./ORAYLISDatabricksSample.dm8s --clean-output
```

Open the generated documentation index and inspect the notebooks/jobs and TMDL
under the [three target output folders](reference/targets.md). Each generation
command replaces only its selected target's output, including stale artifacts.
Save a copy of this baseline outside `output/` to compare artifacts after editing.

## Extend the model

Use the DataM8 app or edit the persisted JSON and function files in your editor.
The [user handbook](https://github.com/oraylis/datam8/blob/main/docs/user-guide/README.md)
covers the individual editors and workflows.

1. Choose the layer where the change belongs. Add or modify entities and
   attributes with the appropriate types, keys, descriptions and properties.
   Add new entities through the app or follow the existing schema when editing
   JSON; every entity needs a unique ID.
2. Define where the data comes from. For an external source, configure its source
   type and connection references. Source import and preview require your own
   connection and credentials; stored model metadata can be edited offline.
   For an existing modeled source, select the upstream entity and map its
   attributes to the target attributes.
3. Update transformations and referenced function files when the change needs
   new logic. Maintain relationships and downstream mappings across the affected
   layers. Expose reporting fields in the Consumer layer when report authors
   need them.
4. Save and reload the solution to confirm that the edits are persisted. Validate
   before generating again.

Keep credentials outside version control and use secret references in source
settings. For property behavior and target selection, consult the
[model properties](model-properties.md) and [target references](reference/targets.md).

## Validate and review the generated changes

Run the validation and generation commands above again, or select the affected
targets in the app. Check command exit codes and review the resulting artifacts:

- **Documentation:** changed entities, attributes, mappings and relationships
  appear in the catalog and entity pages.
- **Databricks:** affected Raw, Stage, Core and Curated notebooks and jobs reflect
  the change, with the intended dependencies and table definitions.
- **Power BI:** affected Consumer tables, columns, relationships and measures
  appear in the generated TMDL.

The targets cover different layers, so a model change may affect only some of
them. Compare against your baseline and investigate unrelated differences.
Documentation timestamps change whenever documentation is regenerated. Commit
the authored model, template and configuration changes after review; output
remains disposable. When changing generator code, use the contributor
[local checks](integration-tests.md) as well.

## Prepare your own environment

Continue with [Databricks deployment](../generate/databricks-lake/DEPLOYMENT.md)
to create tables and load data, then [Power BI project integration](powerbi-deployment.md)
to build and publish your own report. For different output conventions, follow
[template development](template-development.md).

Keep your authored reports and connection parameters in a separate PBIP project,
and maintain bundle configuration under `deployment/`. Local profiles, secrets
and deployment state belong outside version control. Review the generated
changes and the impact on existing data before deploying to your own environment.
