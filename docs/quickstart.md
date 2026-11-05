# From Generated Files to Deployment

Start with [local generation](getting-started.md). This public example contains
metadata and templates, not a deployment runner, environment bindings or an active
Azure pipeline. Generated notebooks and TMDL are files for review, not evidence of
a running data platform.

Before any deployment, review your platform's workspace, catalog, storage,
identities, source connections and secret integration in your own delivery process.
Keep those bindings outside this sample and preserve the authored runtime utilities
referenced by generated notebooks. Verify platform prerequisites independently.

The [Databricks boundary](../generate/databricks-lake/DEPLOYMENT.md) and
[configured outputs](reference/targets.md) identify the artifacts supplied here.
The local exercise creates no cloud resources and starts no data processing.
Never commit live values in place of neutral source examples.
