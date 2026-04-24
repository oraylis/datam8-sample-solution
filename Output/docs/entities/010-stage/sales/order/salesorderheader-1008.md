

# Sales_Order_Header (SalesOrderHeader)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">22</div>
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
| Zone | Staging Data Layer |
| Product | All Entities for Sales |
| Module | Order module |
| Entity ID | 1008 |
| Kind | Entity |
| Path | `010-Stage/Sales/Order/SalesOrderHeader` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Sales order header information entity

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
| 1 | `SalesOrderID` | int (ID) | no | yes | no | HistoryType.SCD1 | N/A | N/A |
| 2 | `RevisionNumber` | int (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 3 | `OrderDate` | datetime (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 4 | `DueDate` | datetime (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 5 | `ShipDate` | datetime (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 6 | `Status` | int (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 7 | `OnlineOrderFlag` | bit (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 8 | `SalesOrderNumber` | string (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 9 | `PurchaseOrderNumber` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 10 | `AccountNumber` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 11 | `CustomerID` | int (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 12 | `ShipToAddressID` | int (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 13 | `BillToAddressID` | int (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 14 | `ShipMethod` | string (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 15 | `CreditCardApprovalCode` | string(15) (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 16 | `SubTotal` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 17 | `TaxAmt` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 18 | `Freight` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 19 | `TotalDue` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 20 | `Comment` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 21 | `rowguid` | uniqueidentifier (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 22 | `ModifiedDate` | datetime (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Adventure Works Demo Database (external)</summary>
  <p><strong>Reference:</strong> AdventureWorks | <strong>Zone:</strong> Raw Data Layer | <strong>Alias:</strong> SalesOrderHeader</p>
  <p><strong>Product/Module:</strong> - / - | <strong>Location:</strong> [SalesLT].[SalesOrderHeader]</p>
  
  <p><strong>Source Properties:</strong> `extract_mode`=delta</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>SalesOrderID</code></td><td><code>SalesOrderID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>RevisionNumber</code></td><td><code>RevisionNumber</code></td><td>tinyint</td><td>False</td></tr>
    <tr><td><code>OrderDate</code></td><td><code>OrderDate</code></td><td>datetime</td><td>False</td></tr>
    <tr><td><code>DueDate</code></td><td><code>DueDate</code></td><td>datetime</td><td>False</td></tr>
    <tr><td><code>ShipDate</code></td><td><code>ShipDate</code></td><td>datetime</td><td>True</td></tr>
    <tr><td><code>Status</code></td><td><code>Status</code></td><td>tinyint</td><td>False</td></tr>
    <tr><td><code>OnlineOrderFlag</code></td><td><code>OnlineOrderFlag</code></td><td>bit</td><td>False</td></tr>
    <tr><td><code>SalesOrderNumber</code></td><td><code>SalesOrderNumber</code></td><td>nvarchar(25)</td><td>False</td></tr>
    <tr><td><code>PurchaseOrderNumber</code></td><td><code>PurchaseOrderNumber</code></td><td>nvarchar(25)</td><td>True</td></tr>
    <tr><td><code>AccountNumber</code></td><td><code>AccountNumber</code></td><td>nvarchar(15)</td><td>True</td></tr>
    <tr><td><code>CustomerID</code></td><td><code>CustomerID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>ShipToAddressID</code></td><td><code>ShipToAddressID</code></td><td>int</td><td>True</td></tr>
    <tr><td><code>BillToAddressID</code></td><td><code>BillToAddressID</code></td><td>int</td><td>True</td></tr>
    <tr><td><code>ShipMethod</code></td><td><code>ShipMethod</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>CreditCardApprovalCode</code></td><td><code>CreditCardApprovalCode</code></td><td>varchar(15)</td><td>True</td></tr>
    <tr><td><code>SubTotal</code></td><td><code>SubTotal</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>TaxAmt</code></td><td><code>TaxAmt</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>Freight</code></td><td><code>Freight</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>TotalDue</code></td><td><code>TotalDue</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>Comment</code></td><td><code>Comment</code></td><td>nvarchar(200)</td><td>True</td></tr>
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