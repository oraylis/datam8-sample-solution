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

    def OracleDataSource(self, database_connectionstring: str, max_raw: str = None) -> DataFrame:

        DRIVER = "oracle.jdbc.driver.OracleDriver"
        dict_connection_string = dict((element.split(
            '=') + [1])[:2] for element in database_connectionstring.split(";"))
        host = dict_connection_string["Host"]
        sid = dict_connection_string["Connection"]
        port = dict_connection_string["Port"]
        user = dict_connection_string["User"]
        password = dict_connection_string["Password"]
        url = f"jdbc:oracle:thin:@{host}:{port}/{sid}"

        where_clause = ""
        source_location = self.table

        if self.extract_mode == "delta":
            delta_column_name = [col["sourceName"] for col in self.delta_column]
            source_delta_column = ",".join(delta_column_name)
            where_clause = f"\n    WHERE {source_delta_column} > '{max_raw}'"

        if source_location.strip().upper().startswith("SELECT"):
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

    def SqlDataSource(self, database_connectionstring: str, max_raw: str = None) -> DataFrame:

        DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
        url = database_connectionstring

        where_clause = ""
        source_location = self.table

        if self.extract_mode == "delta":
            delta_column_name = [col["sourceName"] for col in self.delta_column]
            source_delta_column = ",".join(delta_column_name)
            
            if self.delta_column[0]["canonicalDataType"] == "timestamp":
                #max_raw = max_raw[:-3]
                max_raw_ts = datetime.strptime(max_raw, "%Y-%m-%d %H:%M:%S.%f")
                max_raw = max_raw_ts.replace(microsecond=0)

            where_clause = f"\n    WHERE {source_delta_column} > '{max_raw}'"

        if source_location.strip().upper().startswith("SELECT"):
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
            .option("query", pushdown_query)
            .load()
        )

        return table_df
