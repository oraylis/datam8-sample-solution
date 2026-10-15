# Optional Deployment Preparation

Start with [local generation](getting-started.md). Deployment is optional and was
not exercised by this documentation update. Generated artifacts are inputs to a
separate platform-specific release process, not proof of running infrastructure.

## Databricks

Choose your own workspace, storage, authentication, secret management and CI/CD
environment. Inspect the actual generated target tree and hand-written deployment
configuration before selecting a deployment runner. Review notebooks, jobs and
resource names; confirm that source and target permissions match your environment.

Do not reuse example cloud URLs, service connections or organization-specific
access instructions. Supply credentials outside committed JSON and output files.
Run a small deployment in your own test workspace and record its platform/tool
versions, results and rollback procedure before describing it as supported.

## Power BI

Review generated TMDL and the selected workspace/deployment tooling independently.
Generating files does not publish a semantic model or validate its refresh access.

## Existing pipeline

`azure-pipelines.yml` references superseded tool commands and environment-specific
resources. It has not been modernized or accepted here. Do not use it as the current
v2 setup procedure; see [the handoff](documentation-handoff.md) for the replacement task.
