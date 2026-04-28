# Databricks notebook source
from pyspark.sql import DataFrame
from datetime import datetime

class ExtractionFramework:
    """Extraction Framework for DataM8 by ORAYLIS."""

    def __init__(self, table: str, extract_mode: str, delta_column: list = None):
        # Get all informations from the source, which includes sourceAlias, sourceLocation, extract_mode, schema (sourceName, targetName, sourceDataType)
        self.extract_mode: str = extract_mode
        self.table: str = table
        self.delta_column: list = delta_column

    def OracleDataSource(self, props: dict, max_raw: str = None) -> DataFrame:
        DRIVER = "oracle.jdbc.driver.OracleDriver"
        connection_props = {str(k).strip().lower(): v for k, v in (props or {}).items()}

        host = connection_props.get("host", "")
        port = connection_props.get("port", 1521)
        password = connection_props.get("password", "")
        user = connection_props.get("username") or connection_props.get("user") or ""
        service_name = (
            connection_props.get("database")
            or connection_props.get("service")
            or connection_props.get("sid")
            or connection_props.get("connection")
            or ""
        )

        if not host or not password or not service_name:
            raise ValueError(
                "Missing required connection properties for OracleDataSource: "
                "host, password, and one of database/service/sid/connection are required."
            )

        url = f"jdbc:oracle:thin:@{host}:{port}/{service_name}"

        where_clause = ""
        source_location = self.table

        if self.extract_mode == "delta":
            delta_column_name = [col["sourceName"] for col in (self.delta_column or []) if col.get("sourceName")]
            source_delta_column = ",".join(delta_column_name)
            if source_delta_column:
                where_clause = f"\n    WHERE {source_delta_column} > '{max_raw}'"

        if self.extract_mode == "query":
            pushdown_query = source_location
        else:
            pushdown_query = f"""
                SELECT *
                FROM {source_location}{where_clause}
            """
        print(
            f"Query: {pushdown_query}"
        )


        table_df = (
            spark.read
            .format("jdbc")
            .option("driver", DRIVER)
            .option("url", url)
            .option("user", user)
            .option("password", password)
            .option("query", pushdown_query)
            .load()
        )

        return table_df

    def SqlDataSource(self, props: dict, max_raw: str = None) -> DataFrame:

        DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
        connection_props = {str(k).strip().lower(): v for k, v in (props or {}).items()}
        host = connection_props.get("host", "")
        database = connection_props.get("database", "")
        port = connection_props.get("port", 1433)
        username = connection_props.get("username") or connection_props.get("user") or ""
        password = connection_props.get("password", "")

        if not host or not database or not password:
            raise ValueError(
                "Missing required connection properties for SqlDataSource: "
                "host, database and password are required."
            )

        encrypt = connection_props.get("encrypt", "true")
        trust_server_certificate = connection_props.get("trust_server_certificate", "false")
        trusted_connection = connection_props.get("trusted_connection", "false")
        if isinstance(encrypt, bool):
            encrypt = "true" if encrypt else "false"
        if isinstance(trust_server_certificate, bool):
            trust_server_certificate = "true" if trust_server_certificate else "false"
        if isinstance(trusted_connection, bool):
            trusted_connection = "true" if trusted_connection else "false"
        url = (
            f"jdbc:sqlserver://{host}:{port};"
            f"database={database};"
            f"encrypt={encrypt};"
            f"trustServerCertificate={trust_server_certificate};"
            f"trustedConnection={trusted_connection};"
        )

        where_clause = ""
        source_location = self.table

        if self.extract_mode == "delta":
            delta_column_name = [col["sourceName"] for col in (self.delta_column or []) if col.get("sourceName")]
            source_delta_column = ",".join(delta_column_name)

            if self.delta_column and self.delta_column[0]["canonicalDataType"] == "timestamp":
                #max_raw = max_raw[:-3]
                max_raw_ts = datetime.strptime(max_raw, "%Y-%m-%d %H:%M:%S.%f")
                max_raw = max_raw_ts.replace(microsecond=0)

            if source_delta_column:
                where_clause = f"\n    WHERE {source_delta_column} > '{max_raw}'"

        if self.extract_mode == "query":
            pushdown_query = source_location
        else:
            pushdown_query = f"""
                SELECT *
                FROM {source_location}{where_clause}
            """
        print(
            f"Query:{pushdown_query}"
        )


        table_df = (
            spark.read
            .format("jdbc")
            .option("driver", DRIVER)
            .option("url", url)
            .option("user", username)
            .option("password", password)
            .option("query", pushdown_query)
            .load()
        )

        return table_df
