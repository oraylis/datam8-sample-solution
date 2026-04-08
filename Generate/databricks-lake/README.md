# databricks-lake

This is a generator designed to produce the necessary files for an ELT (Extract, Load, Transform) flow with Databricks on Azure, enabling data writing to an Azure Data Lake Gen 2.

The generator's templates create Databricks notebooks.

## Maintainer Documentation

For payload contracts, template mapping, and extension guidance, see
[`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Databricks notebooks

The notebooks are organized into different zones and are categorized based on whether they contain Data Definition Language (DDL) or Data Modeling Language (DML).

### 000 Utils

The Utils section is not representative of a zone in the data lake but rather serves as a location for utility notebooks.

### External Source Zone

The external source zone is the first zone in `Base/Zones.json` without a `localFolderName`. It primarily contains data as delivered from source systems. The generated DML notebooks extract data from a source system and write it as Delta tables to Azure Data Lake Gen 2. The partitioned table is categorized by `year`, `month`, `day`, and `__InsertTimestampUTC`. If a source column is marked as a delta criterion (tagged with `delta`), the generated notebook checks already loaded data and only loads new deltas. Supported source systems include Azure SQL Database and Azure Data Lake Gen 2 with Parquet files.

### 020 STAGE

In the STAGE zone, the DDL notebooks define tables with specific columns and data types as defined in the model. The DML notebooks identify the delta between the external source zone and STAGE and attempt to load the missing data. Only the columns from the model definition are selected, and all columns are cast to their defined data types. Any rows containing data that does not conform to the definition are written to a poison table. The poison table's name corresponds to the relevant STAGE table, with `_poison` appended to its name.
