# Properties: Databricks Lake

## Where to set properties

- **Entity:** add a `properties` array to the entity JSON.
- **Folder:** add a `.properties.json` file in that model folder; values inherit to descendants.
- **External source:** set values in its `sources[]` entry, connected to a DataSource.
- **Source mapping:** mark a cursor with `extract_column=delta`.
- **Attribute:** business keys and SCD history are model fields.
- **Reusable values:** define them in `Base/PropertyValues.json`; jobs may reference schedules and clusters.

Use the value's `name` in a property reference. Effects and precedence can differ by target; each target page documents its contract.

## Databricks Lake (`databricks`)

The classic target creates one load job for each distinct resolved `jobs` value.
The job contains the assigned entities across Raw, Stage, Core, and Curated.
Dependencies between entities with the same `jobs` value come from their
modeled source references. Cross-job dependencies remain in the execution
manifest; a load job never invokes another load job or runs its tasks. Raw
extraction tasks stay in the job of their consuming Stage entity. The local/CI
runner runs each selected job once in dependency order. The Create All job and
its four zone-specific table-creation jobs are separate from these load jobs.

| Property | Where and current values | Effect in this target |
| --- | --- | --- |
| `jobs` | Entity or folder. Current load values: `sales_daily` → `Sales (Daily)`, `sales_weekly` → `Sales (Weekly)`. `create_all` configures table creation. | Assigns entities to the corresponding generated job. The model value's `displayName` is the job display name. Same-job source dependencies create task edges; cross-job dependencies are recorded for ordered runner execution. |
| `schedules` | Nested in a `jobs` property value; current schedule values are `daily` (`1 0`) and `weekly` (`0 0 2 ? * SUN`). | Attaches a Quartz schedule to the generated job. Time zone is `Europe/Amsterdam`; enablement is controlled by the bundle's `unpause_schedules` variable. |
| `cluster` | Nested in a `jobs` property value. Values defined: `serverless`, `small`, `extra_small`. | Selects serverless job compute or a configured job cluster. Create All and the Sales Daily/Weekly jobs use `extra_small` (two `Standard_D4ds_v5` workers). |
| `write_mode` | Entity or folder. Values: `overwrite`, `merge`, `append`. | Controls writes to modeled tables. `merge` requires business keys and uses the configured history fields; `append` adds rows; `overwrite` replaces the current output. |
| `extract_mode` | External source entry. Values: `full`, `delta`, `query`. | Controls Raw extraction. `full` and `query` replace the Raw snapshot; `delta` filters by the marked cursor and appends the extracted change set. |
| `extract_column` | Property on a source mapping; current cursors are `ModifiedDate`, `ModifiedAt`, `modifiedat` and `MODIFIEDAT`. | Marks which mapped source column is the cursor for `extract_mode=delta`. Missing or multiple cursors fail generation rather than silently selecting a full read. |
| `data_retention` | Entity or folder. Current value: `7_days`. | Sets Delta log and deleted-file retention intervals on generated tables. |
| `business_area` | Entity or folder. Current values include `sales`, `masterdata`, `procurement`, `inventory`, `commerce`, and `shipping`. | Preserved as table metadata/tag by classic DDL generation; it does not choose a job or change table routing. |
| `tags` | Entity or folder. | Passed through by classic DDL generation as table tag metadata. It does not affect orchestration or writes. |
| `enable_type_widening` | Folder/entity metadata. Defined value: `true`. | Sets Delta's type-widening table property. |
| `column_mapping_mode` | Folder/entity metadata. Defined value: `name`. | Sets Delta's column-mapping table property. |
| `table_properties` | Entity or folder. | **No arbitrary Delta-property handling is implemented.** Do not use this property to configure Delta settings; use the explicit properties above. |
| `data_layout` | Entity. The model contains `liquid_clustering` examples. | **No effect:** the classic DDL/DML generator does not read this property or emit liquid clustering. |
| `dataset_type` | Entity or folder. Values: `materialized_view`, `streaming_table`. | **No effect:** this target always generates Delta tables and notebook DML; it does not select Lakeflow object types. |
| `sequence_by`, `delete_condition` | Entity or folder. | **No effect:** these are read only by the Lakeflow target. |
| `target` | Zone. Defined value: `power-bi`. | **No effect on this target's job or schema generation.** Databricks schema names come from each zone's `targetName` in `Base/Zones.json`. |
| Attribute `sensitive` | Attribute property; present on customer attributes. | Emitted as a Unity Catalog column tag by classic DDL; it does not mask or encrypt the data. |

`validate_all` is a defined `jobs` value but no current model entity or generated
job uses it. `small` remains available as an alternative four-worker job-cluster
configuration.
