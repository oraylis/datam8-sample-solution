# databricks-lake

This generator produces Databricks notebooks and bundle resources for an ELT flow on Azure Databricks, targeting Azure Data Lake Gen2.

## Maintainer Documentation

For payload contracts, template mapping, extension guidance, and property-driven behavior, see:
- [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- [`../../docs/template-development-howto.md`](../../docs/template-development-howto.md)

## Databricks Notebooks

The notebooks are organized by zone and by workload type (`ddl` / `dml`).

### `000` Utilities

This area contains shared utility notebooks and is not a lake zone.

### External Source Zone

The external source zone is the first zone in `Base/Zones.json` without a `localFolderName`.
It stores data ingested from source systems. Generated external DML notebooks load source data into Delta tables.

### `020` Stage and Following Zones

For model-backed zones (`010-Stage`, `020-Core`, `030-Curated`):
- DDL notebooks create target table structures from model metadata.
- DML notebooks load/merge data from modeled or external sources.
- Rows with type-conversion issues are redirected to poison handling in generated logic.
