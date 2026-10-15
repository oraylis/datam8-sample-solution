# Power BI Tabular Target

Build the semantic model that turns your consumer-layer metadata into tables,
relationships and measures for Power BI reporting. This target generates a TMDL
model definition from the entities in `Model/040-Consumer`, keeping the reporting
model connected to the same metadata used for your data platform.

## What you can build

The sample's Consumer layer describes the tables and measures exposed to report
authors. The generated semantic model brings together:

- **Tables and columns** with data types, source mappings, display names, key
  settings, visibility and formatting derived from entity attributes.
- **Relationships** connecting the modeled consumer tables.
- **DAX measures** from attributes whose expression language is DAX.
- **Import partitions** with Power Query expressions that read the referenced
  Databricks tables.
- **Connection parameters** for the Databricks catalog, hostname and HTTP path.

For example, the sample Consumer layer contains Customer, Date, Sales Order and
Measure entities. These provide the building blocks for an analytical model in
which report authors can combine sales facts, customer/date context and shared
measures. Maintain the corresponding entities and relationships in DataM8, then
regenerate the semantic model when they change.

The [Databricks target](../databricks-lake/README.md) supplies the upstream
lakehouse tables; this target supplies their semantic reporting layer.

## Generated artifacts

The target name is **powerbi** and its configured output root is
`Output/powerbi-tabular/generated`. Payloads add a `powerbi-tabular` subdirectory,
so the model definition is written to
`Output/powerbi-tabular/generated/powerbi-tabular/`.

| Artifact | Role |
| --- | --- |
| `database.tmdl` | Database name and model compatibility settings |
| `model.tmdl` | Model settings and references to the generated tables |
| `expressions.tmdl` | Databricks connection parameters |
| `relationships.tmdl` | Relationships between consumer tables |
| `tables/<table>.tmdl` | Columns, measures and partition/query definitions for each table |

## Generate and use the result

Use **DataM8 app 2.0.0**, select **powerbi** in the generator and choose
**Generate**. Or run **DataM8 CLI 2.0.0** from the solution root:

```sh
datam8 generate powerbi --solution ./ORAYLISDatabricksSample.dm8s
```

Inspect the generated tables, relationship columns and measures. Integrate the
TMDL definition into your semantic-model project and supply the Databricks
connection parameters for your environment. Publish and configure refresh through
your Power BI deployment workflow; reports can then use the shared semantic model.

For setup, see [getting started](../../docs/getting-started.md) and
[deployment preparation](../../docs/quickstart.md). For mapping rules, payloads
and extension points, read [ARCHITECTURE.md](ARCHITECTURE.md).
