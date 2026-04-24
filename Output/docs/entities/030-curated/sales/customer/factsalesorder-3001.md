

# Sales Order (FactSalesOrder)


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
      <div style="font-size:24px; font-weight:bold;">2</div>
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
| Zone | Curated Analytics Layer |
| Product | All Entities for Sales |
| Module | Customer module |
| Entity ID | 3001 |
| Kind | Fact |
| Path | `030-Curated/Sales/Customer/FactSalesOrder` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Fact table with sales orders

## Entity Properties


<dl>
<dt>write_mode</dt>
  <dd>overwrite</dd>
<dt>data_retention</dt>
  <dd>7_days</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CustomerSID` | long (SID) | no | no | no | HistoryType.SCD1 | Customer surrogate key | N/A |
| 2 | `ShipDateID` | int (ID) | no | no | no | HistoryType.SCD1 | Ship date as integer | N/A |
| 3 | `TotalCosts` | double (Currency) | yes | no | no | HistoryType.SCD1 | Costs of sales orders | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Sales_Order_Header (model)</summary>
  <p><strong>Reference:</strong> 1008 | <strong>Zone:</strong> Staging Data Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Order | <strong>Location:</strong> 1008</p>
  
  
  <p>No column mapping defined.</p>
  
</details>
<details>
  <summary>Sales_Order_Detail (model)</summary>
  <p><strong>Reference:</strong> 1009 | <strong>Zone:</strong> Staging Data Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Order | <strong>Location:</strong> 1009</p>
  
  
  <p>No column mapping defined.</p>
  
</details>

</div>


## Relationships

<details open>
  <summary>Downstream Relationships (2)</summary>
  
  <ul>
  <li><strong>Customer</strong> (Curated Analytics Layer): CustomerSID->CustomerSID</li>
  <li><strong>Date</strong> (Curated Analytics Layer): ShipDateID->DateID</li>
  
  </ul>
  
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
    <td>transform_sales_orders</td>
    <td>
      
        `source`=FactSalesOrder.py
      
    </td>
  </tr>
  <tr>
    <td>2</td>
    <td>TransformationKind.BUILTIN</td>
    <td>lookup_dimensions</td>
    <td>
      
        N/A
      
    </td>
  </tr>
  
  </tbody>
</table>




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.