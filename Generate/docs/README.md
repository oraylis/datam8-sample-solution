# Model Documentation Target

Build a browsable reference for your data model from the metadata you maintain in
DataM8. This target generates an entity catalog, detailed model pages and a draw.io
relationship diagram, giving developers, analysts and reviewers a shared view of
the solution's structure and meaning.

## What you can build

- **A solution overview** with model statistics, zones, products/modules and a
  linked catalog of entities.
- **An entity reference** covering descriptions, attributes and types, business
  and surrogate keys, history settings and assigned properties.
- **Source and transformation documentation** showing where data comes from,
  its mappings and the modeled transformation steps.
- **Relationship views** showing incoming/outgoing entity relationships and a
  visual diagram grouped by model zone.

For example, open Customer from the generated catalog to review its attributes,
source mappings, inherited folder properties and relationships. Use the diagram
to discuss how entities fit together across the model layers. Regenerate after
model changes so that the reference reflects the current metadata.

## Generated artifacts

The target name is **docs** and its configured output root is `Output/docs`.

| Artifact | Role |
| --- | --- |
| `index.md` | Solution overview, statistics, zone summaries and linked entity catalog |
| `entities/<model-path>/<entity>.md` | An entity's metadata, inherited context, sources, transformations and relationships |
| `diagrams/entity-relationships.drawio` | Editable relationship diagram |

Entity page paths are derived from the model hierarchy. The index links to the
generated pages, so it is the starting point for browsing the reference.

## Generate and use the result

Use **DataM8 app 2.0.0**, select **docs** in the generator and choose **Generate**.
Or run **DataM8 CLI 2.0.0** from the solution root:

```sh
datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s
```

Open `Output/docs/index.md` in a Markdown viewer and follow its entity links. Open
`Output/docs/diagrams/entity-relationships.drawio` in draw.io to explore or arrange
the diagram. Keep the generated Markdown and diagram together when sharing the
reference or including it in your project's documentation.

Generation reads the local metadata, so this is a useful first target to try when
exploring the sample. For setup, see [getting started](../../docs/getting-started.md).
For the documentation builder, templates and extension points, read
[ARCHITECTURE.md](ARCHITECTURE.md).
