# Generation and integration tests

## Generate targets locally

Install Python 3.13 and uv, then from the repository root run:

```powershell
uv sync --frozen
uv run python scripts/check_generation.py --target all
```

Select one target with `--target databricks`, `databricks-lakeflow`, `powerbi`,
or `docs`. The script validates the solution and generates into a disposable
copy, leaving repository output untouched. CI checks all targets for pull
requests and pushes to `main`; manual runs accept the same target selection.

## Databricks integration tests

Integration tests are manually dispatched from GitHub Actions. Set `target` to
`databricks`, `databricks-lakeflow`, or `all`. The `all` selection runs every
registered Databricks integration target in sequence. CI requires a protected
GitHub environment named `sample-integration`, with `DATABRICKS_HOST`,
`ARM_CLIENT_ID`, `ARM_TENANT_ID`, and a serverless
`DATABRICKS_SQL_WAREHOUSE_ID` variable. The workflow signs in through
`azure/login` using OIDC, then the Databricks CLI uses that Azure CLI identity.
Configure a federated credential on the Entra application with issuer
`https://token.actions.githubusercontent.com`, audience
`api://AzureADTokenExchange`, and subject
`repo:oraylis/datam8-sample-solution:environment:sample-integration`.
This trust is managed by the Entra application owner; no Databricks
account federation policy is required.
Grant that identity access to the workspace, catalogs, UC Connections, SQL
warehouse and test bundles. Do not put tokens or passwords in repository
variables.

The shared development identity is `oraylis-automation-databricks-dev`.
Its client ID, tenant ID and client secret are stored in
`aut0kvt0dev0standard` under the same prefix with suffixes `-client-id`,
`-tenant-id`, and `-client-secret`. GitHub uses OIDC and does not consume the
client secret. Other local automation can use the secret in memory with
Microsoft Entra service principal authentication.

Set `authentication_only=true` on a manual run to verify OIDC and Databricks
identity access without deploying or resetting resources. This check does
not count as a successful integration test.

For local work, authenticate with `databricks auth login --profile
oraylis-aut-dev` and run:

```powershell
uv run python scripts/run_integration_tests.py --target databricks --profile oraylis-aut-dev
uv run python scripts/run_integration_tests.py --target databricks-lakeflow --profile oraylis-aut-dev
uv run python scripts/run_integration_tests.py --target all --profile oraylis-aut-dev
```

Pass `--warehouse-id ID` if the SQL warehouse ID is not set in
`DATABRICKS_SQL_WAREHOUSE_ID`.

The test target configuration is in `tests/integration/targets.json`; jobs and
catalog settings come from the existing generated bundles and their
`bundle.targets.yml` files. The runner adds no jobs or notebooks to the bundles.
It deploys their generated artifacts, runs the existing Create, Daily and
Weekly jobs, then checks the expected schema and table counts, nonempty tables,
curated surrogate-key uniqueness, fact-to-dimension references, and the
customer SCD2 current-row rule. Both targets use
Unity Catalog Connections for source access. The committed sample model uses
reserved placeholder endpoints. Provision or update the actual Connections
separately from Key Vault, keeping hosts and credentials out of model files and
logs.

Do not run local and CI tests at the same time against shared catalogs. Reset is
limited to the selected target's test catalog. Reports go to
`Output/e2e-test-reports/`, which is ignored by Git.

To add an integration target, add its descriptor entry, bundle configuration,
and target-specific job/test configuration. Register it in the integration
target map only when its runner can check the complete target lifecycle.
