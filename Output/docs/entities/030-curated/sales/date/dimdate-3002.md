

# Date (DimDate)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">5</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">1</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Business Keys</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">0</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Sources</div>
    </td>
  </tr><tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">1</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Relationships</div>
    </td>
  </tr>
</table>

| Field | Value |
| --- | --- |
| Zone | Curated Analytics Layer |
| Product | All Entities for Sales |
| Module | Date |
| Entity ID | 3002 |
| Kind | Dimension |
| Path | `030-Curated/Sales/Date/DimDate` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Date dimension with calendar attributes

## Entity Properties


<dl>
<dt>jobs</dt>
  <dd>sales_daily</dd>
<dt>write_mode</dt>
  <dd>merge</dd>
<dt>data_retention</dt>
  <dd>7_days</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DateSID` | long (SID) | no | no | yes | HistoryType.SCD1 | Date surrogate key | `attribute_type`=SK |
| 2 | `DateID` | integer (ID) | no | yes | no | HistoryType.SCD1 | Calendar date ID | N/A |
| 3 | `Date` | datetime (ID) | no | no | no | HistoryType.SCD1 | Calendar date | N/A |
| 4 | `CalendarYear` | string (ID) | no | no | no | HistoryType.SCD1 | Calendar year label | N/A |
| 5 | `MonthName` | string (Name) | no | no | no | HistoryType.SCD1 | English month name | N/A |



## Sources


_No sources defined._


## Relationships

<details open>
  <summary>Downstream Relationships (0)</summary>
  
  <p>No outgoing relationships declared.</p>
  
</details>

<details>
  <summary>Upstream Relationships (1)</summary>
  
  <ul>
  <li><strong>Sales Order</strong> (Curated Analytics Layer): ShipDateID->DateID</li>
  
  </ul>
  
</details>

## Transformations


<table>
  <thead><tr><th>Step</th><th>Kind</th><th>Name</th><th>Details</th></tr></thead>
  <tbody>
  <tr>
    <td>1</td>
    <td>TransformationKind.FUNCTION</td>
    <td>transform_dimdate</td>
    <td>
      
        `source`=GenerateDates.py
      
    </td>
  </tr>
  
  </tbody>
</table>




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.