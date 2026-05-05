# Properties Reference

This page summarizes properties that are interpreted by active sample targets.
Target architecture documents remain the source of truth for detailed behavior.

## Databricks Target

The Databricks target interprets these properties:

| Property | Scope | Output impact |
|---|---|---|
| `target` | zone | Selects zones for Databricks output. |
| `jobs` | entity and folder | Groups entities into load jobs. |
| `schedules` | property value referenced by `jobs` | Adds Quartz cron schedules to generated jobs. |
| `cluster` | property value referenced by `jobs` | Selects the Databricks cluster variable for generated jobs. |
| `business_area` | entity and folder | Emits business-area metadata as Databricks table tags. |
| `write_mode` | entity and inherited folder properties | Controls DML write behavior such as `merge`, `overwrite`, or `append`. |
| `extract_mode` | source and mapping properties | Controls extraction behavior and delta column handling. |
| `table_properties` | entity and folder | Emits Delta table properties such as column mapping or type widening. |
| `data_retention` | entity and inherited folder properties | Emits Delta retention properties. |
| `attribute_type=sk` | attribute | Marks surrogate key columns. |

See [Databricks Architecture](../../Generate/databricks/ARCHITECTURE.md).

## Power BI Tabular Target

The Power BI target intentionally has a narrow property surface:

| Property | Scope | Output impact |
|---|---|---|
| `target` | zone | Includes zones where `target=powerbi`. |

See [Power BI Tabular Architecture](../../Generate/powerbi-tabular/ARCHITECTURE.md).

## Documentation Target

The documentation target renders most metadata descriptively. It does not use
custom properties to filter entities.

| Property | Scope | Output impact |
|---|---|---|
| entity/source/attribute properties | model metadata | Rendered into generated documentation pages. |
| `attribute_type=sk` | attribute | Marks surrogate keys in attribute tables. |
| zone `target` | zone | Displayed as target information. |

See [Documentation Target Architecture](../../Generate/docs/ARCHITECTURE.md).
