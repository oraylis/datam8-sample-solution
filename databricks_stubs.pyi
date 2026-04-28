"""
Stub file to provide a local notebook environment proper type hinting for
databricks builtin variables
"""

# ruff: noqa: F401
from typing import Any

from databricks.sdk.dbutils import RemoteDbUtils
from pyspark.sql import DataFrame, SparkSession

spark: SparkSession
dbutils: RemoteDbUtils
display: Any
displayHTML: Any
widgets: Any