

# Customer (Customer)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">13</div>
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
| Zone | Staging Data Layer |
| Product | All Entities for Sales |
| Module | Customer module |
| Entity ID | 1012 |
| Kind | Entity |
| Path | `010-Stage/Sales/Customer/Customer` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Core customer information entity

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
| 1 | `KundenID` | int (ID) | no | yes | no | HistoryType.SCD1 | Unique key for the customer | `data_layout`=liquid_clustering |
| 2 | `NamensTyp` | bit (Flag) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 3 | `Titel` | string (Name) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 4 | `Vorname` | string (Name) | no | no | no | HistoryType.SCD1 | N/A | `sensitive`=True |
| 5 | `Nameszusatz1` | string (Name) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 6 | `Nachname` | string (Name) | no | no | no | HistoryType.SCD2 | N/A | N/A |
| 7 | `Namenszusatz2` | string (Name) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 8 | `Firma` | string (Name) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 9 | `Verkaeufer` | string (Name) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 10 | `Email` | string (Email) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 11 | `Telefon` | string (Description) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 12 | `GeaendertAm` | datetime (CreationDate) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 13 | `KundenName` | string (Name) | no | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Adventure Works Demo Database (external)</summary>
  <p><strong>Reference:</strong> AdventureWorks | <strong>Zone:</strong> Raw Data Layer | <strong>Alias:</strong> Customer_DE</p>
  <p><strong>Product/Module:</strong> - / - | <strong>Location:</strong> [SalesLT].[Customer_DE]</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>KundenID</code></td><td><code>KundenID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>NamensTyp</code></td><td><code>NamensTyp</code></td><td>bit</td><td>False</td></tr>
    <tr><td><code>Titel</code></td><td><code>Titel</code></td><td>nvarchar(8)</td><td>True</td></tr>
    <tr><td><code>Vorname</code></td><td><code>Vorname</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>Nameszusatz1</code></td><td><code>Nameszusatz1</code></td><td>nvarchar(50)</td><td>True</td></tr>
    <tr><td><code>Nachname</code></td><td><code>Nachname</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>Namenszusatz2</code></td><td><code>Namenszusatz2</code></td><td>nvarchar(10)</td><td>True</td></tr>
    <tr><td><code>Firma</code></td><td><code>Firma</code></td><td>nvarchar(128)</td><td>True</td></tr>
    <tr><td><code>Verkaeufer</code></td><td><code>Verkaeufer</code></td><td>nvarchar(256)</td><td>True</td></tr>
    <tr><td><code>Email</code></td><td><code>Email</code></td><td>nvarchar(50)</td><td>True</td></tr>
    <tr><td><code>Telefon</code></td><td><code>Telefon</code></td><td>nvarchar(25)</td><td>True</td></tr>
    <tr><td><code>PasswordHash</code></td><td><code>PasswordHash</code></td><td>varchar(128)</td><td>False</td></tr>
    <tr><td><code>PasswordSalt</code></td><td><code>PasswordSalt</code></td><td>varchar(10)</td><td>False</td></tr>
    <tr><td><code>rowguid</code></td><td><code>rowguid</code></td><td>uniqueidentifier</td><td>False</td></tr>
    <tr><td><code>GeaendertAm</code></td><td><code>GeaendertAm</code></td><td>datetime</td><td>False</td></tr>
    
    </tbody>
  </table>
  
</details>
<details>
  <summary>Adventure Works Demo Database (external)</summary>
  <p><strong>Reference:</strong> AdventureWorks | <strong>Zone:</strong> Raw Data Layer | <strong>Alias:</strong> Customer_EN</p>
  <p><strong>Product/Module:</strong> - / - | <strong>Location:</strong> [SalesLT].[Customer_EN]</p>
  
  <p><strong>Source Properties:</strong> `extract_mode`=delta</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>KundenID</code></td><td><code>CustomerID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>NamensTyp</code></td><td><code>NameStyle</code></td><td>bit</td><td>False</td></tr>
    <tr><td><code>Titel</code></td><td><code>Title</code></td><td>nvarchar(8)</td><td>True</td></tr>
    <tr><td><code>Vorname</code></td><td><code>FirstName</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>Nameszusatz1</code></td><td><code>MiddleName</code></td><td>nvarchar(50)</td><td>True</td></tr>
    <tr><td><code>Nachname</code></td><td><code>LastName</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>Namenszusatz2</code></td><td><code>Suffix</code></td><td>nvarchar(10)</td><td>True</td></tr>
    <tr><td><code>Firma</code></td><td><code>CompanyName</code></td><td>nvarchar(128)</td><td>True</td></tr>
    <tr><td><code>Verkaeufer</code></td><td><code>SalesPerson</code></td><td>nvarchar(256)</td><td>True</td></tr>
    <tr><td><code>Email</code></td><td><code>EmailAddress</code></td><td>nvarchar(50)</td><td>True</td></tr>
    <tr><td><code>Telefon</code></td><td><code>Phone</code></td><td>nvarchar(25)</td><td>True</td></tr>
    <tr><td><code>PasswordHash</code></td><td><code>PasswordHash</code></td><td>varchar(128)</td><td>False</td></tr>
    <tr><td><code>PasswordSalt</code></td><td><code>PasswordSalt</code></td><td>varchar(10)</td><td>False</td></tr>
    <tr><td><code>rowguid</code></td><td><code>rowguid</code></td><td>uniqueidentifier</td><td>False</td></tr>
    <tr><td><code>GeaendertAm</code></td><td><code>ModifiedDate</code></td><td>datetime</td><td>False</td></tr>
    
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