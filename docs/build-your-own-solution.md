# Build Your Own Solution

Start with a complete fork or copy of this repository, including `base`, `model`,
`generate`, `plugins`, `utils`, `deployment` and the solution descriptor. Keep your
own solution in source control. Use a disposable copy for this exercise; it does
not change the distributed model or require a source connection.

## Establish a reproducible starting point

Follow [local setup](getting-started.md#use-the-cli), then commit your starting
point. Keep `pyproject.toml` and `uv.lock` together: the lockfile binds the public
CLI and schema dependencies. The editor schemas in `.vscode/settings.json` match
that dependency. For the app, use a release compatible with the sample schema;
its bundled runtime is independent of the uv environment. When upgrading, review
compatibility notes and regenerate on a branch before updating these pins.

```powershell
uv sync --frozen
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run python scripts/check_generation.py --target all
```

You now have local Databricks notebooks/jobs, a Power BI TMDL model and a browsable
model reference under the three separate `output/` folders. Save a copy of this
baseline outside `output/` if you want to compare artifacts after editing.

## Expose SourceSystem to report authors

The Curated entity **DimCustomer** (ID `3000`) already contains `SourceSystem`.
Expose it in **Consumer / MasterData / Customer / Customer** (ID `4000`). This is
a semantic-layer extension: no new source import or Databricks transformation is
needed.

In the app, add a `SourceSystem` attribute to Consumer Customer with attribute type
`Text`, data type `string`, nullable **false**, and the next ordinal number. Open
its existing modeled source (Curated DimCustomer) and add a mapping from
`SourceSystem` to `SourceSystem`. Save and reload to confirm both changes.

For direct JSON editing, the same changes in
`model/040-Consumer/MasterData/Customer/Customer.json` are:

```json
{
  "name": "SourceSystem",
  "ordinalNumber": 11,
  "attributeType": "Text",
  "dataType": { "type": "string", "nullable": false },
  "dateAdded": "2026-01-01T00:00:00Z"
}
```

Append this object to `attributes`, using your actual creation date. In the existing `sources` entry whose
`sourceLocation` is `3000`, append this object to `mapping`:

```json
{ "sourceName": "SourceSystem", "targetName": "SourceSystem" }
```

Validate and run the same three-target generation check again. Confirm:

- The generated Consumer Customer documentation lists the new attribute and mapping.
- `output/powerbi/tables/Customer.tmdl` contains `column SourceSystem` with
  `dataType: string` and `sourceColumn: SourceSystem`.
- Databricks artifacts are unchanged: this target generates Raw through Curated,
  and the required upstream column was already present. Documentation timestamps
  change whenever documentation is regenerated.

The [offline workflow test](../tests/test_solution_workflow.py) reproduces this
exercise on a temporary complete copy and checks target-clean isolation. For
larger changes, maintain source/relationship references, validate all affected
layers and review generated diffs before deploying.

## Prepare your own environment

Continue with [Databricks deployment](../generate/databricks-lake/DEPLOYMENT.md)
to create tables and load data, then [Power BI project integration](powerbi-deployment.md)
to build and publish your own report. For different output conventions, follow
[template development](template-development.md).

Keep generated output disposable. Keep your authored reports and connection
parameters in a separate PBIP project, and maintain bundle configuration under
`deployment/`. Local profiles, secrets and deployment state belong outside version
control. No passwords, tokens or client secrets are supplied by this sample.
