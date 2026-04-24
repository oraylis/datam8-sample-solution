

# CustomerAddress (CustomerAddress)


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
      <div style="font-size:24px; font-weight:bold;">1</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Sources</div>
    </td>
  </tr><tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">0</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Relationships</div>
    </td>
  </tr>
</table>

| Field | Value |
| --- | --- |
| Zone | Core Business Layer |
| Product | All Entities for Sales |
| Module | Customer module |
| Entity ID | 2001 |
| Kind | Entity |
| Path | `020-Core/Sales/Customer/CustomerAddress` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Core customer address relationship entity

## Entity Properties


<dl>
<dt>jobs</dt>
  <dd>sales_daily</dd>
<dt>write_mode</dt>
  <dd>overwrite</dd>
<dt>data_retention</dt>
  <dd>7_days</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `_CustomerAddressBK` | string (ID) | no | yes | no | HistoryType.SCD1 | N/A | N/A |
| 2 | `_CustomerAddressSID` | long (SID) | no | no | yes | HistoryType.SCD1 | N/A | `attribute_type`=SK |
| 3 | `AddressID` | int (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 4 | `CustomerID` | int (ID) | no | no | no | HistoryType.SCD0 | N/A | N/A |
| 5 | `AddressType` | string (Text) | no | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Customer_Address (model)</summary>
  <p><strong>Reference:</strong> 1001 | <strong>Zone:</strong> Staging Data Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 1001</p>
  
  
  <p>No column mapping defined.</p>
  
</details>

</div>


## Relationships

<details open>
  <summary>Downstream Relationships (0)</summary>
  
  <p>No outgoing relationships declared.</p>
  
</details>

<details>
  <summary>Upstream Relationships (0)</summary>
  
  <p>No upstream relationships declared.</p>
  
</details>

## Transformations


<table>
  <thead><tr><th>Step</th><th>Kind</th><th>Name</th><th>Details</th></tr></thead>
  <tbody>
  <tr>
    <td>1</td>
    <td>TransformationKind.FUNCTION</td>
    <td>transform_first_step</td>
    <td>
      
        `source`=CustomerAddress.py
      
    </td>
  </tr>
  
  </tbody>
</table>




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.