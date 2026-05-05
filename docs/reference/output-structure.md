# Output Structure

Generated artifacts are written below each target's `outputPath` from
[`ORAYLISDatabricksSample.dm8s`](../../ORAYLISDatabricksSample.dm8s).

## Databricks

Databricks output is written to `Output/databricks`.

Expected structure:

```text
Output/databricks/
  clusters/
  jobs/
  notebooks/
  schemas/
```

- `schemas/`: Databricks Asset Bundle schema resources.
- `clusters/`: Databricks Asset Bundle cluster resources.
- `jobs/`: create/load orchestration job definitions.
- `notebooks/`: generated DDL, DML, extraction, and transformation notebooks.

The repository root [`databricks.yml`](../../databricks.yml) includes these files
for Databricks Asset Bundle deployment.

## Power BI Tabular

Power BI output is written to `Output/powerbi-tabular`.

Expected structure:

```text
Output/powerbi-tabular/
  powerbi-tabular/
    database.tmdl
    model.tmdl
    expressions.tmdl
    relationships.tmdl
    tables/
  powerbi.yml
  azure-pipelines.powerbi.yml
```

The nested `powerbi-tabular/` folder contains the generated TMDL files for the
database, model, expressions, relationships, and tables.

## Documentation

Documentation output is written to `Output/docs`.

Expected artifacts:

```text
Output/docs/
  index.md
  entities/
  diagrams/
    entity-relationships.drawio
```

The exact entity pages and diagram content depend on the model metadata.
