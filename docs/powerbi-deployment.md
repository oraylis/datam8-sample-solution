# Use the Generated Model in Your Own Power BI Project

This route uses Power BI Desktop, an authored PBIP project and manual publishing.
The generator writes TMDL to `output/powerbi`; it does not create reports or publish
through XMLA. See [Microsoft's semantic-model project reference](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
for `definition.pbism`, TMDL and local cache behavior.

## Create the project and integrate TMDL

1. Use Power BI Desktop with PBIP and TMDL project support enabled. Create your
   own report and save it as a **Power BI Project (.pbip)** outside `output/`.
   If necessary, add a small local table first so Desktop creates a semantic model.
   Save the model in TMDL format and close Desktop before editing files.
2. Generate the target from your solution root:

   ```powershell
   uv run datam8 generate powerbi --solution ./ORAYLISDatabricksSample.dm8s --clean-output
   ```

3. Back up or commit your PBIP project. Replace the contents of its semantic-model
   `definition/` folder with the contents of `output/powerbi/`, including `tables/`.
   Keep the project, report folder, `definition.pbism` and report-to-model binding.
   Do not place a second `powerbi-tabular/` folder beneath `definition/`.
4. Keep the project free of a stale `.pbi/cache.abf` from the temporary model.
   Microsoft documents that this cache can overwrite the definition on opening.
   A project without a cache opens with metadata and no data. Ignore local cache
   and settings in source control.
5. Open the PBIP in Desktop **without refresh**. Check Customer, Date, Sales Order,
   measures and relationships in Model view. For the extension exercise, check
   `Customer[SourceSystem]`. Opening validates local model metadata; it does not
   establish source connectivity or successful refresh.

## Connect, refresh and publish

After [loading the Databricks tables](../generate/databricks-lake/DEPLOYMENT.md),
set these Power Query parameters in your authored project:

| Parameter | Your value |
| --- | --- |
| `DBW_Catalog` | The catalog used for this solution's Databricks deployment |
| `DBW_Hostname` | Your Databricks SQL server hostname |
| `DBW_HTTP_Path` | Your compatible SQL warehouse's HTTP path |

Generated defaults are neutral placeholders. Authenticate through Desktop's
Databricks connector using your own identity; never put credentials in TMDL.
You need warehouse access and permission to read the Curated tables. Refresh in
your own environment, build report visuals, then use Desktop **Publish** to select
your workspace. Configure the semantic model's credentials and scheduled refresh
in Power BI Service, and verify a refresh there. Workspace access, licensing and
tenant policies are operator prerequisites.

## Regenerate without losing authored work

Keep the PBIP outside the generated output. Regenerate into `output/powerbi`,
close Desktop and review the TMDL diff before copying it into `definition/` again.
Preserve your project's `expressions.tmdl` connection parameters, authored report
folder, project files and report-to-model binding. Review any new generated
parameters explicitly rather than overwriting existing values. Remove obsolete
generated table definitions when the model removes a table; merge any intentional
hand-authored measures or other TMDL customizations separately.

Reopen without refresh to inspect metadata first. Refresh and publish only when
you intend to update your own environment. The sample's local checks never do so.
