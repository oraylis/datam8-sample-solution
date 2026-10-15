# Databricks Target

This target renders Databricks notebooks and related artifacts from the v2 model.
It is selected by the target name `databricks`, while its templates reside here.
The configured output root is `Output/databricks-lake/generated`.

For interpreted properties, payload contracts and extension points, read
[ARCHITECTURE.md](ARCHITECTURE.md). For running generation and inspecting files,
read [getting started](../../docs/getting-started.md) and
[the target reference](../../docs/reference/targets.md).

Generation does not create Azure resources or execute notebooks. Review target
output and configure a separate deployment process for your environment.
