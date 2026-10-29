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
