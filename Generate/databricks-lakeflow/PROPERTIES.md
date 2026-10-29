# Properties: Databricks Lakeflow

## Where to set properties

- **Entity:** add a `properties` array to the entity JSON.
- **Folder:** add a `.properties.json` file in that model folder; values inherit to descendants.
- **External source:** set values in its `sources[]` entry, connected to a DataSource.
- **Source mapping:** mark a cursor with `extract_column=delta`.
- **Attribute:** business keys and SCD history are model fields.
- **Reusable values:** define them in `Base/PropertyValues.json`; jobs may reference schedules and clusters.

Use the value's `name` in a property reference. Effects and precedence can differ by target; each target page documents its contract.

## Databricks Lakeflow (`databricks-lakeflow`)

Lakeflow groups datasets into pipelines by their resolved `jobs` value. Pipeline
and orchestration job dependencies are derived from modeled source references
and dimension lookups and recorded in the manifest. Each orchestration job
triggers only its own processing pipeline and managed ingestions. Ingestion is
grouped by model job plus UC connection; no job refreshes another job's
pipeline. Each pipeline's compute is resolved from the cluster reference nested
in the model job property.

| Property / model field | Where and current values | Effect in this target |
| --- | --- | --- |
| `jobs` | Entity or folder. Current load values: `sales_daily`, `sales_weekly`. | Required grouping and orchestration boundary for datasets. Its `displayName` names the pipeline and load job. Cross-job source dependencies are retained in the manifest and ordered by the local/CI runner. |
| `schedules` | Nested in a `jobs` property value; `daily`, `weekly`. | Sets the schedule on the generated orchestration job. Schedules remain paused unless the bundle variable enables them. |
| `cluster` | Nested in a `jobs` property value; `serverless`, `small`, `extra_small`. Current load jobs use `extra_small`. | Selects per-pipeline compute. `serverless` enables managed compute; `small` or `extra_small` emits classic pipeline `clusters` settings from that property value. The orchestration job's pipeline task does not need a separate job cluster. |
| `dataset_type` | Entity or folder. Values: `materialized_view`, `streaming_table`. Required for each public dataset. | Selects the native Lakeflow dataset type. An entity value overrides the closest folder value. |
| `write_mode` | Entity or folder. Values: `overwrite`, `merge`, `append`. | Selects snapshot/MV behavior, native AUTO CDC merge behavior, or append-stream behavior. Unsupported combinations fail generation. |
| `extract_mode` | External source entry. Values: `full`, `delta`, `query`. | Selects a full snapshot, query-based snapshot, or managed query-based incremental ingestion when the source is a supported physical table. |
| `extract_column` | Property on a source mapping; current cursor fields include `ModifiedDate`, `ModifiedAt`, `modifiedat` and `MODIFIEDAT`. | Provides the mapped cursor required for managed `extract_mode=delta`. |
| `sequence_by` | Entity or folder; value must name a modeled column. | Sets the ordering column for streaming-table AUTO CDC. It is valid only for a streaming table using `write_mode=merge`. |
| `delete_condition` | Entity or folder; expression interpreted by the Lakeflow CDC flow. | Configures delete handling for an ordered CDC feed. It requires `sequence_by`; snapshots do not infer deletes from this property. |
| Attribute `isBusinessKey` and `history` | Attribute model fields (`SCD0`, `SCD1`, `SCD2`). | Supply AUTO CDC keys and history behavior. Only SCD2-marked attributes create historical versions. |
| Attribute `attribute_type=SK` | Attribute property. | Marks a surrogate key. Lakeflow derives deterministic `BIGINT` keys from the business key and version start; it does not use identity columns. |
| `data_retention`, `business_area`, `tags`, `table_properties`, `data_layout`, `enable_type_widening`, `column_mapping_mode`, `target`, attribute `sensitive` | Entity, folder, attribute, or zone according to the property's model scope. | **No effect in the current Lakeflow generator.** It does not emit these table/column tags or Delta table properties. |

The sample's explicit append example is `StockMovement`: its Stage and Core
entities use `write_mode=append` and `dataset_type=streaming_table`; the source
uses managed PostgreSQL delta ingestion with `modifiedat` as its cursor. This
assumes the source is append-only. Managed delta ingestion tracks a cursor, but
does not by itself prove that source rows are immutable or that hard deletes
are represented. Confirm that contract against the fixture before relying on
append semantics.
