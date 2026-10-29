# Properties: Documentation target

## Where to set properties

- **Entity:** add a `properties` array to the entity JSON.
- **Folder:** add a `.properties.json` file in that model folder; values inherit to descendants.
- **External source:** set values in its `sources[]` entry, connected to a DataSource.
- **Source mapping:** mark a cursor with `extract_column=delta`.
- **Attribute:** business keys and SCD history are model fields.
- **Reusable values:** define them in `Base/PropertyValues.json`; jobs may reference schedules and clusters.

Use the value's `name` in a property reference. Effects and precedence can differ by target; each target page documents its contract.

## Documentation target (`docs`)

The documentation generator renders model structure and metadata. Operational
properties such as `jobs`, `schedules`, `cluster`, `write_mode`, `extract_mode`,
`dataset_type`, `sequence_by`, and `delete_condition` do not alter generated
runtime behavior or documentation layout. Zone names, folder hierarchy,
descriptions, entities, attributes, mappings, and relationships drive its output.
Attribute `sensitive` is not presented as a masking or security control.
