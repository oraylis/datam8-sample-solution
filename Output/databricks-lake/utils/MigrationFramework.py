# Databricks notebook source
# MAGIC %md
# MAGIC # Generic notebook for migration

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------

from operator import itemgetter
from pyspark.errors import AnalysisException
from pyspark.sql.types import StructField, StructType  # noqa: F401 - exported to %run callers
from pyspark.sql.functions import row_number, lit, when, col, max as _max, coalesce, lower  # noqa: F401
from pyspark.sql import Window as W  # noqa: F401 - existing notebook exports
import time  # noqa: F401 - existing notebook export
from copy import copy
from typing import NoReturn, Any, List, Dict, Final
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as _migration_f
import json as _migration_json
import re as _migration_re
import uuid as _migration_uuid
from copy import deepcopy as _migration_deepcopy
from datetime import datetime as _MigrationDateTime, timezone as _MigrationTimezone
from pyspark.sql.types import _parse_datatype_string
from functools import lru_cache as _migration_cache
# from delta import DeltaTable

# COMMAND ----------

""" This module provides functions to interact with unity catalog enabled tables
"""


class Catalog(object):
    """ Class to provide funcitonality to work with multiple unity catalogs
        and contains replacement menthods for `spark.catalog.*` methods, as
        those do not work when using a shared unity catalog enabled cluster.
    """

    def __init__(self, catalog_name: str = None):
        self.spark: SparkSession = SparkSession.builder.getOrCreate()

        self.name = catalog_name or self.get_current_catalog()

        self.schema: str = ""

    def set_current_catalog(self, catalog_name: str) -> NoReturn:
        """ Sets the active catalog for the current `SparkSession`

        Arguments:
            catalog_name (str): Name of the catalog to be activated.
        """
        self.spark.sql(f"use catalog `{catalog_name}`")

    def set_active(self) -> NoReturn:
        """ Sets this catalog as the current catalog for the `SparkSession`
        """
        self.set_current_catalog(self.name)

    def get_current_catalog(self) -> str:
        """ Read the current active catalog from the spark session

        Returns:
            The name of the current catalog as a string.
        """
        return self.spark.sql("select current_catalog()").collect().pop()[0]

    def get_schemas(self) -> tuple:
        """ Reads the available schemas/databases from the current active catalog.

        Returns:
            A tuple of schema/database names.
        """

        current_catalog = self.get_current_catalog()

        # temporarily switch to the hive_metastore to get schemata if needed
        if self.name in ["hive_metastore", "spark_catalog"]:
            if current_catalog != self.name:
                self.set_current_catalog(self.name)

            schemas = map(itemgetter("databaseName"),
                          self.spark.sql("show schemas").collect()
                          )

            if current_catalog != self.name:
                self.set_current_catalog(current_catalog)
        else:
            schemas = map(
                itemgetter("schema_name"),
                self.spark.table("`%s`.`%s`.`%s`" % (
                    self.name,
                    "information_schema",
                    "schemata",
                ))
                .collect()
            )

        print(schemas)
        return tuple(schemas)

    def get_catalogs(self) -> tuple[str]:
        """ Read the list of available catalogs from the spark session.

        Returns:
            A tuple of catalog names.
        """
        catalogs = map(
            itemgetter("catalog"),
            self.spark.sql("show catalogs").collect()
        )
        return tuple(catalogs)

    def list_catalogs(self) -> NoReturn:
        """ Prints the list of available catalogs to stdout. """

        for idx, catalog in enumerate(self.get_catalogs()):
            print(catalog)

    @property
    def is_unity_enabled(self) -> bool:
        "Determines if the catalog is managed in unity catalog."

        if self.name in ["hive_metastore", "spark_catalog"]:
            return False

        return True

    @property
    def name(self) -> str:
        """ The name of the catalog. """

        return self.__name

    @name.setter
    def name(self, catalog_name: str) -> NoReturn:
        self.__name = catalog_name
        self.refresh_schemas()

    @property
    def schemas(self) -> list[str]:
        """ The available schemas within the selected catalog. """

        return self.__schemas

    @property
    def schema(self) -> str:
        """ The current selected schema. """

        if self.__schema == "" or self.__schema is None:
            raise AttributeError("Schema has not been set yet!")

        return self.__schema

    @schema.setter
    def schema(self, schema_name: str) -> NoReturn:
        if "." in schema_name:
            self.name = schema_name.split(".")[0]
            self.__schema = schema_name.split(".")[1]
        else:
            self.__schema = schema_name

    def get_search_names(self, table_name: str) -> tuple[str]:
        table_name_details = tuple(reversed(table_name.split(".")))
        arg_count = len(table_name_details)

        return (table_name_details[2].lower() if arg_count > 2 else self.name,
                table_name_details[1].lower(
        ) if arg_count > 1 else self.schema,
            table_name_details[0].lower(),
        )

    def table_exists(self, table_name: str) -> bool:
        """ Check if a table exists.

        Depending on format of the name, different meta values are extracted from it.
        The table to checked does not need to be in the currently selected context.

        Examples:
            hive_metastore.structured.ERP_baan6_fp3
            structured.ERP_baan6_fp3
            ERP_baan6_fp3

        Arguments:
            table_name (str): The name of the table to be checked.

        Returns:
            True if the table exists, otherwise False.
        """

        (search_catalog, search_schema,
         search_table) = self.get_search_names(table_name)

        if self.name in ["hive_metastore", "spark_catalog"]:
            try:
                self.spark.read.table("`%s`.`%s`.`%s`" % (
                    search_catalog, search_schema, search_table
                ))
                return True
            except AnalysisException:
                pass
        else:
            if (
                self.spark.read.table(
                    "`%s`.information_schema.tables" % search_catalog)
                .filter(lower("table_catalog").eqNullSafe(search_catalog)
                        & lower("table_schema").eqNullSafe(search_schema)
                        & lower("table_name").eqNullSafe(search_table)
                        )
                .count() == 1
            ):
                return True

        return False

    @classmethod
    def __map_yes_no(cls, column):
        """ Helper method for interal things. """

        return (
            when(
                col(column) == "YES",
                lit(True)
            )
            .otherwise(
                lit(False)
            )
        )

    def create_schema_if_not_exists(self, schema_name: str, location: str = None, comment: str = None) -> NoReturn:
        """ Create a new schema in the currently selected catalog if it does not exist yet.

        Arguments:
            schema_name (str): The name for the new schema.
            location (str): The location or name of the external location, where data should reside.
            comment (str): A comment to be shown in the catalog.
        """
        if schema_name not in self.schemas:
            self.create_schema(schema_name=schema_name,
                               location=location,
                               comment=comment,
                               )

    def create_schema(self, schema_name: str, location: str = None, comment: str = None) -> NoReturn:
        """ Create a new schema in the currently selected catalog.

        Arguments:
            schema_name (str): The name for the new schema.
            location (str): The location or name of the external location, where data should reside.
            comment (str): A comment to be shown in the catalog.
        """

        sql_statement = f"CREATE SCHEMA `{self.name}`.`{schema_name}`"

        if location is not None:
            sql_statement += " %(type)s '%(location)s'" % {
                "type": (
                    "LOCATION"
                    if self.name in ["hive_metastore", "spark_catalog"]
                    else "MANAGED LOCATION"
                ),
                "location": location,
            }

        if comment is not None:
            sql_statement += f" COMMENT '{comment}'"

        self.spark.sql(sql_statement)
        self.refresh_schemas()

    def create_volume_if_not_exists(
        self,
        volume_name: str,
        schema_name: str,
        location: str = None,
        comment: str = None,
        owner: str = None
    ) -> NoReturn:
        """ Create a new schema in the currently selected catalog.

        Arguments:
            volume_name (str): The name for the new volume.
            schema_name (str): The name of the schema.
            location (str): The location or name of the external location, where data should reside.
            comment (str): A comment to be shown in the catalog.
        """
        if self.name in ["hive_metastore", "spark_catalog"]:
            print("Volumes are only supported with unity catalog.")
            return

        sql_statement = "CREATE %(type)s VOLUME IF NOT EXISTS `%(catalog)s`.`%(schema)s`.`%(volume)s`" % {
            "type": "" if location is None else "EXTERNAL",
            "catalog": self.name,
            "schema": schema_name,
            "volume": volume_name,
        }

        if location is not None:
            sql_statement += f" LOCATION '{location}'"

        if comment is not None:
            sql_statement += f" COMMENT '{comment}'"

        self.spark.sql(sql_statement)

        if owner is not None:
            set_owner_sql = f"ALTER VOLUME `{self.name}`.`{schema_name}`.`{volume_name}` SET OWNER TO `{owner}`"
            self.spark.sql(set_owner_sql)

    def set_schema_owner(self, schema_name: str, owner: str) -> NoReturn:
        """ Set the owner of a schema in the currently selected catalog.

        Arguments:
            schema_name (str): The name of the schema.
            owner (str): The owner of the schema.
        """

        if self.name in ["hive_metastore", "spark_catalog"]:
            print("Owner is only supported with unity catalog.")
            return

        sql_statement = "ALTER SCHEMA `%(catalog)s`.`%(schema)s` OWNER TO `%(owner)s`" % {
            "catalog": self.name,
            "schema": schema_name,
            "owner": owner,
        }

        self.spark.sql(sql_statement)
        self.refresh_schemas()

    def create_table_from_ddl(self, full_table_name: str, ddl: str) -> "Table":
        """Create a table within a catalog.

        Args:
            full_table_name (str): The table name incl. schema and/or catalog.
            ddl (str): A SQL DDL statement.

        Returns:
            (Table): New instance of the created table.
        """
        if not self.table_exists(full_table_name):
            self.spark.sql(ddl)

        return Table(full_table_name, self)

    def reset(self) -> NoReturn:
        """ Resets the instance to  the currently active catalog and refreshs the available schema list
        """

        self.name = self.get_current_catalog()
        self.refresh_schemas()

    def refresh_schemas(self) -> NoReturn:
        """ Refreshes the list of available schemas based on the currently selected catalog. """
        self.__schemas = self.get_schemas()


def check_dbr_version(version: str) -> bool:
    """ Checks if the given DBR version or higher is installed on the cluster.

    Arguments:
        version (str): A shorthand DBR version in the form of major, minor, i.e. 13.3.

    Returns:
        Return true if the given version is higher or equal than the cluster version.
    """
    spark = SparkSession.builder.getOrCreate()
    (major, minor, _) = (spark.conf.get("spark.databricks.clusterUsageTags.sparkVersion")
                         .split("x")[0]
                         .split(".")
                         )
    (target_major, target_minor) = version.split(".")

    # convert major and minor version into an integer for comparison
    # multiplication with 100000 to account for different length minor versions
    cluster_version = int(major) * 100000 + int(minor)
    target_version = int(target_major) * 100000 + int(target_minor)

    if cluster_version >= target_version:
        return True
    else:
        print("DBR version needs to be at least %s LTS" % version)
        return False

# COMMAND ----------


""" This module provides functions to interact with unity catalog enabled tables
"""


class ManualDataMigrationRequired(RuntimeError):
    """The target exists, but its archived data needs manual migration."""

    def __init__(self, result):
        self.result = result
        super().__init__(result["message"])


class MigrationFailed(RuntimeError):
    """A technical failure, with the recovery outcome and object names attached."""

    def __init__(self, result):
        self.result = result
        super().__init__(result["message"])


def _mi(value):
    return "`" + str(value).replace("`", "``") + "`"


def _ml(value):
    # Spark concatenates adjacent literals; quote characters need backslashes.
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


@_migration_cache(maxsize=256)
def _migration_type(ddl):
    # Spark Connect parses DDL remotely; reuse immutable type descriptions.
    return _parse_datatype_string(ddl)


class _MigrationDDL:
    """Tokenizer/parser for explicit Delta CREATE statements, not arbitrary SQL.

    Kept here so deployed notebooks need neither a parser package nor a helper
    notebook. Token positions also make quoted identifiers and nested types safe.
    """

    token = _migration_re.compile(
        r"\s+|--[^\n]*|/\*[\s\S]*?\*/|`(?:``|[^`])*`|'(?:''|\\.|[^'\\])*'|"
        r'"(?:""|[^"])*"|[A-Za-z_][\w$]*|[0-9]+(?:\.[0-9]+)?|<=>|>=|<=|<>|!=|==|=>|\|\||&&|::|->|[^\s]'
    )

    @classmethod
    def tokens(cls, sql):
        return [
            m.group()
            for m in cls.token.finditer(sql)
            if not m.group().isspace() and not m.group().startswith(("--", "/*"))
        ]

    @staticmethod
    def value(token):
        if token.startswith("`"):
            return token[1:-1].replace("``", "`")
        if token.startswith(("'", '"')):
            delimiter = token[0]
            body = token[1:-1].replace(delimiter * 2, delimiter)
            escapes = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "%": "\\%", "_": "\\_"}

            def decode(match):
                value = match.group(1)
                return chr(int(value, 8)) if value[0] in "01234567" else escapes.get(value, value)

            return _migration_re.sub(r"\\([0-7]{1,3}|.)", decode, body, flags=_migration_re.S)
        return token

    @staticmethod
    def text(tokens):
        return " ".join(tokens)

    @staticmethod
    def group(tokens, start):
        if start >= len(tokens) or tokens[start] != "(":
            raise ValueError("Expected parenthesized SQL clause")
        level = 0
        for index in range(start, len(tokens)):
            if tokens[index] == "(":
                level += 1
            elif tokens[index] == ")":
                level -= 1
                if level == 0:
                    return tokens[start + 1 : index], index + 1
        raise ValueError("Unbalanced SQL parentheses")

    @staticmethod
    def split(tokens):
        result, current, parens, angles = [], [], 0, 0
        for token in tokens:
            if token == "," and not parens and not angles:
                result.append(current)
                current = []
                continue
            current.append(token)
            if token == "(":
                parens += 1
            elif token == ")":
                parens -= 1
            elif token == "<" and (not parens or angles):
                angles += 1
            elif token == ">" and angles:
                angles -= 1
        if current:
            result.append(current)
        return result

    @classmethod
    def canonical(cls, sql):
        return " ".join(t if t.startswith("'") else cls.value(t).casefold() for t in cls.tokens(sql))

    @classmethod
    def parse(cls, sql):
        tokens = cls.tokens(sql)
        if tokens and tokens[-1] == ";":
            tokens.pop()
        if ";" in tokens:
            raise ValueError("Only one CREATE statement is accepted")
        upper = [t.upper() for t in tokens]
        if upper[:2] != ["CREATE", "TABLE"]:
            raise ValueError("Expected CREATE TABLE [IF NOT EXISTS]")
        index = 2
        if upper[index : index + 3] == ["IF", "NOT", "EXISTS"]:
            index += 3
        names = [cls.value(tokens[index])]
        index += 1
        while index < len(tokens) and tokens[index] == ".":
            names.append(cls.value(tokens[index + 1]))
            index += 2
        definitions, index = cls.group(tokens, index)
        spec = {
            "name": names,
            "columns": [],
            "constraints": [],
            "properties": {},
            "comment": "",
            "clustering": [],
            "partitions": [],
            "location": None,
            "row_filter": None,
        }
        for definition in cls.split(definitions):
            words = [t.upper() for t in definition]
            if words[0] == "CONSTRAINT":
                body = cls.text(definition[2:])
                spec["constraints"].append({"name": cls.value(definition[1]), "body": body})
                continue
            name = cls.value(definition[0])
            boundary, parens, angles = len(definition), 0, 0
            for j, token in enumerate(definition[1:], 1):
                if (
                    not parens
                    and not angles
                    and token.upper() in {"NOT", "NULL", "COMMENT", "DEFAULT", "GENERATED", "MASK", "COLLATE"}
                ):
                    boundary = j
                    break
                parens += (token == "(") - (token == ")")
                angles += (token == "<") - (token == ">")
            column = {
                "name": name,
                "type": cls.text(definition[1:boundary]),
                "nullable": True,
                "comment": "",
                "default": None,
                "identity": None,
                "generated": None,
                "mask": None,
                "collation": None,
            }
            j = boundary
            while j < len(definition):
                word = words[j]
                if word == "NOT" and words[j : j + 2] == ["NOT", "NULL"]:
                    column["nullable"], j = False, j + 2
                elif word == "NULL":
                    j += 1
                elif word in {"COMMENT", "COLLATE"}:
                    column["comment" if word == "COMMENT" else "collation"] = cls.value(definition[j + 1])
                    j += 2
                elif word == "GENERATED":
                    start = j
                    expression_start = words.index("AS", j) + 1
                    if words[expression_start] == "IDENTITY":
                        k = expression_start + 1
                        if k < len(definition) and definition[k] == "(":
                            _, k = cls.group(definition, k)
                        column["identity"], j = cls.text(definition[start:k]), k
                    else:
                        k = words.index("AS", j) + 1
                        _, end = cls.group(definition, k)
                        column["generated"], j = cls.text(definition[start:end]), end
                elif word in {"DEFAULT", "MASK"}:
                    end, level = j + 1, 0
                    while end < len(definition):
                        if not level and words[end] in {"COMMENT", "NOT", "MASK", "COLLATE"}:
                            break
                        level += (definition[end] == "(") - (definition[end] == ")")
                        end += 1
                    column[word.lower()], j = cls.text(definition[j + 1 : end]), end
                else:
                    raise ValueError(f"Unsupported column clause: {definition[j:]}")
            if not column["type"]:
                raise ValueError("Missing column type: " + name)
            spec["columns"].append(column)
        while index < len(tokens):
            word = upper[index]
            if word == "USING":
                if upper[index + 1] != "DELTA":
                    raise ValueError("Only Delta tables can be migrated")
                index += 2
            elif word == "COMMENT":
                spec["comment"], index = cls.value(tokens[index + 1]), index + 2
            elif word in {"CLUSTER", "PARTITIONED"} and upper[index + 1] == "BY":
                index += 2
                if word == "CLUSTER" and upper[index] in {"AUTO", "NONE"}:
                    values, index = (["AUTO"] if upper[index] == "AUTO" else []), index + 1
                else:
                    values, index = cls.group(tokens, index)
                    values = [".".join(cls.value(t) for t in item if t != ".") for item in cls.split(values)]
                spec["clustering" if word == "CLUSTER" else "partitions"] = values
            elif word == "TBLPROPERTIES":
                values, index = cls.group(tokens, index + 1)
                for item in cls.split(values):
                    if len(item) != 3 or item[1] != "=":
                        raise ValueError("Invalid table property")
                    key, value = cls.value(item[0]), cls.value(item[2])
                    if key.startswith("delta.constraints."):
                        spec["constraints"].append(
                            {"name": key[len("delta.constraints.") :], "body": "CHECK (" + value + ")"}
                        )
                    else:
                        spec["properties"][key] = value
            elif word == "LOCATION":
                spec["location"], index = cls.value(tokens[index + 1]), index + 2
            elif upper[index : index + 3] == ["WITH", "ROW", "FILTER"]:
                start = index + 3
                on = upper.index("ON", start)
                _, index = cls.group(tokens, on + 1)
                spec["row_filter"] = cls.text(tokens[start:index])
            else:
                raise ValueError("Unsupported CREATE clause: " + cls.text(tokens[index:]))
        keys = [c["name"].casefold() for c in spec["columns"]]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate target column names")
        if not keys:
            raise ValueError("The target must have columns")
        for constraint in spec["constraints"]:
            body = cls.tokens(constraint["body"])
            if [t.upper() for t in body[:2]] == ["PRIMARY", "KEY"]:
                fields, _ = cls.group(body, 2)
                primary = {cls.value(item[0]).casefold() for item in cls.split(fields)}
                for column in spec["columns"]:
                    if column["name"].casefold() in primary:
                        column["nullable"] = False
        return spec

    @staticmethod
    def column_sql(column, *, for_add=False):
        sql = _mi(column["name"]) + " " + column["type"]
        if column["collation"] and _MigrationDDL.tokens(column["type"])[0].upper() in {"STRING", "CHAR", "VARCHAR"}:
            sql += " COLLATE " + _mi(column["collation"])
        if not for_add:
            if column["identity"]:
                sql += " " + column["identity"]
            if column["generated"]:
                sql += " " + column["generated"]
            if not column["nullable"]:
                sql += " NOT NULL"
            if column["default"] is not None:
                sql += " DEFAULT " + column["default"]
        if column["comment"]:
            sql += " COMMENT " + _ml(column["comment"])
        if column["mask"]:
            sql += " MASK " + column["mask"]
        return sql

    @classmethod
    def render(cls, spec, table, *, constraints=True, replace=False, query=None, suffix="", defer_constraints=False):
        columns = [cls.column_sql(c) for c in spec["columns"]]
        if constraints:
            columns.extend(
                "CONSTRAINT " + _mi(c["name"] + suffix) + " " + c["body"]
                for c in spec["constraints"]
                if not defer_constraints or cls.tokens(c["body"])[0].upper() not in {"CHECK", "FOREIGN"}
            )
        sql = ("CREATE OR REPLACE TABLE " if replace else "CREATE TABLE ") + table
        # CTAS derives types; constraints/defaults are reconciled afterwards.
        if query is None:
            sql += " (" + ", ".join(columns) + ")"
        sql += " USING DELTA"
        if spec["partitions"]:
            sql += " PARTITIONED BY (" + ", ".join(_mi(c) for c in spec["partitions"]) + ")"
        if spec["clustering"]:
            sql += " CLUSTER BY " + (
                "AUTO" if spec["clustering"] == ["AUTO"] else "(" + ", ".join(_mi(c) for c in spec["clustering"]) + ")"
            )
        if spec["comment"]:
            sql += " COMMENT " + _ml(spec["comment"])
        if spec["properties"]:
            sql += (
                " TBLPROPERTIES ("
                + ", ".join(_ml(k) + "=" + _ml(v) for k, v in sorted(spec["properties"].items()))
                + ")"
            )
        if spec["location"]:
            sql += " LOCATION " + _ml(spec["location"])
        if spec["row_filter"]:
            sql += " WITH ROW FILTER " + spec["row_filter"]
        if query is not None:
            sql += " AS " + query
        return sql

    @classmethod
    def bind_reference(cls, body, spec, relation):
        tokens = cls.tokens(body)
        upper = [t.upper() for t in tokens]
        if "REFERENCES" not in upper:
            return body
        start = upper.index("REFERENCES") + 1
        end = start + 1
        while end < len(tokens) and tokens[end] == ".":
            end += 2
        names = [cls.value(t).casefold() for t in tokens[start:end] if t != "."]
        own = [name.casefold() for name in spec["name"]]
        if names and own[-len(names) :] == names:
            tokens[start:end] = cls.tokens(relation)
        return cls.text(tokens)


class _MigrationCatalog:
    """Read-only Delta and Unity Catalog snapshot operations."""

    def __init__(self, spark, parts):
        self.spark, self.parts = spark, parts
        self.qualified = ".".join(_mi(part) for part in parts)

    @staticmethod
    def user_properties(properties):
        return {
            k: v
            for k, v in properties.items()
            if not (
                k.startswith(("delta.feature.", "delta.constraints."))
                or k
                in {
                    "delta.minReaderVersion",
                    "delta.minWriterVersion",
                    "transient_lastDdlTime",
                    "clusteringColumns",
                    "delta.columnMapping.maxColumnId",
                }
            )
        }

    def state(self, name=None):
        name = name or self.qualified
        detail = self.spark.sql("DESCRIBE DETAIL " + name).first().asDict(recursive=True)
        if detail["format"].lower() != "delta":
            raise ValueError("Only Delta tables are supported")
        if detail.get("properties", {}).get("pipelines.pipelineId"):
            raise ValueError("Pipeline-managed tables must be migrated through their pipeline definition")
        spec = _MigrationDDL.parse(self.spark.sql("SHOW CREATE TABLE " + name).first()[0])
        # SHOW CREATE is useful for structure, but its escaped literals are not
        # a lossless metadata transport (notably backslashes in comments).
        spec["comment"] = detail.get("description") or ""
        described = self.spark.sql("DESCRIBE TABLE " + name).collect()[: len(spec["columns"])]
        for column, row in zip(spec["columns"], described):
            if row["col_name"] != column["name"]:
                raise ValueError("Column metadata and SHOW CREATE disagree")
            column["comment"] = row["comment"] or ""
        native_properties = detail.get("properties", {})
        spec["properties"] = {key: native_properties[key] for key in self.user_properties(spec["properties"])}
        for constraint in spec["constraints"]:
            key = "delta.constraints." + constraint["name"].lower()
            if key in native_properties:
                constraint["body"] = "CHECK (" + native_properties[key] + ")"
        spec["features"] = detail.get("tableFeatures", [])
        version = self.spark.sql("DESCRIBE HISTORY " + name + " LIMIT 1").first()["version"]
        location = detail["location"].rstrip("/")
        registration = _migration_re.search(
            r"/__unitystorage/(?:catalogs|schemas)/[^/]+/tables/([0-9a-fA-F-]{36})$", location
        )
        return {
            "spec": spec,
            # REPLACE can change the Delta reservoir ID while retaining the UC
            # registration and its managed storage directory. Recovery must use
            # that stable registration, not confuse it with a foreign table.
            "id": registration.group(1) if registration else "location:" + location,
            "delta_id": detail["id"],
            "identity_location": location,
            "version": version,
            "table_type": detail.get("type"),
            "detail": detail,
        }

    def catalog_metadata(self):
        where = (
            "table_catalog="
            + _ml(self.parts[0])
            + " AND table_schema="
            + _ml(self.parts[1])
            + " AND table_name="
            + _ml(self.parts[2])
        )
        prefix = _mi(self.parts[0]) + ".information_schema."
        tag_where = where.replace("table_catalog=", "catalog_name=").replace("table_schema=", "schema_name=")
        table_tags = {
            r["tag_name"]: r["tag_value"]
            for r in self.spark.sql(
                "SELECT tag_name,tag_value FROM " + prefix + "table_tags WHERE " + tag_where
            ).collect()
        }
        columns = {}
        for row in self.spark.sql(
            "SELECT column_name,tag_name,tag_value FROM " + prefix + "column_tags WHERE " + tag_where
        ).collect():
            columns.setdefault(row["column_name"], {})[row["tag_name"]] = row["tag_value"]
        owner = self.spark.sql("SELECT table_owner FROM " + prefix + "tables WHERE " + where).first()[0]
        grants = sorted(
            (r.asDict() for r in self.spark.sql("SHOW GRANTS ON TABLE " + self.qualified).collect()),
            key=lambda grant: tuple((key, str(value)) for key, value in sorted(grant.items())),
        )
        return {"owner": owner, "table_tags": table_tags, "column_tags": columns, "grants": grants}

    def incoming_references(self):
        prefix = _mi(self.parts[0]) + ".information_schema."
        sql = f"""SELECT child.table_catalog, child.table_schema, child.table_name,
                    r.constraint_name, r.unique_constraint_name AS referenced_constraint
                  FROM {prefix}referential_constraints r
                  JOIN {prefix}table_constraints parent
                    ON r.unique_constraint_catalog=parent.constraint_catalog
                   AND r.unique_constraint_schema=parent.constraint_schema
                   AND r.unique_constraint_name=parent.constraint_name
                  JOIN {prefix}table_constraints child
                    ON r.constraint_catalog=child.constraint_catalog
                   AND r.constraint_schema=child.constraint_schema
                   AND r.constraint_name=child.constraint_name
                  WHERE parent.table_catalog={_ml(self.parts[0])}
                    AND parent.table_schema={_ml(self.parts[1])}
                    AND parent.table_name={_ml(self.parts[2])}
                    AND NOT (child.table_catalog=parent.table_catalog AND child.table_schema=parent.table_schema
                             AND child.table_name=parent.table_name)"""
        return [r.asDict() for r in self.spark.sql(sql).collect()]


class _TableMigration:
    """Plan and execute one table migration; no persistent migration journal."""

    def __init__(self, table, ddl, schema, refactored_columns, partitions, metadata):
        self.table, self.spark = table, table.spark
        if self.spark.conf.get("spark.sql.parser.escapedStringLiterals", "false").lower() == "true":
            raise ValueError("Migration requires spark.sql.parser.escapedStringLiterals=false")
        self.parts = [table.catalog.name, table.schema_name, table.table_name]
        self.name = ".".join(self.parts)
        self.qualified = ".".join(_mi(p) for p in self.parts)
        self.target = _MigrationDDL.parse(ddl)
        names = self.target["name"]
        if [p.casefold() for p in self.parts[-len(names) :]] != [p.casefold() for p in names]:
            raise ValueError("CREATE target does not match this Table instance")
        self.target["name"] = list(self.parts)
        if len(schema.fields) != len(self.target["columns"]):
            raise ValueError("DDL and schema have different columns")
        for field, column in zip(schema.fields, self.target["columns"]):
            if field.name != column["name"] or field.dataType != _migration_type(column["type"]):
                raise ValueError("DDL and schema disagree for " + column["name"])
        if list(partitions or []) != self.target["clustering"] and list(partitions or []) != self.target["partitions"]:
            raise ValueError("DDL and new_partitions disagree")
        self.metadata = _migration_deepcopy(metadata) if metadata is not None else None
        if self.metadata is not None:
            if not isinstance(self.metadata, dict):
                raise TypeError("target_metadata must be a dictionary")
            if "owner" in self.metadata and (not isinstance(self.metadata["owner"], str) or not self.metadata["owner"]):
                raise ValueError("owner must be a nonempty principal name; omit it to preserve ownership")
            for key in ("table_tags", "column_tags"):
                if not isinstance(self.metadata.get(key, {}), dict):
                    raise TypeError(key + " must be a dictionary")
            if any(not isinstance(tags, dict) for tags in self.metadata.get("column_tags", {}).values()):
                raise TypeError("column_tags values must be dictionaries")
            if self.metadata.get("column_tags", {}).keys() - {c["name"] for c in self.target["columns"]}:
                raise ValueError("column_tags references a column missing from the target")
        self.refactors = refactored_columns or []
        self.run_id = (
            _MigrationDateTime.now(_MigrationTimezone.utc).strftime("%Y%m%d_%H%M%S_") + _migration_uuid.uuid4().hex[:10]
        )
        self.archive = ".".join(_mi(p) for p in self.parts[:-1] + [self.parts[-1] + "__archive_" + self.run_id])
        self.candidate = ".".join(_mi(p) for p in self.parts[:-1] + [self.parts[-1] + "__candidate_" + self.run_id])
        self.result = {
            "status": "NOOP",
            "table": self.name,
            "strategy": "NONE",
            "message": "Target already matches.",
            "changes": [],
            "manual_migration_required": False,
            "archive_table": None,
            "reasons": [],
        }
        self.steps = []
        self.created = {}
        self.changed = False

    @staticmethod
    def constraint_key(constraint):
        tokens = _MigrationDDL.tokens(constraint["body"])
        end = max((i for i, token in enumerate(tokens) if token == ")"), default=-1) + 1
        result = tokens[:end]
        index = end
        defaults = (
            ("NOT", "ENFORCED"),
            ("INITIALLY", "DEFERRED"),
            ("DEFERRABLE",),
            ("NORELY",),
            ("MATCH", "FULL"),
            ("ON", "UPDATE", "NO", "ACTION"),
            ("ON", "DELETE", "NO", "ACTION"),
        )
        while index < len(tokens):
            match = next(
                (words for words in defaults if tuple(t.upper() for t in tokens[index : index + len(words)]) == words),
                None,
            )
            if match:
                index += len(match)
            else:
                result.append(tokens[index])
                index += 1
        return constraint["name"].casefold(), _MigrationDDL.canonical(_MigrationDDL.text(result))

    def state(self, name=None):
        return _MigrationCatalog(self.spark, self.parts).state(name)

    def catalog_metadata(self):
        return _MigrationCatalog(self.spark, self.parts).catalog_metadata()

    def incoming_references(self):
        return _MigrationCatalog(self.spark, self.parts).incoming_references()

    def execute_sql(self, sql, action, **info):
        """Single execution boundary, also used by live failure-injection tests."""
        self.spark.sql(sql).collect()
        self.changed = True
        self.result["changes"].append({"action": action, **info, "sql": sql})

    def reason(self, code, message, column=None):
        entry = {"code": code, "message": message}
        if column is not None:
            entry["column"] = column
        if entry not in self.result["reasons"]:
            self.result["reasons"].append(entry)

    def match_columns(self, existing_names, target_names, path=()):
        """One ambiguity policy for top-level and nested historical names."""
        existing = {name.casefold(): name for name in existing_names}
        targets = {name.casefold() for name in target_names}
        prefix = ".".join(path)
        paths = getattr(self, "column_paths", {})
        source_path = tuple(path)
        for length in range(len(path), -1, -1):
            if tuple(path[:length]) in paths:
                source_path = paths[tuple(path[:length])] + tuple(path[length:])
                break
        source_prefix = ".".join(source_path)

        def qualified(name):
            return prefix + "." + name if prefix else name

        aliases = {item["name"].casefold(): item.get("refactorNames", []) for item in self.refactors}
        result, used = {}, set()
        for name in target_names:
            histories = aliases.get(qualified(name).casefold(), [])
            hits = []
            for alias in histories:
                leaf = alias
                if prefix:
                    matched = next(
                        (p for p in (source_prefix, prefix) if alias.casefold().startswith(p.casefold() + ".")), None
                    )
                    if matched is None:
                        continue
                    leaf = alias[len(matched) + 1 :]
                source = existing.get(leaf.casefold())
                if source is not None and source.casefold() != name.casefold() and source not in hits:
                    hits.append(source)
            exact = existing.get(name.casefold())
            if exact is not None:
                if any(h.casefold() not in targets for h in hits):
                    self.reason("AMBIGUOUS_RENAME", "Current name and historical source both exist", qualified(name))
                source = exact
            elif len(hits) == 1:
                source = hits[0]
            else:
                source = None
                if hits:
                    self.reason("AMBIGUOUS_RENAME", "Multiple historical sources exist", qualified(name))
            if source is not None:
                if source in used:
                    self.reason("AMBIGUOUS_RENAME", "Source is used by more than one target", qualified(name))
                used.add(source)
                paths[(*path, name)] = (*source_path, source)
            result[name] = source
        self.column_paths = paths
        return result

    def mapping(self, current):
        return self.match_columns([c["name"] for c in current["columns"]], [c["name"] for c in self.target["columns"]])

    @staticmethod
    def is_widening(old, new):
        if old == new:
            return True
        if old.typeName() == new.typeName() == "struct":
            return len(old.fields) == len(new.fields) and all(
                a.name == b.name and a.nullable == b.nullable and _TableMigration.is_widening(a.dataType, b.dataType)
                for a, b in zip(old.fields, new.fields)
            )
        if old.typeName() == new.typeName() == "array":
            return old.containsNull == new.containsNull and _TableMigration.is_widening(
                old.elementType, new.elementType
            )
        if old.typeName() == new.typeName() == "map":
            return (
                old.valueContainsNull == new.valueContainsNull
                and _TableMigration.is_widening(old.keyType, new.keyType)
                and _TableMigration.is_widening(old.valueType, new.valueType)
            )
        a, b = old.simpleString().lower(), new.simpleString().lower()
        allowed = {
            "tinyint": {"smallint", "int", "bigint", "double"},
            "smallint": {"int", "bigint", "double"},
            "int": {"bigint", "double"},
            "float": {"double"},
            "date": {"timestamp_ntz"},
        }
        if a == "void":
            return True
        if b in allowed.get(a, set()):
            return True
        if b.startswith("decimal(") and a in {"tinyint", "smallint", "int", "bigint"}:
            return new.precision - new.scale >= (20 if a == "bigint" else 10)
        if a.startswith("decimal(") and b.startswith("decimal("):
            return new.scale >= old.scale and new.precision - new.scale >= old.precision - old.scale
        return False

    @staticmethod
    def identity_key(value):
        if not value:
            return None
        tokens = [t.upper() for t in _MigrationDDL.tokens(value)]

        def number(keyword):
            if keyword not in tokens:
                return "1"
            index = tokens.index(keyword) + 2
            return "".join(tokens[index : index + 2]) if tokens[index] in {"-", "+"} else tokens[index]

        start = number("START")
        step = number("INCREMENT")
        return ("BY DEFAULT" if "DEFAULT" in tokens else "ALWAYS", start, step)

    def add_step(self, action, sql, **info):
        self.steps.append({"action": action, "sql": sql, **info})

    @staticmethod
    def contains_timestamp_ntz(datatype):
        if datatype.typeName() == "timestamp_ntz":
            return True
        if datatype.typeName() == "struct":
            return any(_TableMigration.contains_timestamp_ntz(f.dataType) for f in datatype.fields)
        if datatype.typeName() == "array":
            return _TableMigration.contains_timestamp_ntz(datatype.elementType)
        if datatype.typeName() == "map":
            return _TableMigration.contains_timestamp_ntz(datatype.keyType) or _TableMigration.contains_timestamp_ntz(
                datatype.valueType
            )
        return False

    def nested_metadata(self, old, new, path):
        """Build supported leaf ALTER operations instead of rewriting structs."""

        def qpath(parts):
            return ".".join(_mi(n) for n in parts)

        if old == new:
            return []
        if old.typeName() == new.typeName() == "struct":
            result, used = [], set()
            fields = {f.name: f for f in old.fields}
            mapping = self.match_columns(list(fields), [f.name for f in new.fields], path)
            if any(r["code"] == "AMBIGUOUS_RENAME" for r in self.result["reasons"]):
                return None
            for field in new.fields:
                target_path = path + [field.name]
                previous = fields.get(mapping[field.name])
                if previous is None:
                    if not field.nullable:
                        return None
                    result.append(
                        (
                            "ADD_NESTED_FIELD",
                            f"ALTER TABLE {self.qualified} ADD COLUMNS "
                            f"({qpath(target_path)} {field.dataType.simpleString()})",
                        )
                    )
                else:
                    if previous.name in used:
                        return None
                    used.add(previous.name)
                    if previous.name != field.name:
                        if self.target["properties"].get("delta.columnMapping.mode") not in {"name", "id"}:
                            return None
                        result.append(
                            (
                                "RENAME_NESTED_FIELD",
                                f"ALTER TABLE {self.qualified} RENAME COLUMN "
                                f"{qpath(path + [previous.name])} TO {_mi(field.name)}",
                            )
                        )
                    child = self.nested_metadata(previous.dataType, field.dataType, target_path)
                    if child is None:
                        return None
                    result.extend(child)
                    if previous.nullable != field.nullable:
                        result.append(
                            (
                                "NESTED_NULLABILITY",
                                f"ALTER TABLE {self.qualified} ALTER COLUMN {qpath(target_path)} "
                                + ("DROP NOT NULL" if field.nullable else "SET NOT NULL"),
                            )
                        )
            for field in old.fields:
                if field.name not in used:
                    if self.target["properties"].get("delta.columnMapping.mode") not in {"name", "id"}:
                        return None
                    result.append(
                        ("DROP_NESTED_FIELD", f"ALTER TABLE {self.qualified} DROP COLUMN {qpath(path + [field.name])}")
                    )
            return result
        if old.typeName() == new.typeName() == "array" and old.containsNull == new.containsNull:
            return self.nested_metadata(old.elementType, new.elementType, path + ["element"])
        if old.typeName() == new.typeName() == "map" and old.valueContainsNull == new.valueContainsNull:
            keys = self.nested_metadata(old.keyType, new.keyType, path + ["key"])
            values = self.nested_metadata(old.valueType, new.valueType, path + ["value"])
            return None if keys is None or values is None else keys + values
        if old.typeName() == "void" or (
            self.is_widening(old, new)
            and self.target["properties"].get("delta.enableTypeWidening", "false").lower() == "true"
        ):
            return [
                (
                    "ALTER_NESTED_TYPE",
                    f"ALTER TABLE {self.qualified} ALTER COLUMN {qpath(path)} TYPE {new.simpleString()}",
                )
            ]
        return None

    def metadata_steps(self, current):
        """Return False if the complete schema cannot be changed with ALTER."""
        old = {c["name"]: c for c in current["columns"]}
        q = self.qualified
        if any(self.contains_timestamp_ntz(_migration_type(c["type"])) for c in self.target["columns"]):
            setting = self.target["properties"].setdefault("delta.feature.timestampNtz", "supported")
            if setting.lower() != "supported":
                raise ValueError("TIMESTAMP_NTZ requires delta.feature.timestampNtz=supported")
        if self.target["location"] and self.target["location"] != current["location"]:
            raise ValueError("Changing external storage locations is not supported")
        if self.target["partitions"] != current["partitions"]:
            return False
        if current["partitions"] and self.target["clustering"]:
            return False
        for c in self.target["columns"]:
            source = self.sources[c["name"]]
            previous = old.get(source)
            if c["identity"] or c["generated"]:
                if (
                    previous is None
                    or self.identity_key(c["identity"]) != self.identity_key(previous["identity"])
                    or _MigrationDDL.canonical(c["generated"] or "")
                    != _MigrationDDL.canonical(previous["generated"] or "")
                ):
                    return False
            elif previous and (previous["identity"] or previous["generated"]):
                return False
            if previous and _migration_type(previous["type"]) != _migration_type(c["type"]):
                if (
                    self.nested_metadata(_migration_type(previous["type"]), _migration_type(c["type"]), [c["name"]])
                    is None
                ):
                    return False
        affected = {
            source
            for name, source in self.sources.items()
            if source is not None
            and (
                source != name
                or _migration_type(old[source]["type"])
                != _migration_type(next(c["type"] for c in self.target["columns"] if c["name"] == name))
            )
        }
        affected.update(set(old) - set(self.sources.values()))
        constraints = self.constraint_steps(
            current["constraints"], self.target["constraints"], q, affected, protect=True
        )
        if constraints is None:
            return False
        self.steps.extend(step for step in constraints if step["action"] == "DROP_CONSTRAINT")
        for key, value in self.target["properties"].items():
            if (
                key.startswith("delta.feature.")
                and key[len("delta.feature.") :].casefold() in {f.casefold() for f in current.get("features", [])}
                and value.lower() == "supported"
            ):
                continue
            if current["properties"].get(key) != value:
                self.add_step(
                    "SET_PROPERTY",
                    f"ALTER TABLE {q} SET TBLPROPERTIES ({_ml(key)}={_ml(value)})",
                    property=key,
                    value=value,
                )
        renames = [(source, name) for name, source in self.sources.items() if source is not None and source != name]
        if renames and self.target["properties"].get(
            "delta.columnMapping.mode", current["properties"].get("delta.columnMapping.mode")
        ) not in {"name", "id"}:
            return False
        for index, (source, name) in enumerate(renames):
            temporary = "__dm8_rename_" + self.run_id + "_" + str(index)
            self.add_step(
                "RENAME_COLUMN",
                f"ALTER TABLE {q} RENAME COLUMN {_mi(source)} TO {_mi(temporary)}",
                **{"from": source, "to": temporary},
            )
        for index, (source, name) in enumerate(renames):
            temporary = "__dm8_rename_" + self.run_id + "_" + str(index)
            self.add_step(
                "RENAME_COLUMN",
                f"ALTER TABLE {q} RENAME COLUMN {_mi(temporary)} TO {_mi(name)}",
                **{"from": temporary, "to": name},
            )
        removed = [c for c in old if c not in set(self.sources.values())]
        if removed and self.target["properties"].get(
            "delta.columnMapping.mode", current["properties"].get("delta.columnMapping.mode")
        ) not in {"name", "id"}:
            return False
        # Remove clustering dependencies before removing their columns.
        if current["clustering"] != self.target["clustering"] and current["clustering"]:
            self.add_step("CLEAR_CLUSTERING", f"ALTER TABLE {q} CLUSTER BY NONE")
        for name in removed:
            self.add_step("DROP_COLUMN", f"ALTER TABLE {q} DROP COLUMN {_mi(name)}", column=name)
        for c in self.target["columns"]:
            name, source = c["name"], self.sources[c["name"]]
            previous = old.get(source)
            colsql = q + " ALTER COLUMN " + _mi(name)
            if previous is None:
                self.add_step(
                    "ADD_COLUMN",
                    f"ALTER TABLE {q} ADD COLUMNS ({_MigrationDDL.column_sql(c, for_add=True)})",
                    column=name,
                )
            elif _migration_type(previous["type"]) != _migration_type(c["type"]):
                for action, sql in self.nested_metadata(
                    _migration_type(previous["type"]), _migration_type(c["type"]), [name]
                ):
                    self.add_step(action, sql, column=name, **{"from": previous["type"], "to": c["type"]})
            if previous and previous["comment"] != c["comment"]:
                self.add_step(
                    "COLUMN_COMMENT",
                    "COMMENT ON COLUMN "
                    + q
                    + "."
                    + _mi(name)
                    + " IS "
                    + (_ml(c["comment"]) if c["comment"] else "NULL"),
                    column=name,
                )
            if (previous and previous["nullable"] != c["nullable"]) or (not previous and not c["nullable"]):
                self.add_step(
                    "COLUMN_NULLABILITY",
                    "ALTER TABLE " + colsql + (" DROP NOT NULL" if c["nullable"] else " SET NOT NULL"),
                    column=name,
                )
            if _MigrationDDL.canonical((previous or {}).get("default") or "") != _MigrationDDL.canonical(
                c["default"] or ""
            ):
                self.add_step(
                    "COLUMN_DEFAULT",
                    "ALTER TABLE "
                    + colsql
                    + (" DROP DEFAULT" if c["default"] is None else " SET DEFAULT " + c["default"]),
                    column=name,
                )
            if (
                previous
                and (previous.get("collation") or "UTF8_BINARY").upper()
                != (c.get("collation") or "UTF8_BINARY").upper()
            ):
                self.add_step(
                    "COLUMN_COLLATION",
                    "ALTER TABLE "
                    + colsql
                    + " TYPE "
                    + c["type"]
                    + " COLLATE "
                    + _mi(c.get("collation") or "UTF8_BINARY"),
                    column=name,
                )
            before_mask = (previous or {}).get("mask")
            if _MigrationDDL.canonical(before_mask or "") != _MigrationDDL.canonical(c["mask"] or ""):
                self.add_step(
                    "COLUMN_MASK",
                    "ALTER TABLE " + colsql + (" DROP MASK" if not c["mask"] else " SET MASK " + c["mask"]),
                    column=name,
                )
        order = [next((n for n, s in self.sources.items() if s == c), c) for c in old if c not in removed]
        order += [n for n, s in self.sources.items() if s is None]
        desired = [c["name"] for c in self.target["columns"]]
        if order != desired:
            for index, name in enumerate(desired):
                location = " FIRST" if index == 0 else " AFTER " + _mi(desired[index - 1])
                self.add_step("REORDER_COLUMN", f"ALTER TABLE {q} ALTER COLUMN {_mi(name)}{location}", column=name)
        self.steps.extend(step for step in constraints if step["action"] == "ADD_CONSTRAINT")
        if current["clustering"] != self.target["clustering"] and self.target["clustering"]:
            clustering = self.target["clustering"]
            clause = "AUTO" if clustering == ["AUTO"] else "(" + ", ".join(_mi(n) for n in clustering) + ")"
            self.add_step("SET_CLUSTERING", f"ALTER TABLE {q} CLUSTER BY {clause}")
        if current["comment"] != self.target["comment"]:
            self.add_step(
                "TABLE_COMMENT",
                f"COMMENT ON TABLE {q} IS " + (_ml(self.target["comment"]) if self.target["comment"] else "NULL"),
            )
        if _MigrationDDL.canonical(current["row_filter"] or "") != _MigrationDDL.canonical(
            self.target["row_filter"] or ""
        ):
            self.add_step(
                "ROW_FILTER",
                f"ALTER TABLE {q} "
                + (
                    "DROP ROW FILTER"
                    if not self.target["row_filter"]
                    else "SET ROW FILTER " + self.target["row_filter"]
                ),
            )
        for key in current["properties"].keys() - self.target["properties"].keys():
            # Feature removal needs explicit DROP FEATURE, never an implicit downgrade.
            if key in {
                "delta.columnMapping.mode",
                "delta.enableTypeWidening",
                "delta.enableDeletionVectors",
                "delta.enableRowTracking",
                "delta.checkpointPolicy",
                "delta.parquet.format.version",
            }:
                continue
            self.add_step("UNSET_PROPERTY", f"ALTER TABLE {q} UNSET TBLPROPERTIES ({_ml(key)})", property=key)
        return True

    @staticmethod
    def data_error(error):
        getter = getattr(error, "getCondition", None) or getattr(error, "getErrorClass", None)
        code = (getter() if getter else "") or ""
        return code.startswith(
            (
                "CAST_",
                "NUMERIC_",
                "DATATYPE_MISMATCH",
                "DELTA_NOT_NULL",
                "DELTA_CHECK_CONSTRAINT",
                "DELTA_NEW_CHECK_CONSTRAINT_VIOLATION",
                "DELTA_NEW_NOT_NULL_VIOLATION",
                "DELTA_VIOLATE_CONSTRAINT_WITH_VALUES",
                "NEW_CHECK_CONSTRAINT_VIOLATION",
                "INCOMPATIBLE_DATA",
                "DUPLICATED_MAP_KEY",
                "NOT_NULL",
                "CHECK_CONSTRAINT",
            )
        )

    @staticmethod
    def unsupported_change(error):
        condition = getattr(error, "getCondition", None) or getattr(error, "getErrorClass", None)
        code = (condition() if condition else "") or ""
        sqlstate = getattr(error, "getSqlState", lambda: "")() or ""
        return sqlstate.startswith("0A") or code.startswith(
            ("DELTA_UNSUPPORTED", "NOT_SUPPORTED_CHANGE_COLUMN", "UNSUPPORTED_FEATURE")
        )

    @staticmethod
    def temporal_condition(expression, old, new):
        if old.typeName() != "string" or new.typeName() not in {"date", "timestamp", "timestamp_ntz"}:
            return None
        patterns = {
            "date": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
            "timestamp_ntz": "^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?$",
        }
        pattern = patterns.get(new.typeName())
        return (
            expression
            + " IS NOT NULL"
            + (" AND NOT (" + expression + " RLIKE " + _ml(pattern) + ")" if pattern else "")
        )

    def projection(self):
        old = {c["name"]: c for c in self.before["spec"]["columns"]}
        expressions, checks = [], []
        nonempty = self.spark.sql("SELECT 1 FROM " + self.qualified + " LIMIT 1").first() is not None
        for column in self.target["columns"]:
            name, source = column["name"], self.sources[column["name"]]
            if column["generated"]:
                continue
            if column["identity"] and source is None:
                continue
            if source is None:
                expression = "CAST(NULL AS " + column["type"] + ")"
            else:
                expression = _mi(source)
                previous = old[source]
                a, b = _migration_type(previous["type"]), _migration_type(column["type"])
                if a != b:
                    temporal = self.temporal_condition(_mi(source), a, b)
                    if (
                        temporal
                        and self.spark.sql(
                            "SELECT 1 FROM " + self.qualified + " WHERE " + temporal + " LIMIT 1"
                        ).first()
                    ):
                        self.reason(
                            "AMBIGUOUS_TIME_CONVERSION", "An explicit date/time interpretation is required", name
                        )
                    if a.typeName() == b.typeName() and a.typeName() in {"struct", "array", "map"}:
                        expression, losses = self.project_nested(_mi(source), a, b, [name])
                        checks.extend((name, loss) for loss in losses)
                    else:
                        expression = "TRY_CAST(" + _mi(source) + " AS " + column["type"] + ")"
                    if not self.is_widening(a, b) and a.typeName() not in {"struct", "array", "map"}:
                        checks.append(
                            (
                                name,
                                "NOT (TRY_CAST("
                                + expression
                                + " AS "
                                + previous["type"]
                                + ") <=> "
                                + _mi(source)
                                + ")",
                            )
                        )
                    checks.append((name, _mi(source) + " IS NOT NULL AND (" + expression + ") IS NULL"))
            previous_collation = (old.get(source, {}).get("collation") or "UTF8_BINARY").upper()
            target_collation = (column.get("collation") or "UTF8_BINARY").upper()
            if (
                _MigrationDDL.tokens(column["type"])[0].upper() in {"STRING", "CHAR", "VARCHAR"}
                and previous_collation != target_collation
            ):
                expression = "(" + expression + ") COLLATE " + _mi(target_collation)
            needs_null_check = (
                source is None
                or old[source]["nullable"]
                or (_migration_type(old[source]["type"]) != _migration_type(column["type"]))
            )
            if not column["nullable"] and not column["identity"] and needs_null_check:
                checks.append((name, expression + " IS NULL"))
            expressions.append((name, expression))
        for name, condition in checks:
            try:
                invalid = self.spark.sql("SELECT 1 FROM " + self.qualified + " WHERE " + condition + " LIMIT 1").first()
                if invalid:
                    self.reason(
                        "INVALID_DATA",
                        "Existing values cannot be transferred without loss or constraint violations",
                        name,
                    )
            except Exception as error:
                if not self.data_error(error):
                    raise
                self.reason("UNSUPPORTED_CONVERSION", str(error)[:500], name)
        return expressions, nonempty

    def project_nested(self, expression, old, new, path):
        """Preserve container shape/nulls and check conversion loss at leaves."""
        if old == new:
            return expression, []
        if old.typeName() == new.typeName() == "struct":
            pieces, losses = [], []
            fields = {f.name: f for f in old.fields}
            mapping = self.match_columns(list(fields), [f.name for f in new.fields], path)
            for field in new.fields:
                previous = fields.get(mapping[field.name])
                if previous is None:
                    value, child = "CAST(NULL AS " + field.dataType.simpleString() + ")", []
                else:
                    value, child = self.project_nested(
                        "(" + expression + ")." + _mi(previous.name),
                        previous.dataType,
                        field.dataType,
                        path + [field.name],
                    )
                pieces.extend([_ml(field.name), value])
                losses.extend("(" + expression + ") IS NOT NULL AND (" + loss + ")" for loss in child)
                if not field.nullable:
                    losses.append("(" + expression + ") IS NOT NULL AND (" + value + ") IS NULL")
            projected = "named_struct(" + ", ".join(pieces) + ")"
            return "IF(" + expression + " IS NULL, CAST(NULL AS " + new.simpleString() + "), " + projected + ")", losses
        if old.typeName() == new.typeName() == "array":
            variable = "__element" + str(len(path))
            value, child = self.project_nested(variable, old.elementType, new.elementType, path + ["element"])
            losses = ["exists(" + expression + ", " + variable + " -> (" + loss + "))" for loss in child]
            if not new.containsNull:
                losses.append("exists(" + expression + ", " + variable + " -> (" + value + ") IS NULL)")
            return "transform(" + expression + ", " + variable + " -> " + value + ")", losses
        if old.typeName() == new.typeName() == "map":
            variable = "__entry" + str(len(path))
            key, key_losses = self.project_nested(variable + ".key", old.keyType, new.keyType, path + ["key"])
            value, value_losses = self.project_nested(
                variable + ".value", old.valueType, new.valueType, path + ["value"]
            )
            child = key_losses + value_losses + ["(" + key + ") IS NULL"]
            if not new.valueContainsNull:
                child.append("(" + value + ") IS NULL")
            losses = ["exists(map_entries(" + expression + "), " + variable + " -> (" + loss + "))" for loss in child]
            keys = "transform(map_entries(" + expression + "), " + variable + " -> " + key + ")"
            losses.append("size(array_distinct(" + keys + ")) <> size(" + keys + ")")
            result = (
                "map_from_entries(transform(map_entries("
                + expression
                + "), "
                + variable
                + " -> named_struct('key', "
                + key
                + ", 'value', "
                + value
                + ")))"
            )
            return result, losses
        value = "TRY_CAST(" + expression + " AS " + new.simpleString() + ")"
        losses = (
            []
            if self.is_widening(old, new)
            else ["NOT (TRY_CAST(" + value + " AS " + old.simpleString() + ") <=> " + expression + ")"]
        )
        temporal = self.temporal_condition(expression, old, new)
        if temporal:
            losses.append(temporal)
        return value, losses

    def check_constraints(self, expressions, nonempty):
        if not nonempty or self.result["reasons"]:
            return
        if not expressions:
            self.reason("NO_INSERTABLE_COLUMNS", "No target column accepts an automatic source projection")
            return
        query = "SELECT " + ", ".join(e + " AS " + _mi(n) for n, e in expressions) + " FROM " + self.qualified
        generated = []
        for column in self.target["columns"]:
            if column["generated"]:
                tokens = _MigrationDDL.tokens(column["generated"])
                expression, _ = _MigrationDDL.group(tokens, [t.upper() for t in tokens].index("AS") + 1)
                generated.append(_MigrationDDL.text(expression) + " AS " + _mi(column["name"]))
        if generated:
            query = "SELECT projected.*, " + ", ".join(generated) + " FROM (" + query + ") projected"
        for constraint in self.target["constraints"]:
            tokens = _MigrationDDL.tokens(constraint["body"])
            upper = [t.upper() for t in tokens]
            predicate = None
            if upper[:2] == ["PRIMARY", "KEY"] or upper[0] == "UNIQUE":
                primary = upper[0] == "PRIMARY"
                fields, _ = _MigrationDDL.group(tokens, 2 if primary else 1)
                column_tokens = _MigrationDDL.split(fields)
                cols = [_MigrationDDL.text(c) for c in column_tokens]
                names = {_MigrationDDL.value(c[0]) for c in column_tokens}
                # A newly generated identity cannot violate uniqueness or NOT NULL.
                if any(
                    c["name"] in names and c["identity"] and self.sources[c["name"]] is None
                    for c in self.target["columns"]
                ):
                    continue
                nulls = " OR ".join(c + " IS NULL" for c in cols)
                duplicates = self.spark.sql(
                    "WITH target AS ("
                    + query
                    + ") SELECT 1 FROM target "
                    + ("" if primary else "WHERE " + " AND ".join(c + " IS NOT NULL" for c in cols) + " ")
                    + "GROUP BY "
                    + ",".join(cols)
                    + " HAVING count(*)>1 LIMIT 1"
                ).first()
                if duplicates:
                    self.reason(
                        "PRIMARY_KEY_VIOLATION" if primary else "UNIQUE_VIOLATION",
                        "Duplicate target key: " + constraint["name"],
                    )
                predicate = nulls if primary else None
            elif upper[0] == "CHECK":
                body, _ = _MigrationDDL.group(tokens, 1)
                predicate = "(" + _MigrationDDL.text(body) + ") IS NOT TRUE"
            elif upper[:2] == ["FOREIGN", "KEY"]:
                fields, end = _MigrationDDL.group(tokens, 2)
                cols = [_MigrationDDL.text(c) for c in _MigrationDDL.split(fields)]
                if upper[end] != "REFERENCES":
                    raise ValueError("Malformed foreign key")
                end += 1
                start = end
                while (
                    end < len(tokens)
                    and tokens[end] != "("
                    and upper[end] not in {"RELY", "NORELY", "NOT", "DEFERRABLE", "INITIALLY"}
                ):
                    end += 1
                reference = _MigrationDDL.text(tokens[start:end])
                self_reference = _MigrationDDL.bind_reference(
                    constraint["body"], self.target, "target"
                ) != _MigrationDDL.text(tokens)
                if end < len(tokens) and tokens[end] == "(":
                    ref_fields, _ = _MigrationDDL.group(tokens, end)
                    refs = [_MigrationDDL.text(c) for c in _MigrationDDL.split(ref_fields)]
                else:
                    ref_spec = self.target if self_reference else self.state(reference)["spec"]
                    pk = next(
                        c for c in ref_spec["constraints"] if _MigrationDDL.tokens(c["body"])[0].upper() == "PRIMARY"
                    )
                    pk_fields, _ = _MigrationDDL.group(_MigrationDDL.tokens(pk["body"]), 2)
                    refs = [_MigrationDDL.text(c) for c in _MigrationDDL.split(pk_fields)]
                if len(refs) != len(cols):
                    raise ValueError("Foreign key arity mismatch")
                if self_reference:
                    reference = "target"
                conditions = " AND ".join("src." + a + " = ref." + b for a, b in zip(cols, refs))
                nonnull = " AND ".join("src." + c + " IS NOT NULL" for c in cols)
                bad = self.spark.sql(
                    "WITH target AS ("
                    + query
                    + ") SELECT 1 FROM target src WHERE "
                    + nonnull
                    + " AND NOT EXISTS (SELECT 1 FROM "
                    + reference
                    + " ref WHERE "
                    + conditions
                    + ") LIMIT 1"
                ).first()
                if bad:
                    self.reason("FOREIGN_KEY_VIOLATION", "Missing referenced key: " + constraint["name"])
            if (
                predicate
                and self.spark.sql(
                    "WITH target AS (" + query + ") SELECT 1 FROM target WHERE " + predicate + " LIMIT 1"
                ).first()
            ):
                self.reason("CONSTRAINT_VIOLATION", "Existing data violates " + constraint["name"])

    def tag_steps(self, current, desired, q=None):
        q = q or self.qualified
        columns = set(self.spark.table(q).columns)
        scopes = set(current.get("column_tags", {})) | set(desired.get("column_tags", {}))
        for scope in (None, *sorted(scopes & columns)):
            before = current.get("table_tags", {}) if scope is None else current.get("column_tags", {}).get(scope, {})
            after = desired.get("table_tags", {}) if scope is None else desired.get("column_tags", {}).get(scope, {})
            prefix = "ALTER TABLE " + q + ("" if scope is None else " ALTER COLUMN " + _mi(scope))
            for key in before.keys() - after.keys():
                self.execute_sql(prefix + " UNSET TAGS (" + _ml(key) + ")", "UNSET_TAG", column=scope, tag=key)
            for key, value in after.items():
                if before.get(key) != str(value):
                    self.execute_sql(
                        prefix + " SET TAGS (" + _ml(key) + "=" + _ml(value) + ")", "SET_TAG", column=scope, tag=key
                    )

    def restore_catalog(self, metadata, *, tags=True, grants=False, owner=True):
        current = self.catalog_metadata()
        if tags:
            self.tag_steps(current, metadata)
        if grants:
            for grant in metadata.get("grants", []):
                # Inherited catalog/schema grants already apply to the target.
                # Re-granting them on the table would change future inheritance.
                if (grant.get("ObjectType") or grant.get("objectType", "")).upper() != "TABLE":
                    continue
                action = grant.get("ActionType") or grant.get("actionType")
                principal = grant.get("Principal") or grant.get("principal")
                if action and principal and action not in {"OWN", "OWNERSHIP"}:
                    self.execute_sql(
                        "GRANT " + action + " ON TABLE " + self.qualified + " TO " + _mi(principal), "RESTORE_GRANT"
                    )
        if owner and metadata.get("owner") and current["owner"] != metadata["owner"]:
            self.execute_sql(
                "ALTER TABLE " + self.qualified + " OWNER TO " + _mi(metadata["owner"]),
                "SET_OWNER",
                owner=metadata["owner"],
            )

    def validate(self):
        self.validated_state = self.state()
        actual = self.validated_state["spec"]
        for key in ("comment", "clustering", "partitions", "row_filter"):
            left, right = actual[key], self.target[key]
            if key == "row_filter":
                left, right = _MigrationDDL.canonical(left or ""), _MigrationDDL.canonical(right or "")
            if left != right:
                raise RuntimeError("Target verification failed: " + key)
        if len(actual["columns"]) != len(self.target["columns"]):
            raise RuntimeError("Target verification failed: column count")
        for a, b in zip(actual["columns"], self.target["columns"]):
            for key in ("name", "nullable", "comment"):
                if a[key] != b[key]:
                    raise RuntimeError("Target verification failed: " + b["name"] + "." + key)
            if _migration_type(a["type"]) != _migration_type(b["type"]):
                raise RuntimeError("Target verification failed: type " + b["name"])
            if (a.get("collation") or "UTF8_BINARY").upper() != (b.get("collation") or "UTF8_BINARY").upper():
                if _MigrationDDL.tokens(b["type"])[0].upper() in {"STRING", "CHAR", "VARCHAR"}:
                    raise RuntimeError("Target verification failed: collation " + b["name"])
            for key in ("default", "identity", "generated", "mask"):
                left = self.identity_key(a[key]) if key == "identity" else _MigrationDDL.canonical(a[key] or "")
                right = self.identity_key(b[key]) if key == "identity" else _MigrationDDL.canonical(b[key] or "")
                if left != right:
                    raise RuntimeError("Target verification failed: " + b["name"] + "." + key)
        if {self.constraint_key(c) for c in actual["constraints"]} != {
            self.constraint_key(c) for c in self.target["constraints"]
        }:
            raise RuntimeError("Target verification failed: constraints")
        for key, value in self.target["properties"].items():
            if (
                key.startswith("delta.feature.")
                and key[len("delta.feature.") :].casefold() in {f.casefold() for f in actual.get("features", [])}
                and value.lower() == "supported"
            ):
                continue
            if actual["properties"].get(key) != value:
                raise RuntimeError("Target verification failed: property " + key)
        if self.metadata is not None:
            catalog = self.catalog_metadata()
            self.validated_catalog = catalog
            if catalog["owner"] != self.metadata.get("owner", catalog["owner"]):
                raise RuntimeError("Target verification failed: owner")
            for key in ("table_tags", "column_tags"):
                expected = self.metadata.get(key, {})
                if key == "column_tags":
                    expected = {c: {k: str(v) for k, v in tags.items()} for c, tags in expected.items() if tags}
                else:
                    expected = {k: str(v) for k, v in expected.items()}
                if catalog[key] != expected:
                    raise RuntimeError("Target verification failed: " + key)

    def candidate_constraints(self):
        return [
            "ALTER TABLE "
            + self.candidate
            + " ADD CONSTRAINT "
            + _mi(c["name"] + ("_" + self.run_id if _MigrationDDL.tokens(c["body"])[0].upper() == "FOREIGN" else ""))
            + " "
            + _MigrationDDL.bind_reference(c["body"], self.target, self.candidate)
            for c in self.target["constraints"]
            if _MigrationDDL.tokens(c["body"])[0].upper() in {"CHECK", "FOREIGN"}
        ]

    def check_archive_constraints(self):
        """UC key names are schema-wide; never rename constraints on the archive."""

        def names(spec):
            return {
                c["name"].casefold()
                for c in spec["constraints"]
                if _MigrationDDL.tokens(c["body"])[0].upper() != "CHECK"
            }

        conflicts = names(self.before["spec"]) & names(self.target)
        if conflicts:
            raise ValueError(
                "ARCHIVE_CONSTRAINT_NAME_CONFLICT: original and target cannot share schema-wide key names: "
                + ", ".join(sorted(conflicts))
                + ". Choose distinct target constraint names."
            )

    def constraint_steps(self, current, desired, name, affected=(), *, protect=False):
        old = {self.constraint_key(c): c for c in current}
        new = {self.constraint_key(c): c for c in desired}
        affected = {n.casefold() for n in affected}

        def references(constraint):
            tokens = _MigrationDDL.tokens(constraint["body"])
            kind = tokens[0].upper()
            if kind in {"PRIMARY", "FOREIGN", "UNIQUE"}:
                fields, _ = _MigrationDDL.group(tokens, 1 if kind == "UNIQUE" else 2)
                return {_MigrationDDL.value(item[0]).casefold() for item in _MigrationDDL.split(fields)}
            return {_MigrationDDL.value(token).casefold() for token in tokens if not token.startswith("'")}

        removed = {key for key, constraint in old.items() if key not in new or affected & references(constraint)}
        if any(_MigrationDDL.tokens(old[key]["body"])[0].upper() in {"PRIMARY", "UNIQUE"} for key in removed):
            removed.update(key for key, c in old.items() if _MigrationDDL.tokens(c["body"])[0].upper() == "FOREIGN")
        if protect and any(
            r["referenced_constraint"].casefold() == old[key]["name"].casefold()
            for key in removed
            for r in self.incoming
        ):
            return None
        steps = []
        for key, constraint in sorted(
            old.items(), key=lambda item: _MigrationDDL.tokens(item[1]["body"])[0].upper() != "FOREIGN"
        ):
            if key in removed:
                steps.append(
                    {
                        "action": "DROP_CONSTRAINT",
                        "sql": "ALTER TABLE " + name + " DROP CONSTRAINT " + _mi(constraint["name"]),
                        "name": constraint["name"],
                    }
                )
        for key, constraint in sorted(
            new.items(), key=lambda item: _MigrationDDL.tokens(item[1]["body"])[0].upper() == "FOREIGN"
        ):
            if key not in old or key in removed:
                steps.append(
                    {
                        "action": "ADD_CONSTRAINT",
                        "sql": "ALTER TABLE "
                        + name
                        + " ADD CONSTRAINT "
                        + _mi(constraint["name"])
                        + " "
                        + constraint["body"],
                        "name": constraint["name"],
                    }
                )
        return steps

    def sync_constraints(self, name, desired):
        for step in self.constraint_steps(self.state(name)["spec"]["constraints"], desired, name):
            self.execute_sql(step["sql"], step["action"], name=step["name"], table=name)

    def create_candidate(self, action):
        count = len(self.result["changes"])
        try:
            self.execute_sql(
                _MigrationDDL.render(self.target, self.candidate, suffix="_" + self.run_id, defer_constraints=True),
                action,
            )
        finally:
            if any(c["action"] == action for c in self.result["changes"][count:]) and self.spark.catalog.tableExists(
                self.candidate
            ):
                self.candidate_id = self.remember(self.candidate)
        # CHECK must be added with ALTER in Databricks. Deferred FKs can now
        # resolve an existing candidate, including self-references.
        for sql in self.candidate_constraints():
            self.execute_sql(sql, "ADD_CANDIDATE_CONSTRAINT")

    def replace_target(self, expressions, nonempty, strategy):
        """Build a fully checked candidate before renaming the original."""
        target = self.target
        if strategy.startswith("ARCHIVE_"):
            self.check_archive_constraints()
        can_copy = strategy != "ARCHIVE_AND_CREATE_EMPTY"
        self.create_candidate("CREATE_CANDIDATE")
        if can_copy and nonempty:
            names = ", ".join(_mi(n) for n, _ in expressions)
            query = "SELECT " + ", ".join(e + " AS " + _mi(n) for n, e in expressions) + " FROM " + self.qualified
            try:
                self.execute_sql("INSERT INTO " + self.candidate + " (" + names + ") " + query, "COPY_DATA")
                for c in target["columns"]:
                    if c["identity"] and self.sources[c["name"]] is not None:
                        self.execute_sql(
                            "ALTER TABLE " + self.candidate + " ALTER COLUMN " + _mi(c["name"]) + " SYNC IDENTITY",
                            "SYNC_IDENTITY",
                        )
            except Exception as error:
                if not self.data_error(error):
                    raise
                can_copy = False
                self.reason("DATA_TRANSFER_FAILED", str(error)[:500])
                self.check_archive_constraints()
                self.discard(self.candidate, "DISCARD_CANDIDATE")
                self.create_candidate("CREATE_EMPTY_CANDIDATE")
        # Compare all carried values including duplicate rows, before cutover.
        if can_copy and nonempty:
            carried = [(n, e) for n, e in expressions if self.sources[n] is not None]
            if carried:
                expected = self.spark.sql(
                    "SELECT " + ", ".join(e + " AS " + _mi(n) for n, e in carried) + " FROM " + self.qualified
                )
                actual = self.spark.table(self.candidate).select(*[_mi(n) for n, _ in carried])
                self.assert_data(expected, actual)
        # Prefer a single-table replacement when no identity/generated/filter
        # clauses prevent a faithful CTAS. Keep the validated candidate as source.
        rewrite = can_copy and strategy == "REWRITE"
        if rewrite:
            query = "SELECT " + ", ".join(_mi(c["name"]) for c in target["columns"]) + " FROM " + self.candidate
            before_rewrite = self.state()
            try:
                self.execute_sql(
                    _MigrationDDL.render(target, self.qualified, replace=True, query=query), "REWRITE_TABLE"
                )
            except Exception as error:
                observed = self.state()
                if not self.unsupported_change(error) or (observed["id"], observed["version"]) != (
                    before_rewrite["id"],
                    before_rewrite["version"],
                ):
                    raise
                self.check_archive_constraints()
                self.result.setdefault("fallbacks", []).append(
                    {"from": "REWRITE", "to": "ARCHIVE_AND_COPY", "reason": str(error)[:500]}
                )
                rewrite = False
        if rewrite:
            actual = self.state()["spec"]
            self.sources = {c["name"]: c["name"] for c in target["columns"]}
            self.steps = []
            if not self.metadata_steps(actual):
                raise RuntimeError("Cannot reconcile rewritten target")
            for step in self.steps:
                self.execute_sql(
                    step["sql"], step["action"], **{k: v for k, v in step.items() if k not in {"sql", "action"}}
                )
            self.result["strategy"] = "REWRITE"
            self.discard(self.candidate, "DROP_CANDIDATE")
        else:
            self.execute_sql(
                "ALTER TABLE " + self.qualified + " RENAME TO " + self.archive,
                "ARCHIVE_TABLE",
                table=self.archive.replace("`", ""),
            )
            self.result["archive_table"] = ".".join(self.parts[:-1] + [self.parts[-1] + "__archive_" + self.run_id])
            self.execute_sql("ALTER TABLE " + self.candidate + " RENAME TO " + self.qualified, "ACTIVATE_TARGET")
            self.created.pop(self.candidate)
            self.sync_constraints(self.qualified, self.target["constraints"])
            self.result["strategy"] = "ARCHIVE_AND_COPY" if can_copy else "ARCHIVE_AND_CREATE_EMPTY"
            self.result["manual_migration_required"] = not can_copy
            if getattr(self, "incoming", []):
                self.result["manual_actions"] = [
                    {
                        "action": "REPOINT_FOREIGN_KEY",
                        "table": ".".join([r["table_catalog"], r["table_schema"], r["table_name"]]),
                        "constraint": r["constraint_name"],
                        "currently_references": self.result["archive_table"],
                        "target": self.name,
                    }
                    for r in self.incoming
                ]
            self.restore_catalog(self.original_metadata, tags=False, grants=True, owner=False)

    @staticmethod
    def comparable(column, datatype):
        """Convert only maps to sorted entry arrays; retain native scalar precision."""
        kind = datatype.typeName()
        if kind == "struct":
            value = _migration_f.struct(
                *[
                    _TableMigration.comparable(column.getField(f.name), f.dataType).alias(f.name)
                    for f in datatype.fields
                ]
            )
            return _migration_f.when(column.isNull(), _migration_f.lit(None)).otherwise(value)
        if kind == "array":
            return _migration_f.transform(column, lambda value: _TableMigration.comparable(value, datatype.elementType))
        if kind == "map":
            entries = _migration_f.transform(
                _migration_f.map_entries(column),
                lambda entry: _migration_f.struct(
                    _TableMigration.comparable(entry.getField("key"), datatype.keyType).alias("key"),
                    _TableMigration.comparable(entry.getField("value"), datatype.valueType).alias("value"),
                ),
            )
            return _migration_f.array_sort(entries)
        if kind == "string" and getattr(datatype, "collation", "UTF8_BINARY") != "UTF8_BINARY":
            return _migration_f.collate(column, "UTF8_BINARY")
        return column

    @staticmethod
    def assert_data(expected, actual):
        frames = [
            frame.select(
                *[
                    _TableMigration.comparable(_migration_f.col(_mi(f.name)), f.dataType).alias(f.name)
                    for f in frame.schema.fields
                ]
            )
            for frame in (expected, actual)
        ]
        left, right = frames
        if left.exceptAll(right).limit(1).count() or right.exceptAll(left).limit(1).count():
            raise RuntimeError("Data verification failed")

    def remember(self, name):
        identity = self.state(name)["id"]
        self.created[name] = identity
        return identity

    def discard(self, name, action):
        if self.state(name)["id"] != self.created.get(name):
            raise RuntimeError("Candidate identity changed; retain object for inspection: " + name)
        self.execute_sql("DROP TABLE " + name, action)
        self.created.pop(name)

    def recover(self):
        """Only touch objects whose identities were observed by this invocation."""
        if self.spark.catalog.tableExists(self.archive):
            if self.state(self.archive)["id"] != self.before["id"]:
                raise RuntimeError("Archive identity changed; manual recovery required")
            if self.spark.catalog.tableExists(self.qualified):
                if self.state()["id"] != getattr(self, "candidate_id", None):
                    raise RuntimeError("Unexpected target identity; manual recovery required")
                failed = ".".join(
                    _mi(p) for p in self.parts[:-1] + [self.parts[-1] + "__candidate_" + self.run_id + "_failed"]
                )
                self.spark.sql("ALTER TABLE " + self.qualified + " RENAME TO " + failed).collect()
                self.created[failed] = self.candidate_id
            self.spark.sql("ALTER TABLE " + self.archive + " RENAME TO " + self.qualified).collect()
        if self.state()["id"] != self.before["id"]:
            raise RuntimeError("Original identity changed; manual recovery required")
        for name in list(self.created):
            if self.spark.catalog.tableExists(name):
                self.discard(name, "RECOVERY_DROP_CANDIDATE")

        current = self.state()["spec"]
        original_constraints = {self.constraint_key(c) for c in self.before["spec"]["constraints"]}
        drop_parent = any(
            self.constraint_key(c) not in original_constraints
            and _MigrationDDL.tokens(c["body"])[0].upper() in {"PRIMARY", "UNIQUE"}
            for c in current["constraints"]
        )
        for constraint in sorted(
            current["constraints"], key=lambda c: _MigrationDDL.tokens(c["body"])[0].upper() != "FOREIGN"
        ):
            if (
                self.constraint_key(constraint) not in original_constraints
                or drop_parent
                and _MigrationDDL.tokens(constraint["body"])[0].upper() == "FOREIGN"
            ):
                self.spark.sql(
                    "ALTER TABLE " + self.qualified + " DROP CONSTRAINT " + _mi(constraint["name"])
                ).collect()
        if not (self.protected_metadata or self.protected_source) and self.state()["version"] != self.before["version"]:
            self.spark.sql(
                "RESTORE TABLE " + self.qualified + " TO VERSION AS OF " + str(self.before["version"])
            ).collect()
        # Unity Catalog constraints and comments need separate reconciliation.
        target, sources, steps = self.target, self.sources, self.steps
        try:
            self.target = self.before["spec"]
            self.sources = {c["name"]: c["name"] for c in self.target["columns"]}
            self.steps = []
            if not self.metadata_steps(self.state()["spec"]):
                raise RuntimeError("Original metadata requires manual recovery")
            for step in self.steps:
                self.spark.sql(step["sql"]).collect()
        finally:
            self.target, self.sources, self.steps = target, sources, steps
        self.restore_catalog(self.original_metadata, grants=False)
        target, metadata = self.target, self.metadata
        try:
            self.target, self.metadata = self.before["spec"], self.original_metadata
            self.validate()
            restored = self.validated_state
            if (
                set(restored["spec"]["features"]) != set(self.before["spec"]["features"])
                or any(
                    restored["detail"][k] != self.before["detail"][k] for k in ("minReaderVersion", "minWriterVersion")
                )
                or self.validated_catalog != self.original_metadata
            ):
                raise RuntimeError("Original protocol or catalog metadata differs after recovery")
            if not (self.protected_metadata or self.protected_source):
                self.assert_data(
                    self.spark.sql("SELECT * FROM " + self.qualified + " VERSION AS OF " + str(self.before["version"])),
                    self.spark.table(self.qualified),
                )
        finally:
            self.target, self.metadata = target, metadata

    def run(self, fail_on_manual):
        plan = self.prepare()
        is_metadata = plan["strategy"] in {"METADATA", "NONE"}
        expressions, nonempty = self.expressions, self.nonempty
        observed = self.state()
        if (observed["id"], observed["version"]) != (self.before["id"], self.before["version"]):
            raise RuntimeError("Table changed during planning; replan the migration")
        try:
            if is_metadata:
                try:
                    for step in self.steps:
                        self.execute_sql(
                            step["sql"], step["action"], **{k: v for k, v in step.items() if k not in {"sql", "action"}}
                        )
                    if self.steps and expressions and nonempty:
                        # Read the recorded pre-migration version, so renames,
                        # drops and nested changes are checked against old values
                        # rather than a lazily re-evaluated current DataFrame.
                        expected = self.spark.sql(
                            "SELECT "
                            + ", ".join(e + " AS " + _mi(n) for n, e in expressions)
                            + " FROM "
                            + self.qualified
                            + " VERSION AS OF "
                            + str(self.before["version"])
                        )
                        actual = self.spark.table(self.qualified).select(*[_mi(n) for n, _ in expressions])
                        self.assert_data(expected, actual)
                    self.result["strategy"] = "METADATA" if self.steps else "NONE"
                    if self.protected_metadata:
                        self.result["verification"] = (
                            "Native metadata operations only; protected data files are unchanged"
                        )
                except Exception as error:
                    if not self.data_error(error) and not self.unsupported_change(error):
                        raise
                    if self.changed:
                        self.recover()
                        self.result["changes"].append({"action": "RESTORE_BEFORE_FALLBACK"})
                    if self.data_error(error):
                        self.reason("DATA_CONSTRAINT_FAILURE", str(error)[:500])
                    self.replace_target(expressions, nonempty, self.replacement_strategy())
            else:
                self.steps = []
                self.replace_target(expressions, nonempty, plan["strategy"])
            if self.metadata is not None:
                self.restore_catalog(self.metadata)
            else:
                preserved = _migration_deepcopy(self.original_metadata)
                source_mapping = self.original_sources
                preserved["column_tags"] = {
                    name: preserved["column_tags"][source]
                    for name, source in source_mapping.items()
                    if source in preserved["column_tags"]
                }
                self.restore_catalog(preserved)
            self.validate()
            self.result["target_id"] = self.validated_state["id"]
            self.table.create_or_replace_dataframe()
        except Exception as error:
            self.result["status"] = "FAILED"
            self.reason("TECHNICAL_FAILURE", str(error)[:1500])
            try:
                # A lost SQL response can follow a committed change even when
                # execute_sql never had a chance to mark it successful.
                self.recover()
                self.result["message"] = "Migration failed; original table restored: " + str(error)[:500]
                if self.spark.catalog.tableExists(self.candidate):
                    self.result["recovery"] = {
                        "unconfirmed_candidate": self.candidate,
                        "message": "Original restored; unconfirmed candidate retained for inspection",
                    }
            except Exception as recovery:
                self.result["message"] = "RECOVERY_REQUIRED: " + str(recovery)[:500]
                self.result["recovery"] = {
                    "original": self.name,
                    "archive": self.archive,
                    "candidate": self.candidate,
                    "version": self.before["version"],
                    "candidate_id": getattr(self, "candidate_id", None),
                }
            self.table.last_migration_result = self.result
            print(_migration_json.dumps(self.result, ensure_ascii=False, default=str))
            raise MigrationFailed(self.result) from error
        if self.result["manual_migration_required"]:
            self.result["status"] = "MANUAL_DATA_MIGRATION_REQUIRED"
            self.result["message"] = "Empty target ready. Migrate data manually from " + self.result["archive_table"]
        elif self.result["changes"]:
            self.result["status"] = "MIGRATED"
            self.result["message"] = "Target ready; all carried data retained."
            if self.result["strategy"] == "NONE":
                self.result["strategy"] = "METADATA"
        self.table.last_migration_result = self.result
        print(_migration_json.dumps(self.result, ensure_ascii=False, default=str))
        if fail_on_manual and self.result["manual_migration_required"]:
            raise ManualDataMigrationRequired(self.result)
        return self.result

    def new_features(self, current):
        """Detect protocol boundaries before any change to the original."""
        active = {f.casefold().replace("typewidening-preview", "typewidening") for f in current.get("features", [])}
        required = set()
        toggles = {
            "delta.enableTypeWidening": "typeWidening",
            "delta.enableDeletionVectors": "deletionVectors",
            "delta.enableRowTracking": "rowTracking",
            "delta.enableChangeDataFeed": "changeDataFeed",
        }
        known = set(toggles) | {"delta.columnMapping.mode", "delta.checkpointPolicy"}
        for key, value in self.target["properties"].items():
            if key.startswith("delta.feature.") and value.lower() == "supported":
                required.add(key[len("delta.feature.") :])
            elif key in toggles and value.lower() == "true":
                required.add(toggles[key])
            elif key == "delta.columnMapping.mode" and value in {"name", "id"}:
                required.add("columnMapping")
            elif key == "delta.checkpointPolicy" and value == "v2":
                required.add("v2Checkpoint")
            elif key.startswith("delta.") and key not in known and current["properties"].get(key) != value:
                if not key.startswith(("delta.parquet.", "delta.dataSkipping.", "delta.autoOptimize.")):
                    required.add("property:" + key)
        if self.target["clustering"]:
            required.add("clustering")
        known = {
            "byte",
            "short",
            "integer",
            "long",
            "float",
            "double",
            "decimal",
            "boolean",
            "string",
            "binary",
            "date",
            "timestamp",
            "timestamp_ntz",
            "void",
        }
        old = {c["name"]: c for c in current.get("columns", [])}
        for column in self.target["columns"]:
            if (column.get("collation") or "UTF8_BINARY").upper() != "UTF8_BINARY":
                required.add("collations")
            previous = old.get(self.sources.get(column["name"]))
            datatype = _migration_type(column["type"])
            pending = [datatype] if previous is None or _migration_type(previous["type"]) != datatype else []
            while pending:
                item = pending.pop()
                kind = item.typeName()
                if kind == "struct":
                    pending.extend(f.dataType for f in item.fields)
                elif kind == "array":
                    pending.append(item.elementType)
                elif kind == "map":
                    pending.extend([item.keyType, item.valueType])
                elif kind == "string" and getattr(item, "collation", "UTF8_BINARY") != "UTF8_BINARY":
                    required.add("collations")
                elif kind not in known:
                    required.add("datatype:" + kind)
            if column["identity"]:
                required.add("identityColumns")
            if column["generated"]:
                required.add("generatedColumns")
            if column["default"] is not None:
                required.add("allowColumnDefaults")
        if any(_MigrationDDL.tokens(c["body"])[0].upper() == "CHECK" for c in self.target["constraints"]):
            required.add("checkConstraints")
        return sorted(feature for feature in required if feature.casefold() not in active)

    def replacement_strategy(self):
        """Shared by read-only planning, execution and checked runtime fallback."""
        if self.before["spec"]["location"] is not None:
            raise ValueError("Rebuild of external tables needs an independent storage location")
        if self.before["spec"]["row_filter"] or any(c["mask"] for c in self.before["spec"]["columns"]):
            self.reason("PROTECTED_SOURCE", "Automatic copy cannot prove it reads every unmasked source value")
        if self.nonempty:
            if not self.expressions:
                self.reason("NO_INSERTABLE_COLUMNS", "No target column accepts an automatic source projection")
            for column in self.target["columns"]:
                if (
                    column["identity"]
                    and self.sources[column["name"]] is not None
                    and "ALWAYS" in column["identity"].upper()
                ):
                    self.reason(
                        "IDENTITY_VALUES_NOT_INSERTABLE",
                        "Existing GENERATED ALWAYS values require manual copy",
                        column["name"],
                    )
        if self.result["reasons"]:
            return "ARCHIVE_AND_CREATE_EMPTY"
        if (
            not self.feature_changes
            and not self.incoming
            and not any(c["identity"] or c["generated"] for c in self.before["spec"]["columns"])
            and not any(c["identity"] or c["generated"] or c["mask"] for c in self.target["columns"])
            and not self.target["row_filter"]
            and not (self.before["spec"]["clustering"] and self.target["partitions"])
        ):
            return "REWRITE"
        return "ARCHIVE_AND_COPY"

    def prepare(self):
        """Read snapshot, bind columns, validate values, and choose one plan."""
        self.before = self.state()
        self.result["source_id"] = self.before["id"]
        self.incoming = self.incoming_references()
        self.original_metadata = self.catalog_metadata()
        self.sources = self.mapping(self.before["spec"])
        self.original_sources = dict(self.sources)
        self.target["row_filter"] = self.target["row_filter"] or self.before["spec"]["row_filter"]
        existing = {c["name"]: c for c in self.before["spec"]["columns"]}
        for column in self.target["columns"]:
            previous = existing.get(self.sources[column["name"]])
            if previous and previous["mask"] and not column["mask"]:
                column["mask"] = previous["mask"]
        if any(c["default"] is not None for c in self.target["columns"]):
            self.target["properties"].setdefault("delta.feature.allowColumnDefaults", "supported")
        metadata_only = self.metadata_steps(self.before["spec"])
        self.feature_changes = self.new_features(self.before["spec"])
        self.protected_source = bool(
            self.before["spec"]["row_filter"] or any(c["mask"] for c in self.before["spec"]["columns"])
        )
        protected = (
            self.before["spec"]["row_filter"]
            or self.target["row_filter"]
            or any(c["mask"] for c in self.before["spec"]["columns"] + self.target["columns"])
        )
        reversible = {
            "TABLE_COMMENT",
            "COLUMN_COMMENT",
            "SET_PROPERTY",
            "UNSET_PROPERTY",
            "CLEAR_CLUSTERING",
            "SET_CLUSTERING",
            "REORDER_COLUMN",
            "COLUMN_DEFAULT",
            "COLUMN_NULLABILITY",
            "ROW_FILTER",
            "COLUMN_MASK",
        }
        self.protected_metadata = bool(
            protected
            and metadata_only
            and not self.feature_changes
            and all(step["action"] in reversible for step in self.steps)
        )
        if protected:
            # Row policies can hide all rows. Metadata-only operations above do
            # not alter files; every other change needs an empty protected target.
            self.expressions, self.nonempty = [], False
            metadata_only = self.protected_metadata
        else:
            self.expressions, self.nonempty = self.projection()
            self.check_constraints(self.expressions, self.nonempty)
        if self.feature_changes or self.result["reasons"]:
            metadata_only = False
        if metadata_only:
            strategy = "METADATA" if self.steps or self.metadata_changed() else "NONE"
        else:
            self.steps = []
            strategy = self.replacement_strategy()
        if strategy.startswith("ARCHIVE_"):
            self.check_archive_constraints()
        return {
            "table": self.name,
            "source_id": self.before["id"],
            "source_version": self.before["version"],
            "strategy": strategy,
            "reasons": self.result["reasons"],
            "column_mapping": dict(self.sources),
            "feature_changes": self.feature_changes,
            "target_metadata": self.metadata,
        }

    def metadata_changed(self):
        if self.metadata is None:
            return False
        return self.original_metadata["owner"] != self.metadata.get("owner", self.original_metadata["owner"]) or any(
            self.original_metadata[key] != self.metadata.get(key, {}) for key in ("table_tags", "column_tags")
        )

    def plan(self):
        """Render the same assessment that run() executes, without mutations."""
        plan = self.prepare()
        if plan["strategy"] in {"METADATA", "NONE"}:
            sql = [step["sql"] for step in self.steps]
        else:
            sql = [_MigrationDDL.render(self.target, self.candidate, suffix="_" + self.run_id, defer_constraints=True)]
            sql.extend(self.candidate_constraints())
            if plan["strategy"] != "ARCHIVE_AND_CREATE_EMPTY" and self.nonempty:
                sql.append(
                    "INSERT INTO "
                    + self.candidate
                    + " ("
                    + ",".join(_mi(n) for n, _ in self.expressions)
                    + ") SELECT "
                    + ",".join(e for _, e in self.expressions)
                    + " FROM "
                    + self.qualified
                )
            if plan["strategy"] == "REWRITE":
                sql.append(
                    _MigrationDDL.render(
                        self.target, self.qualified, replace=True, query="SELECT * FROM " + self.candidate
                    )
                )
                sql.append("DROP TABLE " + self.candidate)
            else:
                sql.extend(
                    [
                        "ALTER TABLE " + self.qualified + " RENAME TO " + self.archive,
                        "ALTER TABLE " + self.candidate + " RENAME TO " + self.qualified,
                    ]
                )
        return {
            **plan,
            "sql": sql,
            "note": "Execution revalidates identity/version and reconciles catalog metadata after data operations.",
        }
class Table(object):
    """ The Table class provides basic functionalities to read from tables created
    via the MDWH Automation Framework.
    """

    def __init__(self, full_table_name: str, catalog: Catalog = None):
        """ Initializer

        Arguments:
            full_table_name (str): the full table name, inkl. catalog
            catalog (Catalog): The catalog to use (optional)

        Returns:
            Initialized object of class Table
        """
        self.is_current = False
        self.include_deletions = False

        self.schema_name, self.table_name = tuple(full_table_name.split("."))
        self.catalog = catalog or Catalog()
        self.catalog.schema = self.schema_name

        self.spark: SparkSession = SparkSession.builder.getOrCreate()
        self.dataframe: DataFrame = None

        self.create_or_replace_dataframe()

    @classmethod
    def from_list(cls, table_list: list[str], catalog: Catalog = None) -> dict[str, "Table"]:
        """ Takes a list of table names and creates Table instances from it.

        Does not support different meta stores.

        Arguments:
            table_list (list[str]): A list of full table name in the form of <schema>.<table>.
            catalog (Catalog): The catalog to be used (optional).

        Returns:
            A dictionary containing the new created Table instances. Uses
            the tablename as the dictionary key.
        """

        return {
            table_name: Table(table_name, catalog=catalog)
            for table_name in table_list
        }

    @classmethod
    def duplicate(cls, table) -> Any:
        """ Creates a shallow copy of a Table instance.

        Arguments:
            table (Table): Table instance to be copied

        Returns:
            A duplicated instance of Table or a sub-class.
        """

        return copy(table)

    @staticmethod
    def infer_layer_from_schema(schema_name: str):
        """" Get the layer name for a specific schema

        Arguments:
            schema_name (str): The schema name as visible in spark.

        Returns:
            The name of the layer as a string
        """

        schema = schema_name.removesuffix("zone")

        if schema in ["structured"]:
            return "technical"

        elif schema in ["core", "curated", "consumer"]:
            return "business"

        elif schema.startswith("common_"):
            return "common"

    @classmethod
    def infer_zone_from_schema(cls, schema_name: str):
        """ Get the zone name for a specific schema

        Arguments:
            schema_name (str): The schema name as visible in spark.

        Returns:
            The name of the Zone.
        """

        schema = schema_name.removesuffix("zone")

        if "_" in schema:
            return str(schema.split("_")[1])
        else:
            return schema

    @property
    def full_table_name(self) -> str:
        """ The table name in the form of <schema>.<table> """

        return "{0}.{1}".format(self.schema_name,
                                self.table_name
                                )

    @property
    def zone_name(self) -> str:
        """ The zone name of the table. """

        return Table.infer_zone_from_schema(self.schema_name)

    @property
    def layer_name(self) -> str:
        """ The layer name of the table. """

        return Table.infer_layer_from_schema(self.schema_name)

    @property
    def columns(self) -> list[str]:
        """ The list of available columns

        Derived from DataFrame.columns
        """

        return self.dataframe.columns

    @property
    def schema(self) -> StructType:
        """ The dataframe schema

        Derived from DataFrame.schema
        """

        return self.dataframe.schema

    @property
    def dataframe(self) -> DataFrame:
        """ Dataframe representing the table and selected options """

        df = self._dataframe

        if self.is_current:
            df = df.filter(col("__IsCurrent").eqNullSafe(True))

        if (not self.include_deletions
                and "__IsDeleted" in self._dataframe.columns):
            df = df.filter(col("__IsDeleted").eqNullSafe(False)
                           | col("__IsDeleted").isNull()
                           )

        return df

    @dataframe.setter
    def dataframe(self, val):
        self._dataframe = val

    @property
    def last_execution_status_id(self) -> int:
        """ The last (maximum) ExecutionStatusId contained in the table """

        return (self.dataframe
                .agg({"__ExecutionStatusId": "max"})
                .fillna({"max(__ExecutionStatusId)": -1})
                .collect()[0][0]
                )

    @property
    def owner(self) -> str:
        """ Returns the owner of this table based on describe extended """

        return (self.spark.sql("describe table extended %s" % self.full_table_name)
                .filter("col_name = 'Owner'")
                .collect()[0][1]
                )

    @owner.setter
    def owner(self, owner: str) -> NoReturn:
        """Sets the owner of a table."""
        print(self.catalog.name)
        self.spark.sql(
            """
            ALTER TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
            SET OWNER TO `%(owner)s`;
        """ % {
                "catalog": self.catalog.name,
                "schema": self.catalog.schema,
                "table": self.table_name,
                "owner": owner,
            })

    def explain(self) -> NoReturn:
        """ Wrapper function to call DataFrame.explain() """

        self.dataframe.explain()

    def current(self) -> "Table":
        """ Sets the option to only return the currently valid rows.

        Applies only to historized tables.

        Returns:
            A new Table instance.
        """

        if "__IsCurrent" not in self.columns:
            raise AssertionError("Table contains not history")

        new_table = Table.duplicate(self)
        new_table.is_current = True

        return new_table

    def with_deletions(self) -> "Table":
        """ Sets the option to additionally include deleted rows.

        Applies only to tables with the "deletions" flag enabled.

        Returns:
            A new Table instance.
        """

        if "__IsDeleted" not in self.columns:
            raise AssertionError("Table contains not deleted records")

        new_table = Table.duplicate(self)
        new_table.include_deletions = True

        return new_table

    def create_or_replace_dataframe(self):
        """ Re-/creates the dataframe attribute based on the current table table_name """

        self.dataframe = (self.spark
                          .read.table(f"{self.catalog.name}.{self.full_table_name}")
                          )

    def migrate_schema(self, ddl: str, schema: StructType,
                       refactored_columns: List[Dict[str, List[str]]],
                       new_partitions: tuple, target_metadata=None,
                       fail_on_manual_migration: bool = False) -> dict:
        """Converge to the DDL target, preserving data or archiving for manual copy.

        Historical names identify renames before adds/drops are calculated.
        ``new_partitions`` retains its legacy meaning (the DDL layout columns).
        Optional target_metadata contains owner, table_tags and column_tags.
        A manual fallback succeeds by default; technical failures always raise.
        Results and actual SQL changes are returned and printed, never journaled
        in another table. The caller must stop concurrent writers.
        """
        try:
            if not isinstance(fail_on_manual_migration, bool):
                raise TypeError("fail_on_manual_migration must be a boolean")
            return _TableMigration(self, ddl, schema, refactored_columns,
                                   new_partitions, target_metadata).run(fail_on_manual_migration)
        except (ManualDataMigrationRequired, MigrationFailed):
            raise
        except Exception as error:
            result = {"status": "FAILED", "table": ".".join([self.catalog.name, self.schema_name, self.table_name]),
                      "strategy": "NONE", "message": "Migration preflight failed: " + str(error)[:1000],
                      "changes": [], "manual_migration_required": False, "archive_table": None,
                      "reasons": [{"code": "PREFLIGHT_FAILED", "message": str(error)[:1000]}]}
            self.last_migration_result = result
            print(_migration_json.dumps(result, ensure_ascii=False, default=str))
            raise MigrationFailed(result) from error

    def plan_schema_migration(self, ddl: str, schema: StructType,
                              refactored_columns, new_partitions, target_metadata=None) -> dict:
        """Inspect the planned SQL without mutating the table or creating a journal."""
        return _TableMigration(self, ddl, schema, refactored_columns, new_partitions, target_metadata).plan()

    def set_table_comment(self, comment: str) -> int:
        """ Sets a comment on an unity catalog table.

        There can only be one comment assigned to table. If the function
        is called again, it will override the previous comment.

        Arguments:
            comment (str): The table comment to be.

        Returns:
            0: Success
        """
        sql_table_comment: Final[str] = "COMMENT ON TABLE `%(catalog)s`.`%(schema)s`.`%(table)s` IS '%(comment)s';"

        spark = SparkSession.builder.getOrCreate()
        spark.sql(sql_table_comment % {
            "catalog": self.catalog.name,
            "schema": self.schema_name,
            "table": self.table_name,
            "comment": comment,
        }
        )

        return 0

    def set_column_comment(self, column: str, comment: str) -> int:
        """ Sets a comment on column for an unity catalog table.

        There can only be one comment assigned to a column. If the function
        is called again, it will override the previous comment.

        Arguments:
            column (str): The column name.
            comment (str): The comment that gets applied to the column.

        Returns:
            0: Success
        """
        sql_column_comment: Final[str] = """
            ALTER TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
            ALTER COLUMN `%(column)s` COMMENT '%(comment)s';
        """

        spark = SparkSession.builder.getOrCreate()
        spark.sql(sql_column_comment % {
            "catalog": self.catalog.name,
            "schema": self.schema_name,
            "table": self.schema_name,
            "column": column,
            "comment": comment,
        }
        )

        return 0

    def set_table_tags(self, tags: dict) -> int:
        """ Set tags for an unity catalog enabled table.

        Once a tag is assigned it will not be automaticcaly removed via this
        function. It will only update an existing tag or create a new one.
        Removing a tag is an explicit action.

        Requires DBR version > 13.3.

        Arguments:
            tags (dict): Tags to be applied in the form of a dictionary.
                Other datatypes, e.g. bool, will get casted automatically to string.

        Returns:
            0: Success.
            1: Tags could not be applied, due to wrong DBR version.
        """
        sql_table_tags: Final[str] = """
            ALTER TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
            SET TAGS (%(tags)s);
        """

        tag_list = Table.__create_tag_list(tags)

        spark = SparkSession.builder.getOrCreate()
        spark.sql(sql_table_tags % {
            "catalog": self.catalog.name,
            "schema": self.schema_name,
            "table": self.table_name,
            "tags": tag_list,
        }
        )

        return 0

    def set_column_tags(self, column: str, tags: dict) -> int:
        """ Set tags for a column in an unity catalog enabled table.

        Once a tag is assigned it will not be automaticcaly removed via this
        function. It will only update an existing tag or create a new one.
        Removing a tag is an explicit action.

        Requires DBR version > 13.3.

        Arguments:
            column (str): The column tags will be assigned to.
            tags (dict): Tags to be applied in the form of a dictionary.
                Other datatypes, e.g. bool, will get casted automatically to string.

        Returns:
            0: Success.
            1: Tags could not be applied, due to wrong DBR version.
        """
        sql_column_tags: Final[str] = """
            ALTER TABLE `%(catalog)s`.`%(schema)s`.`%(table)s`
            ALTER COLUMN `%(column)s` SET TAGS (%(tags)s);
        """

        tag_list = Table.__create_tag_list(tags)

        spark = SparkSession.builder.getOrCreate()
        spark.sql(sql_column_tags % {
            "catalog": self.catalog.name,
            "schema": self.schema_name,
            "table": self.table_name,
            "column": column,
            "tags": tag_list
        }
        )

        return 0

    def __create_tag_list(tags: dict) -> tuple:
        """ Internal function to parse a dictionary of Tags

        Arguments:
            tags (dict): A dictionary of tags, preferably as string.

        Returns:
            Return a string of tag assignments, ready for an SQL query.
        """
        return ",".join(f"'{k}' = '{v}'"
                        for k, v in tags.items()
                        )

# COMMAND ----------


class TableBuilder(object):
    """ Instance builder to set common Table parameters at once.
    """

    def __init__(self, catalog: Catalog = None):
        """ Initializer

        Args:
            catalog (Catalog): catalog to be used for the created tables.
        """
        self.catalog = catalog or Catalog()

    def create(self, table: str) -> Table:
        """ Creates a new Table

        Args:
            table (str): Full tabl ename of the table ot be created, i.e. <schema>.<table>

        Returns:
            A newly created Table instance created with the parameters of the builders.
        """

        return Table(table, catalog=self.catalog)
