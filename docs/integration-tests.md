# Generation and integration tests

## Runner order and repeat selection

1. Validate environment and identity, save the report, and start the SQL warehouse
   only when initially stopped.
2. Apply non-secret bindings through the CLI, generate each selected target once,
   and restore the original model bindings on every exit.
3. Check source families with bounded reads and both API endpoints with pagination.
   Database smoke checks use `LIMIT 1`. Both targets reuse a normalized source
   inventory result for two hours. Full source counts occur at final validation.
4. Inspect selected bundle bindings, active runs and owned objects. Known Lakeflow
   internal tables must match the manifest and a bound pipeline ID.
5. Deploy and verify assets, compute and execution identities.
6. Run the existing classic Create root, then Load jobs in manifest dependency
   order. Its four nested zone jobs are child runs of one root launch. Lakeflow
   has Load jobs only. No additional test jobs are created.
7. Validate data, history, relationships and totals. Repeat Load only when
   `--verify-repeat` is selected; record every repeat in `repeat_runs`.
8. Reconcile extraction completeness, compare targets, save the final result,
   and stop an initially stopped warehouse. Cleanup errors are reported separately.

Default local and GitHub integration runs load once; `verify_repeat` defaults to
false. Explicit repeat acceptance and local resume use:

```powershell
uv run python scripts/run_integration_tests.py --environment dev --target all --verify-repeat
uv run python scripts/run_integration_tests.py --environment dev --target all --verify-repeat --resume-report Output/e2e-test-reports/previous.json
```

GitHub's optional `resume_run_id` downloads the prior report artifact. Resume
reconciles stored remote run IDs, reuses unchanged success evidence, repairs
affected tasks and invalidates downstream jobs. New starts use stable idempotency
tokens to correlate a lost response. An unrequested repeat is `not_requested`,
never passed. Full repeat acceptance requires that suite and all data checks.

For a one-time migration from locally verified runs, the selected GitHub
environment can temporarily supply `INTEGRATION_RESUME_EVIDENCE` (gzip-compressed,
base64-encoded sanitized report JSON, maximum one MiB unpacked). This uses the
same fingerprint and environment checks as file-based resume. Remove that variable
after the first CI report exists and use `resume_run_id` for subsequent retries.
Resume always rechecks the target and its data; it reuses job execution evidence.

Entra OIDC is renewed before each target and at most every thirty minutes during
long runs. Renewal is serialized; mutation API calls are never blindly retried.
Diagnostics and artifacts redact credentials, including GitHub's OIDC request
credential. Cleanup cannot discard the primary failure or leave a running result.

Extraction examples live in the [classic properties guide](../Generate/databricks-lake/PROPERTIES.md)
and [Lakeflow properties guide](../Generate/databricks-lakeflow/PROPERTIES.md).

## Install the pinned tools

Use Python 3.13 or newer and uv in this checkout:

```powershell
uv sync --frozen
uv run python scripts/install_plugins.py
```

The lockfile pins CLI commit `85ff50de3c7fc8e20abd4edd021d63df02c31b91`
and model commit `002aa65f6f127f91d06c8dc0fc4ea50ce75616fc`.
[plugins.lock.json](../plugins.lock.json) records the five metadata plugins from
commit `5fec63282f0c94727031a5ebe15ed6e86247bb5b`, version 1.2.0, and their
SHA-256 checksums. Only the lock is versioned; installed `Plugins/` files stay
local. Local source import, metadata refresh and preview need these plugins, so
local installation uses `DATAM8_PLUGINS_READ_TOKEN` or a plugin checkout passed
with `--repository PATH`.

## Generation

```powershell
uv run python scripts/check_generation.py --target all
uv run python scripts/check_generation.py --target powerbi
```

Generation reads target names and output paths from the solution descriptor.
It validates the persisted local model, cleans each selected generated output,
and runs every target in a separate CLI process. No solution copy is created.
Unknown targets fail before generation; all selected failures are reported.
Python syntax, task graphs, bundle assets, public source metadata and the native
Lakeflow inventory are checked. CI runs all targets for PRs and pushes to `main`;
manual execution accepts one target or `all`.

## Integration environments

The [environment configuration](../tests/integration/environments.json) contains
non-secret workspace, identity, catalog, warehouse and source bindings. See the
target guides for their workspace and catalog bindings: [Databricks Lake](../Generate/databricks-lake/DEPLOYMENT.md)
and [Lakeflow](../Generate/databricks-lakeflow/DEPLOYMENT.md). The runner never
cleans old workspaces.

Deploy and run identities are distinct. The deployment service principal manages
the bundle and must be allowed to use the run principal. Bundle-level permissions
grant the run principal execution access to both pipelines and nested jobs.
The run principal needs catalog/schema data privileges, `USE CONNECTION` on its
five source connections and read access to uploaded workspace files. The deploy
principal also needs the permissions used by preflight and data validation.
Stopping the dedicated test warehouse requires `CAN_MANAGE`; its run identity
needs only `CAN_USE`.

The runner executes modeled load jobs in dependency order and retains each
target's task results in its report. Target-specific naming and compute behavior
is documented in each target guide. The SQL validation warehouse is serverless;
an initially stopped warehouse is stopped again on completion or failure.

GitHub Actions uses the GitHub environment names `sample-integration-dev` and
`sample-integration-prod`. Each must define `ARM_CLIENT_ID` matching that
environment's `deployment_principal` in `environments.json`, `ARM_TENANT_ID`,
`DATABRICKS_HOST`, and `DATABRICKS_SQL_WAREHOUSE_ID`. The host and warehouse are
checked against the selected environment configuration before Azure login or
deployment. Azure federated credentials must trust the matching GitHub
environment subject, for example
`repo:oraylis/datam8-sample-solution:environment:sample-integration-dev`.

GitHub generation and integration use the persisted source metadata and do not
invoke connector plugins; no plugin token is required in Actions. The plugin
lock and installer are for local source import, metadata refresh and preview.
The previous
`sample-integration` environment belongs to the legacy integration setup and is not
used by the new Dev/Prod workflow.

## UC connections and source access

Each environment shares five connections between its two targets:
`dm8_sample_<environment>_sqlserver`, `_oracle`, `_mysql`, `_postgresql` and
`_shipping_api`. Oracle uses TLS. HTTP uses OAuth M2M stored in UC; both endpoints
are paginated through the UC proxy. There is no direct-credential fallback.

Infrastructure provisioning reads the Lab credentials from `kv-dm8-dev-weu-001`
in memory and assigns environment-specific use privileges. Source secrets and
hosts must not be copied into the sample. Its DataSources retain neutral
`.example.invalid` endpoints, sample users and `ref://sample/...` references.
Only non-secret database/service bindings are temporarily applied to this local
solution through DataM8 CLI before generation and restored in `finally`.

Start the Lab fixtures under the infrastructure project's bounded lease before
running integration. Provisioning and Lab lifecycle belong to that project,
not to generated notebooks. Use the current operator IP for the temporary SSH
rule; no broader administrative network rule is needed. Verify the lease is
stopped and its session rules removed after testing, including failures.

## Local execution

CI authenticates as the selected environment's deployment SP through OIDC.
For a local Dev run, an explicitly supplied user UPN can be allowed; the script
checks it against the workspace identity and still verifies the configured
`run_as` principal. Prod does not allow the local-user override. Credentials
remain in the local Databricks authentication session; no token or password
belongs in a bundle, model, report, shell history or repository variable.

```powershell
uv run python scripts/run_integration_tests.py --environment dev --target all
uv run python scripts/run_integration_tests.py --environment dev --target databricks-lakeflow
uv run python scripts/run_integration_tests.py --environment prod --target databricks
uv run python scripts/run_integration_tests.py --environment dev --target all --profile dm8-target-dev --deployment-profile dm8-deploy-dev --local-user "your.name@company.com"
```

For the user-session example, replace `dm8-deploy-dev` with a local profile
authenticated as the configured deployment SP. The user profile runs validation;
the separate deployment profile manages the existing bundle.

Use `--force-lock` only to recover a stale bundle lock. Before deploying, the
runner still checks that none of the selected bundle's jobs or pipelines is
active.

A local profile can be supplied with `--profile NAME`. The runner verifies its
actual deployment identity and selected host; a user login or the run SP cannot
silently replace the deployment SP. Generate first when inspecting bundle files
manually, then run Databricks commands from the selected target output folder
with `--target dev` or `--target prod`.

## Acceptance and reset

Dev performs source preflight before any reset, validates and deploys the existing
bundle, executes the classic Create root followed by each modeled Load job in
dependency order; for Lakeflow it executes each modeled Load job once, with
managed ingestion tasks completed before that job's processing pipeline. It
checks complete execution trees and validates data. Load is repeated only with
`--verify-repeat`; Create is not repeated for that check. Job keys and cross-job dependencies come from the generated
manifest rather than hardcoded names. Timeouts cancel remote work: Create 30 minutes, Load 90
minutes and validation queries at most 30 minutes.

Reset requires explicit `--reset` on a fresh Dev run and cannot be combined with
`--resume-report`. Classic reset drops only validated, owned sample schemas. Native reset refreshes
only the owned pipeline graph; subsequent updates do not use full refresh.
An explicit Dev Lakeflow migration can instead select individual manifest
datasets with repeated `--refresh-dataset schema.table` arguments together with
`--target databricks-lakeflow --resume-report ...`. The runner verifies each
dataset's bound pipeline and refreshes only that selection in dependency order.
It records update IDs and resumes completed updates without restarting them.
Foreign objects, active runs, partially bound deployment states and unexpected
resource replacement abort the test. Lakeflow event-log tables are considered
owned only when their names match the IDs of the selected target's bound
pipelines. Selecting one target changes only that target's cloud resources.

Generation manifests define the 22 Raw, 21 Stage, 15 Core and 11 Curated public
objects per target, plus explicitly owned internal history datasets. Validation
checks object kinds, schemas, nonempty data, business and surrogate keys, history
intervals, relationships, source extraction completeness and financial totals.
Unchanged reloads must preserve business data and history version counts.
When both targets run, normalized business contents are compared across them.
Power BI exposes the six domains in one semantic model; explicit relationships
must reference real consumer columns.

Prod's scope is enforced by the runner: deployment and smoke checks only. It
cannot execute full processing roots or reset tables through this entry point.
A successful smoke run is recorded as smoke, never as full data acceptance.
Skipped required tasks, partial API snapshots and empty modeled tables fail.
Generation or authentication success alone does not satisfy acceptance.

## Reports and diagnosis

Reports are local, Git-ignored files beneath `Output/e2e-test-reports/`. CI uploads
its generation and integration JSON reports as artifacts. They identify the
revision, selected environment/targets, deployment and run identities, resource
links, nested task outcomes and data checks. They contain no source credentials.

Check the failing phase first: source preflight, binding/ownership, deployment,
remote execution or data validation. Fix metadata via CLI and payloads/templates
in their owning target, regenerate and rerun. Do not skip a required source or
convert a failed task into success to obtain a green report.

## Add an integration target

Add its generation target to the descriptor. Register a supported implementation
and bundle path in [targets.json](../tests/integration/targets.json); keep target
selection validation ahead of mutations. Reuse the shared generation, report and
lifecycle contracts while implementing platform-specific deployment and data
checks. A new target must not weaken the environment's safety or test scope.
