

# Customer (DimCustomer)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">10</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">1</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Business Keys</div>
    </td>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">3</div>
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
| Module | Customer module |
| Entity ID | 3000 |
| Kind | Dimension |
| Path | `030-Curated/Sales/Customer/DimCustomer` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Customer dimension with personal and address information

## Entity Properties


<dl>
<dt>write_mode</dt>
  <dd>merge</dd>
<dt>data_retention</dt>
  <dd>7_days</dd>

</dl>




## Attribute Catalogue


| # | Attribute | Type | Nullable | BK | SK | History | Description | Properties |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `CustomerSID` | long (SID) | no | no | yes | HistoryType.SCD1 | Customer surrogate key | `attribute_type`=SK |
| 2 | `CustomerID` | int (ID) | yes | yes | no | HistoryType.SCD1 | Original customer identifier | N/A |
| 3 | `DisplayName` | string (Name) | yes | no | no | HistoryType.SCD2 | Customer display name | N/A |
| 4 | `FirstName` | string (Name) | yes | no | no | HistoryType.SCD2 | Customer first name | N/A |
| 5 | `LastName` | string (Name) | yes | no | no | HistoryType.SCD2 | Customer last name | N/A |
| 6 | `AddressType` | string (Text) | yes | no | no | HistoryType.SCD1 | Type of customer address (Home, Business, etc.) | N/A |
| 7 | `Address` | string (Text) | yes | no | no | HistoryType.SCD1 | Full address line | N/A |
| 8 | `PostalCode` | string (Text) | yes | no | no | HistoryType.SCD1 | Address postal code | N/A |
| 9 | `CityName` | string (Name) | yes | no | no | HistoryType.SCD1 | Address city name | N/A |
| 10 | `CountryName` | string (Name) | yes | no | no | HistoryType.SCD1 | Address country name | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Customer (model)</summary>
  <p><strong>Reference:</strong> 2000 | <strong>Zone:</strong> Core Business Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 2000</p>
  
  
  <p>No column mapping defined.</p>
  
</details>
<details>
  <summary>CustomerAddress (model)</summary>
  <p><strong>Reference:</strong> 2001 | <strong>Zone:</strong> Core Business Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Customer | <strong>Location:</strong> 2001</p>
  
  
  <p>No column mapping defined.</p>
  
</details>
<details>
  <summary>Address (model)</summary>
  <p><strong>Reference:</strong> 2002 | <strong>Zone:</strong> Core Business Layer | <strong>Alias:</strong> -</p>
  <p><strong>Product/Module:</strong> Sales / Other | <strong>Location:</strong> 2002</p>
  
  
  <p>No column mapping defined.</p>
  
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
  <li><strong>Sales Order</strong> (Curated Analytics Layer): CustomerSID->CustomerSID</li>
  
  </ul>
  
</details>

## Transformations


<table>
  <thead><tr><th>Step</th><th>Kind</th><th>Name</th><th>Details</th></tr></thead>
  <tbody>
  <tr>
    <td>1</td>
    <td>TransformationKind.FUNCTION</td>
    <td>transform_customer_dimension</td>
    <td>
      
        `source`=DimCustomer.py
      
    </td>
  </tr>
  
  </tbody>
</table>




---


[Return to the documentation overview](../../../../index.md) or open the lineage diagram at `../../../../diagrams/entity-relationships.drawio`.