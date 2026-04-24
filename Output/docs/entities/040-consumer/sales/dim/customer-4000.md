

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
      <div style="font-size:24px; font-weight:bold;">1</div>
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
| Zone | Consumer Tabular Layer |
| Product | All Entities for Sales |
| Module | Dim |
| Entity ID | 4000 |
| Kind | Dimension |
| Path | `040-Consumer/Sales/Dim/Customer` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Customer dimension with personal and address information

## Entity Properties


<dl>
<dt>jobs</dt>
  <dd>sales_daily</dd>
<dt>write_mode</dt>
  <dd>merge</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CustomerSID` | long (SID) | no | yes | no | HistoryType.SCD1 | Customer surrogate key | N/A |
| 2 | `First Name` | string (ID) | yes | no | no | HistoryType.SCD1 | First name of the customer | N/A |
| 3 | `Display Name` | string (Name) | yes | no | no | HistoryType.SCD1 | Customer display name | N/A |
| 4 | `Last Name` | string (Name) | yes | no | no | HistoryType.SCD1 | Customer last name | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Customer (model)</summary>
  <p><strong>Reference:</strong> 3000 | <strong>Zone:</strong> Curated Analytics Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 3000</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>Customer SID</code></td><td><code>CustomerSID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>First Name</code></td><td><code>FirstName</code></td><td>string</td><td>True</td></tr>
    <tr><td><code>Display Name</code></td><td><code>DisplayName</code></td><td>string</td><td>True</td></tr>
    <tr><td><code>Last Name</code></td><td><code>LastName</code></td><td>string</td><td>True</td></tr>
    
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
  <summary>Upstream Relationships (1)</summary>
  
  <ul>
  <li><strong>Sales Order</strong> (Consumer Tabular Layer): Customer SID->Customer SID</li>
  
  </ul>
  
</details>

## Transformations


_No transformation steps registered._




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.