

# Sales Order (Sales Order)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">3</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">0</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Business Keys</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">3</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Sources</div>
    </td>
  </tr><tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">2</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Relationships</div>
    </td>
  </tr>
</table>

| Field | Value |
| --- | --- |
| Zone | Consumer Tabular Layer |
| Product | All Entities for Sales |
| Module | Fact |
| Entity ID | 4001 |
| Kind | Fact |
| Path | `040-Consumer/Sales/Fact/Sales Order` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Fact table with sales orders

## Entity Properties


<dl>
<dt>jobs</dt>
  <dd>sales_daily</dd>
<dt>write_mode</dt>
  <dd>overwrite</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Customer SID` | long (SID) | no | no | no | HistoryType.SCD1 | Customer surrogate key | N/A |
| 2 | `Ship Date ID` | int (ID) | no | no | no | HistoryType.SCD1 | Ship date as integer | N/A |
| 3 | `Total Costs` | double (Currency) | yes | no | no | HistoryType.SCD1 | Costs of sales orders | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Sales Order (model)</summary>
  <p><strong>Reference:</strong> 3001 | <strong>Zone:</strong> Curated Analytics Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 3001</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>Customer SID</code></td><td><code>CustomerSID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>Ship Date ID</code></td><td><code>ShipDateID</code></td><td>int</td><td>True</td></tr>
    <tr><td><code>Total Costs</code></td><td><code>TotalCosts</code></td><td>double</td><td>True</td></tr>
    
    </tbody>
  </table>
  
</details>
<details>
  <summary>Customer (model)</summary>
  <p><strong>Reference:</strong> 4000 | <strong>Zone:</strong> Consumer Tabular Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Dim | <strong>Location:</strong> 4000</p>
  
  
  <p>No column mapping defined.</p>
  
</details>
<details>
  <summary>Date (model)</summary>
  <p><strong>Reference:</strong> 4003 | <strong>Zone:</strong> Consumer Tabular Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Dim | <strong>Location:</strong> 4003</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>Ship Date ID</code></td><td><code>Date SID</code></td><td>long</td><td>False</td></tr>
    
    </tbody>
  </table>
  
</details>

</div>


## Relationships

<details open>
  <summary>Downstream Relationships (2)</summary>
  
  <ul>
  <li><strong>Customer</strong> (Consumer Tabular Layer): Customer SID->Customer SID</li>
  <li><strong>Date</strong> (Consumer Tabular Layer): Ship Date ID->Date ID</li>
  
  </ul>
  
</details>

<details>
  <summary>Upstream Relationships (0)</summary>
  
  <p>No upstream relationships declared.</p>
  
</details>

## Transformations


_No transformation steps registered._




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.