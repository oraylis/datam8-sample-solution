# Databricks Lakeflow deployment and integration

## Dev and Prod bindings

| Environment | Workspace | Catalog | Validation warehouse |
| --- | --- | --- | --- |
| Dev | `adb-7405619058873076.16.azuredatabricks.net` | `dm8_sample_dev_lakeflow` | `825b17d829cbed30` |
| Prod | `adb-7405605063080000.0.azuredatabricks.net` | `dm8_sample_prod_lakeflow` | `ec27803655fa68c7` |

The deployment identity manages bundle resources. A separate run identity executes
jobs and pipelines. Local Dev runs may deploy as the authenticated user when the
runner receives `--local-user` and a separate deployment profile. CI uses the
selected GitHub environment's OIDC identity.

The `ingestion_permissions` bundle variable records the ingestion resources' ACL.
Existing Dev UC ingestion pipelines retain their current user owner, with
`CAN_MANAGE` for the deploy SP and `CAN_RUN` for the run SP. This explicit Dev
binding preserves ownership instead of attempting a metastore-admin-only owner
transfer on every deployment. Fresh environments default to the deploy SP as
owner. The execution identity remains the run SP in both cases.

Pipeline compute comes from each model job's nested `cluster` property. The
current sample uses `extra_small` for processing and managed-ingestion
pipelines. The SQL validation warehouse remains serverless. Schedules stay
paused unless enabled through the bundle configuration.

## Run locally

```powershell
uv run python scripts/run_integration_tests.py --environment dev --target databricks-lakeflow --profile dm8-target-dev --deployment-profile dm8-target-dev-deploy-codex --validation-profile dm8-target-dev-run-codex --local-user "your.name@company.com"
```

Dev performs the full pipeline and data acceptance. Prod supports deployment
and bounded source smoke checks only. Shared setup, source requirements and
report semantics are in the [integration test guide](../../docs/integration-tests.md).

## Explicit selected-dataset migration

A connector key/mode change can require a full refresh of the impacted datasets.
Use the existing runner with a Dev resume report and explicit manifest keys:

```powershell
uv run python scripts/run_integration_tests.py --environment dev --target databricks-lakeflow --resume-report Output/e2e-test-reports/previous.json --verify-repeat --refresh-dataset raw.postgresqlwarehouse_aw_warehouse_stockmovement --refresh-dataset stage.postgresqlwarehouse_aw_warehouse_stockmovement --refresh-dataset core.inventory_stock_stockmovement
```

This validates pipeline ownership and performs selected full refreshes on the
already deployed pipelines in source dependency order. Every update ID is recorded
under `dataset_refreshes`; successful migration updates are reused on resume.
The existing failed job is then repaired for its unsuccessful tasks. Unchanged
successful ingestion tasks are retained. Repetition runs the normal job settings
without full refresh. This option is not supported in Prod or as an implicit reset.
