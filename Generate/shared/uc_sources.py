"""Credential-free UC readers shared by generated source datasets."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import re
import time


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def database_query(connection, location, database, plugin):
    option = "service_name" if plugin == "oracle" else "database"
    if not database:
        raise ValueError("A database/service binding is required for UC reads")
    match = re.fullmatch(r"(?is)\s*SELECT\s+\*\s+FROM\s+(.+?)(?:\s+WHERE\s+(.+?))?\s*;?\s*", location)
    table = match[1] if match else location.strip()
    predicate = match[2] if match else None
    # Only decompose a plain qualified table reference. Preserve joins,
    # subqueries and other native SQL as an opaque remote query.
    identifier = r'(?:\[[^\]]+\]|"[^"]+"|`[^`]+`|[A-Za-z_][A-Za-z0-9_$]*)'
    if match and not re.fullmatch(identifier + r'(?:\s*\.\s*' + identifier + r')*', table):
        table, predicate = location.strip(), None
    if not re.match(r"(?i)^select\b", table):
        table = table.replace("[", "").replace("]", "") if plugin == "sqlserver" else table
        selection = "dbtable => " + sql_literal(table)
    else:
        selection = "query => " + sql_literal(table)
    return f"SELECT * FROM remote_query({sql_literal(connection)}, {option} => {sql_literal(database)}, {selection})", predicate


def read_database(spark, connection, location, database, plugin):
    query, predicate = database_query(connection, location, database, plugin)
    frame = spark.sql(query)
    if predicate:
        frame = frame.filter(predicate.replace("[", "`").replace("]", "`") if plugin == "sqlserver" else predicate)
    return frame


def spark_type(name):
    from pyspark.sql import types as T
    decimal = re.fullmatch(r"(?i)decimal\((\d+),\s*(\d+)\)", name)
    if decimal:
        return T.DecimalType(int(decimal[1]), int(decimal[2]))
    types = {"string": T.StringType, "int": T.IntegerType, "integer": T.IntegerType, "bigint": T.LongType, "long": T.LongType,
             "smallint": T.ShortType, "tinyint": T.ByteType, "boolean": T.BooleanType, "bit": T.BooleanType,
             "double": T.DoubleType, "float": T.FloatType, "date": T.DateType, "timestamp": T.TimestampType,
             "datetime": T.TimestampType, "binary": T.BinaryType}
    try:
        return types[name.lower()]()
    except KeyError:
        raise ValueError("Unsupported HTTP field type: " + name) from None


def typed_value(value, datatype):
    if value is None:
        return None
    from pyspark.sql import types as T
    if isinstance(datatype, T.DecimalType):
        return Decimal(str(value))
    if isinstance(datatype, T.TimestampType):
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if isinstance(datatype, T.DateType):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(datatype, (T.IntegerType, T.LongType, T.ShortType, T.ByteType)):
        return int(value)
    if isinstance(datatype, T.BooleanType):
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ValueError("Invalid boolean in API response")
    return value


def fetch_http_rows(connection, endpoint, client=None):
    """Read a bounded snapshot through the UC proxy, never direct source auth.

    Repeated cursors, partial responses and page-bound exhaustion are errors.
    No request headers, response bodies or tokens are logged.
    """
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()
    if not re.fullmatch(r"[A-Za-z0-9_.]+", connection) or not re.fullmatch(r"[A-Za-z0-9_/-]+", endpoint) or ".." in endpoint:
        raise ValueError("Invalid UC connection or relative endpoint")
    rows, seen, cursor, expected = [], set(), None, None
    for _ in range(1000):
        query = {"page_size": 500}
        if cursor is not None:
            query["cursor"] = cursor
        for attempt in range(4):
            try:
                payload = client.api_client.do("GET", "/api/2.0/unity-catalog/connections/" + connection + "/proxy/" + endpoint.lstrip("/"), query=query)
                break
            except Exception as error:
                status = getattr(error, "status_code", None)
                if status not in {429, 500, 502, 503, 504} or attempt == 3:
                    raise RuntimeError("UC HTTP request failed; no snapshot was published") from None
                time.sleep(2 ** attempt)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("API response has no items array")
        if payload.get("total") is not None:
            if expected is not None and expected != int(payload["total"]):
                raise ValueError("API total changed during snapshot read")
            expected = int(payload["total"])
        for item in payload["items"]:
            if not isinstance(item, dict):
                raise ValueError("API item must be an object")
            rows.append(item)
        cursor = payload.get("next_cursor")
        if cursor is None:
            if expected is not None and len(rows) != expected:
                raise ValueError("API snapshot row count differs from declared total")
            return rows
        cursor = str(cursor)
        if cursor in seen:
            raise ValueError("API repeated a pagination cursor")
        seen.add(cursor)
    raise ValueError("API snapshot exceeded the pagination bound")


def read_http(spark, connection, endpoint, columns, client=None):
    from pyspark.sql import types as T
    schema = T.StructType([T.StructField(column["name"], spark_type(column["type"]), column.get("nullable", True)) for column in columns])
    rows = fetch_http_rows(connection, endpoint, client)
    return spark.createDataFrame([tuple(typed_value(item.get(column.name), column.dataType) for column in schema) for item in rows], schema)
