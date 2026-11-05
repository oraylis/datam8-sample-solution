# Deploy to Your Own Databricks Development Environment

Use a complete [own solution copy](../../docs/build-your-own-solution.md). The
[neutral bundle](../../deployment/databricks/databricks.yml) deploys generated
notebooks/jobs with your own user, an isolated dev workspace path and paused
schedules. It requires existing compatible compute; it does not provision a
workspace, source system, catalog, connection or service principal.

## Prepare source, catalog and identity

- Have an AdventureWorks SQL Server database containing the modeled SalesLT
  tables, reachable from the compute. Preserve the sample's source/table names
  or update the metadata and regenerate deliberately.
- Have a Unity Catalog-enabled workspace and an existing catalog reserved for
  your solution. Your user needs `USE CATALOG`, `CREATE SCHEMA`, and permission
  to create/read/write the solution's tables and assign their ownership. Existing
  objects must already be accessible. The generated schema resources create the
  Raw, Stage, Core and Curated schemas inside that catalog; managed storage must
  already be configured by its owner.
- Have an existing Unity Catalog **SQL Server connection** to your database,
  with credentials managed by its owner. The sample connection suffix is
  `sqlserver`; with the default prefix `sample_`, the runtime uses
  `sample_sqlserver`. Set your own prefix or change the modeled
  `unityCatalogConnection` setting on your solution copy. This is independent
  of the CLI's metadata connector: the latter uses `builtin:SQLServer` and
  local secret references when you explicitly import/preview a source.
- Use existing Unity Catalog-compatible compute running **Databricks Runtime
  18.3 or later**, with network access to SQL Server and your user's ability to
  attach. The generated reader uses `remote_query`, not JDBC. You need
  `USE CONNECTION`; dedicated compute also requires `MANAGE` on the connection.
  Confirm current runtime and access requirements in the
  [manufacturer documentation](https://learn.microsoft.com/en-us/azure/databricks/query-federation/remote-queries).
  Generated cluster metadata is illustrative; the mandatory dev cluster override
  below avoids provisioning those clusters or relying on their example settings.

Do not replace neutral examples with committed credentials. Databricks auth
profiles live in your personal environment; source passwords belong in the
connection's managed authentication. Local `.env`, `.databricks/` state and Power BI
credentials are excluded or stored outside the repository.

## Generate and inspect locally

From the solution root:

```powershell
uv sync --frozen
uv run datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
uv run datam8 generate databricks --solution ./ORAYLISDatabricksSample.dm8s --clean-output
```

Inspect `output/databricks/manifest.json`, the notebooks, and YAML resources.
Bundle `include` globs load every generated schema, cluster-variable and job YAML.
`sync.paths` selects only `output/databricks` and `utils`; its common ancestor is
the solution root. Explicit `sync.include` patterns re-include the ignored output.
The workspace files retain `output/databricks/...` and `utils/...`, so `%run`
references and Python runtime imports resolve together. `base`, `model`, other
targets and local configuration are not synchronized. See the
[bundle reference](https://docs.databricks.com/aws/en/dev-tools/bundles/reference#sync)
for path and ignore semantics.

## Authenticate, validate and deploy

Install the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install)
and authenticate locally to your own workspace. The following commands contact
that workspace; run them only when you intend to deploy there. Replace the example
values in your shell, without committing them:

```powershell
databricks auth login --host https://YOUR-WORKSPACE --profile sample-dev
$env:BUNDLE_VAR_catalog_name = "YOUR_ISOLATED_CATALOG"
$env:BUNDLE_VAR_owner = "YOUR_USER_NAME"
$env:BUNDLE_VAR_cluster_id = "YOUR_EXISTING_CLUSTER_ID"
$env:BUNDLE_VAR_connection_prefix = "sample_"
Set-Location deployment/databricks
databricks bundle validate --target dev --profile sample-dev
databricks bundle deploy --target dev --profile sample-dev
```

Validation should resolve all variables, resources and local notebook paths.
Deployment should create the schema/job resources and upload files beneath
`/Workspace/Users/<your-user>/.bundle/datam8-sample/dev`, with schedules paused.
The required `cluster_id` selects an existing cluster through development mode;
the `run_as` user is the authenticated current user. See
[development-mode behavior](https://docs.databricks.com/aws/en/dev-tools/bundles/deployment-modes).
Use a distinct bundle name when deploying multiple solution copies as the same
user; dev workspace isolation does not isolate data inside a shared catalog.

## Create tables and run loads in order

From `deployment/databricks`, using the same variables and profile:

```powershell
databricks bundle run --target dev --profile sample-dev Create_All_Tables
databricks bundle run --target dev --profile sample-dev Load_sales_daily
databricks bundle run --target dev --profile sample-dev Load_sales_weekly
```

Wait for each command to finish successfully before starting the next. Create All
calls zone creation jobs in layer order. The current manifest makes the weekly
load depend on the daily load; after model changes, read `execution_plan` again
and follow its dependencies. Do not start downstream jobs after an upstream
failure. Schedules remain paused until you intentionally configure automation.

Inspect run logs, row counts, keys and expected values in your isolated catalog.
The sample's offline tests do not check these live outcomes. On permission,
connection or runtime errors, correct your environment before retrying. Then
continue with [Power BI](../../docs/powerbi-deployment.md).

For a shared or production deployment, define a separate target and review
`run_as`, grants, compute, data isolation and scheduling with your operators.
Service principals are optional advanced configuration; no fixed principal or
job-permission grant is emitted by the templates. Regenerate output before each
deploy, keeping the authored bundle and runtime utilities outside cleaned output.
