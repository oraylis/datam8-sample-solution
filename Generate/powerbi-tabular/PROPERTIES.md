# Properties: Power BI

## Where to set properties

- **Entity:** add a `properties` array to the entity JSON.
- **Folder:** add a `.properties.json` file in that model folder; values inherit to descendants.
- **External source:** set values in its `sources[]` entry, connected to a DataSource.
- **Source mapping:** mark a cursor with `extract_column=delta`.
- **Attribute:** business keys and SCD history are model fields.
- **Reusable values:** define them in `Base/PropertyValues.json`; jobs may reference schedules and clusters.

Use the value's `name` in a property reference. Effects and precedence can differ by target; each target page documents its contract.

## Power BI (`powerbi`)

| Property / model field | Effect in this target |
| --- | --- |
| `target`, `jobs`, `schedules`, `cluster`, `write_mode`, `data_retention`, `business_area`, `tags`, `table_properties`, `data_layout`, `dataset_type`, `sequence_by`, `delete_condition`, `extract_mode` | **No effect in the current Power BI generator.** It builds the semantic model from Consumer entities, their attributes, keys, sources, and relationships. |
| Attribute `sensitive` | **No effect:** it is not emitted as a Power BI security or masking rule. |
| `isBusinessKey`, attribute type, data type, relationships | Used to select columns, determine semantic-model types/keys, and generate relationships. |
