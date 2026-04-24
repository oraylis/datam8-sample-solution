
# ORAYLISDatabricksSample - Metadata Documentation

Generated at **2026-04-14T10:38:04.235275+00:00** (schema 2.0.0).

## Snapshot


<table>
  <tr>
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">21</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Entities</div>
    </td>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">145</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Attributes</div>
    </td>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">4</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Zones</div>
    </td>
    
  </tr><tr>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">11</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">External Sources</div>
    </td>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">13</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Modeled Sources</div>
    </td>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">4</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Relationships</div>
    </td>
    
  </tr><tr>
    
  <td style="padding:12px; border:1px solid #ddd;">
      <div style="font-size:24px; font-weight:bold;">19</div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:0.05em;">Entities with Description</div>
    </td>
    
  
  </tr>
</table>

**Top Properties:** `write_mode` (20), `jobs` (19), `data_retention` (17)

## Zone Overview

<details open>
  <summary><strong>Staging Data Layer</strong> (10 entities)</summary>
  <p><em>Folder:</em> 010-Stage | <em>Target:</em> bronze</p>
  
  <ul>
    <li>All Entities for Sales / Customer module - 2 entities</li>
    <li>All Entities for Sales / Order module - 2 entities</li>
    <li>All Entities for Sales / Other module - 1 entities</li>
    <li>All Entities for Sales / Product module - 5 entities</li>
  </ul>
  
</details>
<details open>
  <summary><strong>Core Business Layer</strong> (3 entities)</summary>
  <p><em>Folder:</em> 020-Core | <em>Target:</em> silver</p>
  
  <ul>
    <li>All Entities for Sales / Customer module - 2 entities</li>
    <li>All Entities for Sales / Other module - 1 entities</li>
  </ul>
  
</details>
<details open>
  <summary><strong>Curated Analytics Layer</strong> (4 entities)</summary>
  <p><em>Folder:</em> 030-Curated | <em>Target:</em> gold</p>
  
  <ul>
    <li>All Entities for Sales / Customer module - 3 entities</li>
    <li>All Entities for Sales / Date - 1 entities</li>
  </ul>
  
</details>
<details open>
  <summary><strong>Consumer Tabular Layer</strong> (4 entities)</summary>
  <p><em>Folder:</em> 040-Consumer | <em>Target:</em> platin</p>
  
  <ul>
    <li>All Entities for Sales / Dim - 3 entities</li>
    <li>All Entities for Sales / Fact - 1 entities</li>
  </ul>
  
</details>


## Entity Catalog

Use the links below to jump directly to the entity specific documentation.

| Zone | Product | Module | Entity | Attr. | BK | Sources | Rel. | Description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Consumer Tabular Layer | All Entities for Sales | Dim | [Customer](entities/040-consumer/sales/dim/customer-4000.md) | 4 | 1 | 1 | 1 | Customer dimension with personal and address information |
| Consumer Tabular Layer | All Entities for Sales | Dim | [Date](entities/040-consumer/sales/dim/date-4003.md) | 4 | 1 | 1 | 1 | Date dimension exposed for reporting |
| Consumer Tabular Layer | All Entities for Sales | Dim | [Measure](entities/040-consumer/sales/dim/measure-4002.md) | 1 | 0 | 0 | 0 | N/A |
| Consumer Tabular Layer | All Entities for Sales | Fact | [Sales Order](entities/040-consumer/sales/fact/sales-order-4001.md) | 3 | 0 | 3 | 2 | Fact table with sales orders |
| Core Business Layer | All Entities for Sales | Customer module | [Customer](entities/020-core/sales/customer/customer-2000.md) | 4 | 1 | 2 | 0 | N/A |
| Core Business Layer | All Entities for Sales | Customer module | [CustomerAddress](entities/020-core/sales/customer/customeraddress-2001.md) | 5 | 1 | 1 | 0 | Core customer address relationship entity |
| Core Business Layer | All Entities for Sales | Other module | [Address](entities/020-core/sales/other/address-2002.md) | 9 | 1 | 1 | 0 | Core address dimension with location data |
| Curated Analytics Layer | All Entities for Sales | Customer module | [Customer](entities/030-curated/sales/customer/dimcustomer-3000.md) | 10 | 1 | 3 | 1 | Customer dimension with personal and address information |
| Curated Analytics Layer | All Entities for Sales | Customer module | [Date](entities/030-curated/sales/customer/dimdate-3002.md) | 5 | 1 | 0 | 0 | Date dimension with calendar attributes |
| Curated Analytics Layer | All Entities for Sales | Customer module | [Sales Order](entities/030-curated/sales/customer/factsalesorder-3001.md) | 3 | 0 | 2 | 2 | Fact table with sales orders |
| Curated Analytics Layer | All Entities for Sales | Date | [Date](entities/030-curated/sales/date/dimdate-3002.md) | 5 | 1 | 0 | 1 | Date dimension with calendar attributes |
| Staging Data Layer | All Entities for Sales | Customer module | [Customer](entities/010-stage/sales/customer/customer-1012.md) | 13 | 1 | 2 | 0 | Core customer information entity |
| Staging Data Layer | All Entities for Sales | Customer module | [Customer_Address](entities/010-stage/sales/customer/customeraddress-1001.md) | 3 | 2 | 1 | 0 | Customer address relationship entity |
| Staging Data Layer | All Entities for Sales | Order module | [Sales_Order_Detail](entities/010-stage/sales/order/salesorderdetail-1009.md) | 9 | 2 | 1 | 0 | Sales order line item details entity |
| Staging Data Layer | All Entities for Sales | Order module | [Sales_Order_Header](entities/010-stage/sales/order/salesorderheader-1008.md) | 22 | 1 | 1 | 0 | Sales order header information entity |
| Staging Data Layer | All Entities for Sales | Other module | [Address](entities/010-stage/sales/other/address-1002.md) | 9 | 1 | 1 | 0 | Address information entity |
| Staging Data Layer | All Entities for Sales | Product module | [Product](entities/010-stage/sales/product/product-1003.md) | 17 | 1 | 1 | 0 | Product catalog entity |
| Staging Data Layer | All Entities for Sales | Product module | [Product_Category](entities/010-stage/sales/product/productcategory-1004.md) | 5 | 1 | 1 | 0 | Product category hierarchy entity |
| Staging Data Layer | All Entities for Sales | Product module | [Product_Description](entities/010-stage/sales/product/productdescription-1005.md) | 4 | 1 | 1 | 0 | Product description text entity |
| Staging Data Layer | All Entities for Sales | Product module | [Product_Model](entities/010-stage/sales/product/productmodel-1006.md) | 5 | 1 | 1 | 0 | Product model information entity |
| Staging Data Layer | All Entities for Sales | Product module | [Product_Model_Product_Description](entities/010-stage/sales/product/productmodelproductdescription-1007.md) | 5 | 3 | 1 | 0 | Product model to description relationship entity |


## Diagram

The Entity Relationship diagram is available at `diagrams/entity-relationships.drawio`. Open it with [draw.io](https://www.drawio.com/) to explore the relationships visually.