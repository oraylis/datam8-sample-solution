# Databricks Generator

This generator produces Databricks notebooks and Databricks Asset Bundle resources
from the DataM8 metadata model.

## Generated Artifacts

- DDL notebooks for modeled and external tables.
- DML notebooks for extraction, source loading, merging, and transformations.
- Python transformation function files copied from model-side scripts.
- Databricks Asset Bundle resources for schemas, clusters, and jobs.

## Maintainer Documentation

For target-specific payload contracts, template mapping, interpreted properties,
and validation guidance, see [ARCHITECTURE.md](./ARCHITECTURE.md).

For beginner template and payload development, see
[Template and Payload Development](../../docs/howto-template-and-payload-development.md).
