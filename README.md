# DataM8 Sample Solution

This public repository owns the small AdventureWorks metadata model and its
business transformations. It supports local generation without cloud credentials.

| Target | Source | Output |
| --- | --- | --- |
| databricks | `Generate/databricks-lake` | `Output/databricks-lake/generated` |
| powerbi | `Generate/powerbi-tabular` | `Output/powerbi-tabular/generated` |
| docs | `Generate/docs` | `Output/docs` |

The large multi-source models, Lakeflow, Fabric, deployment bindings and cloud integration belong to
[DataM8 Solutions](https://github.com/oraylis/datam8-solutions). That repository
is private; its links require the corresponding access. The classic target here
remains a generate-only reference. No cloud resources are removed by this cleanup.

Use the pinned CLI with `uv sync --frozen` and
`uv run datam8 generate -s ORAYLISDatabricksSample.dm8s databricks --clean-output`.
The Generate-only workflow retains offline target and documentation checks.

All source endpoints and credential references must be neutral examples. Never
commit live workspace names/IDs, hosts, warehouse IDs, principals or credentials.
See [the cleanup handoff](docs/solutions-cleanup.md) and [security](SECURITY.md).

Tests are intentionally deferred until the user reviews both migration PRs.

The model follows customers, addresses and orders through Stage, Core and Curated,
including DimCustomer, DimDate and FactSalesOrder. The consumer layer retains
Customer, Date, Sales Order and Total Sales. Product/procurement/inventory/commerce/
shipping examples belong to Solutions. Customer reads the standard SalesLT.Customer
table; no Customer_DE/Customer_EN source views are required.
