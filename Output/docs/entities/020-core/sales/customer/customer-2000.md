

# Customer (Customer)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">4</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">1</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Business Keys</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">2</div>
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
| Entity ID | 2000 |
| Kind | Entity |
| Path | `020-Core/Sales/Customer/Customer` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

_No description provided._

## Entity Properties


<dl>
<dt>jobs</dt>
  <dd>sales_weekly</dd>
<dt>write_mode</dt>
  <dd>overwrite</dd>
<dt>data_retention</dt>
  <dd>7_days</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `KundenNummer` | int (ID) | no | yes | no | HistoryType.SCD1 | Unique key for the customer | N/A |
| 2 | `Vorname` | string (Name) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 3 | `Nachname` | string (Name) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 4 | `AddressType` | string (Address) | yes | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Customer (model)</summary>
  <p><strong>Reference:</strong> 1012 | <strong>Zone:</strong> Staging Data Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 1012</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>CustomerID</code></td><td><code>KundenID</code></td><td>N/A</td><td>N/A</td></tr>
    <tr><td><code>FirstName</code></td><td><code>Vorname</code></td><td>N/A</td><td>N/A</td></tr>
    <tr><td><code>LastName</code></td><td><code>Nachname</code></td><td>N/A</td><td>N/A</td></tr>
    <tr><td><code>CompanyName</code></td><td><code>Firma</code></td><td>N/A</td><td>N/A</td></tr>
    <tr><td><code>CustomerEMail</code></td><td><code>EmailAddress</code></td><td>N/A</td><td>N/A</td></tr>
    <tr><td><code>DisplayName</code></td><td><code>Verkaeufer</code></td><td>N/A</td><td>N/A</td></tr>
    
    </tbody>
  </table>
  
</details>
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
      
        `source`=CustomerNew.py
      
    </td>
  </tr>
  
  </tbody>
</table>




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.