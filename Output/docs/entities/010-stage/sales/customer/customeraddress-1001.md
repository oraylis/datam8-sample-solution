

# Customer_Address (CustomerAddress)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">3</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">2</div>
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
| Zone | Staging Data Layer |
| Product | All Entities for Sales |
| Module | Customer module |
| Entity ID | 1001 |
| Kind | Entity |
| Path | `010-Stage/Sales/Customer/CustomerAddress` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Customer address relationship entity

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
| 1 | `CustomerID` | int (ID) | yes | yes | no | HistoryType.SCD1 | N/A | `data_layout`=hive_partitioning |
| 2 | `AddressID` | int (ID) | yes | yes | no | HistoryType.SCD1 | N/A | `data_layout`=liquid_clustering |
| 3 | `AddressType` | string (Description) | no | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Adventure Works Demo Database (external)</summary>
  <p><strong>Reference:</strong> AdventureWorks | <strong>Zone:</strong> Raw Data Layer | <strong>Alias:</strong> CustomerAddress</p>
  <p><strong>Product/Module:</strong> - / - | <strong>Location:</strong> SELECT * FROM [SalesLT].[CustomerAddress] WHERE CustomerID > 1</p>
  
  <p><strong>Source Properties:</strong> `extract_mode`=query</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>CustomerID</code></td><td><code>CustomerID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>AddressID</code></td><td><code>AddressID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>AddressType</code></td><td><code>AddressType</code></td><td>nvarchar(50)</td><td>True</td></tr>
    <tr><td><code>rowguid</code></td><td><code>rowguid</code></td><td>uniqueidentifier</td><td>False</td></tr>
    <tr><td><code>ModifiedDate</code></td><td><code>ModifiedDate</code></td><td>datetime</td><td>False</td></tr>
    
    </tbody>
  </table>
  
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


_No transformation steps registered._




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.