# Databricks Lake deployment and integration

## Dev and Prod bindings

| Environment | Workspace | Catalog | Validation warehouse |
| --- | --- | --- | --- |
| Dev | `adb-7405619058873076.16.azuredatabricks.net` | `dm8_sample_dev_lake` | `825b17d829cbed30` |
| Prod | `adb-7405605063080000.0.azuredatabricks.net` | `dm8_sample_prod_lake` | `ec27803655fa68c7` |

The deployment identity owns bundle resources; the separate run identity executes
jobs. Local Dev runs can use the authenticated operator for deployment only when
the runner receives `--local-user` and a separate deployment profile. Jobs still
run as the configured run service principal. CI uses the selected GitHub
environment's OIDC identity.

The model's nested `cluster` job property selects the job cluster. The current
sample uses `extra_small` for Create All, zone creation and both load jobs.
Schedules remain paused unless the bundle enables them.

## Run locally

```powershell
uv run python scripts/run_integration_tests.py --environment dev --target databricks --profile dm8-target-dev --deployment-profile dm8-target-dev-deploy-codex --validation-profile dm8-target-dev-run-codex --local-user "your.name@company.com"
```

The Dev run performs controlled Create, modeled load jobs and manifest-based
data checks. Prod only supports deployment and bounded source smoke checks.
Shared setup, source requirements and report semantics are in the
[integration test guide](../../docs/integration-tests.md).
