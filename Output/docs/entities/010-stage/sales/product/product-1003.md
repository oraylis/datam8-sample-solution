

# Product (Product)


<table>
  <tr>
    <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">17</div>
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
| Module | Product module |
| Entity ID | 1003 |
| Kind | Entity |
| Path | `010-Stage/Sales/Product/Product` |

Generated 2026-04-14T10:38:04.235275+00:00 from schema 2.0.0.

## Description

Product catalog entity

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
| 1 | `ProductID` | int (ID) | no | yes | no | HistoryType.SCD1 | N/A | N/A |
| 2 | `Name` | string (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 3 | `ProductNumber` | string (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 4 | `Color` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 5 | `StandardCost` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 6 | `ListPrice` | decimal(19,4) (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 7 | `Size` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 8 | `Weight` | decimal(8,2) (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 9 | `ProductCategoryID` | int (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 10 | `ProductModelID` | int (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 11 | `SellStartDate` | datetime (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 12 | `SellEndDate` | datetime (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 13 | `DiscontinuedDate` | datetime (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 14 | `ThumbNailPhoto` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 15 | `ThumbnailPhotoFileName` | string (ID) | yes | no | no | HistoryType.SCD1 | N/A | N/A |
| 16 | `rowguid` | uniqueidentifier (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |
| 17 | `ModifiedDate` | datetime (ID) | no | no | no | HistoryType.SCD1 | N/A | N/A |



## Sources


<div class="source-list">
<details>
  <summary>Adventure Works Demo Database (external)</summary>
  <p><strong>Reference:</strong> AdventureWorks | <strong>Zone:</strong> Raw Data Layer | <strong>Alias:</strong> Product</p>
  <p><strong>Product/Module:</strong> - / - | <strong>Location:</strong> [SalesLT].[Product]</p>
  
  <p><strong>Source Properties:</strong> `extract_mode`=delta</p>
  
  
  <table>
    <thead><tr><th>Target</th><th>Source</th><th>Source Type</th><th>Nullable</th></tr></thead>
    <tbody>
    <tr><td><code>ProductID</code></td><td><code>ProductID</code></td><td>int</td><td>False</td></tr>
    <tr><td><code>Name</code></td><td><code>Name</code></td><td>nvarchar(50)</td><td>False</td></tr>
    <tr><td><code>ProductNumber</code></td><td><code>ProductNumber</code></td><td>nvarchar(25)</td><td>False</td></tr>
    <tr><td><code>Color</code></td><td><code>Color</code></td><td>nvarchar(15)</td><td>True</td></tr>
    <tr><td><code>StandardCost</code></td><td><code>StandardCost</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>ListPrice</code></td><td><code>ListPrice</code></td><td>money</td><td>False</td></tr>
    <tr><td><code>Size</code></td><td><code>Size</code></td><td>nvarchar(5)</td><td>True</td></tr>
    <tr><td><code>Weight</code></td><td><code>Weight</code></td><td>decimal(8,2)</td><td>True</td></tr>
    <tr><td><code>ProductCategoryID</code></td><td><code>ProductCategoryID</code></td><td>int</td><td>True</td></tr>
    <tr><td><code>ProductModelID</code></td><td><code>ProductModelID</code></td><td>int</td><td>True</td></tr>
    <tr><td><code>SellStartDate</code></td><td><code>SellStartDate</code></td><td>datetime</td><td>False</td></tr>
    <tr><td><code>SellEndDate</code></td><td><code>SellEndDate</code></td><td>datetime</td><td>True</td></tr>
    <tr><td><code>DiscontinuedDate</code></td><td><code>DiscontinuedDate</code></td><td>datetime</td><td>True</td></tr>
    <tr><td><code>ThumbNailPhoto</code></td><td><code>ThumbNailPhoto</code></td><td>varbinary</td><td>True</td></tr>
    <tr><td><code>ThumbnailPhotoFileName</code></td><td><code>ThumbnailPhotoFileName</code></td><td>nvarchar(50)</td><td>True</td></tr>
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