# Databricks notebook source
# MAGIC %md
# MAGIC # Generic notebook for migration

# COMMAND ----------

# MAGIC %md
# MAGIC # Initialize base settings

# COMMAND ----------

from operator import itemgetter
from pyspark.errors import AnalysisException
from pyspark.sql.types import StructField, StructType
from pyspark.sql.functions import row_number, lit, when, col, max as _max, coalesce, lower
from pyspark.sql import Window as W
import time
from copy import copy
from typing import NoReturn, Any, List, Dict, Final
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
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

    def migrate_schema(self,
                       ddl: str,
                       schema: StructType,
                       refactored_columns: List[Dict[str, List[str]]],
                       new_partitions: tuple
                       ) -> int:
        """ Tries to migrate the schema of this table to match the reference dataframe.

        Arguments:
            ddl (str): SQL DDL query used to create the table.
            schema (StructType): Schema of the target table.
            refactored_columns (List[Dict[str, List[str]]]): The table metadata as
                provided by the Automation Framework.
            new_partitions (tuple): new_partitions are created by the create notebook.

        Returns:
            0: Successfull
            2: Table requires no migration
        """
        archive_time: int = int(time.time())

        # Existing table information
        existing_column_names = set(self.columns)

        existing_schema = {StructField(c.name, c.dataType)
                           for c in self.schema}

        existing_partition_fields = tuple(
            map(
                lambda x: x.name,
                filter(
                    lambda c: c.isCluster or c.isPartition,
                    self.spark.catalog.listColumns(f"{self.catalog.name}.{self.full_table_name}")
                )
            )
        )

        existing_data_layout = list({
            val
            for c in self.spark.catalog.listColumns(f"{self.catalog.name}.{self.full_table_name}")
            for val in [
                "liquid_clustering" if c.isCluster else None,
                "hive_partitioning" if c.isPartition else None
            ]
            if val is not None
        })

        target_data_layout = list({
            field.metadata.get("data_layout")
            for field in schema
            if "data_layout" in field.metadata
        })

        # Target table information
        new_column_names = set(schema.fieldNames())

        new_schema = {
            StructField(c.name, c.dataType)
            for c in schema
        }

        # Determine actions

        # Initialize sets to hold the results of columns to rename, delete and add
        columns_to_rename = set()
        columns_to_delete = set()
        columns_to_add = set()
        columns_new_names = set()
        rename_mapping = {}

        # Identify columns that need their datatype changed
        columns_datatype_to_change = {
            c
            for c in new_schema
            if len(
                list(filter(lambda x: x.name == c.name and x.dataType != c.dataType,
                            existing_schema
                            ))
            ) > 0
        }

        # Check if there are deleted or renamed columns
        # Here we compare the names of the columns instead of the schemas, to
        # avoid including changes in the value datatypes
        columns_to_delete_or_rename = existing_column_names - new_column_names

        # Distinguish between columns to rename and delete
        for column_name in columns_to_delete_or_rename:
            # Find the corresponding refactored column if it exists
            refactored_column = next(
                (
                    item
                    for item in refactored_columns
                    if column_name in item.get('refactorNames', [])
                ),
                None
            )

            if refactored_column:
                # Directly update the rename mapping
                columns_new_names.add(refactored_column['name'])
                columns_to_rename.add(column_name)
                rename_mapping = dict(
                    zip(columns_to_rename, columns_new_names))
            else:
                # Add to the set of columns to delete
                columns_to_delete.add(column_name)

        # Check if there are new columns
        columns_to_add = {
            field
            for field in (new_schema - existing_schema - columns_datatype_to_change)
            if field.name not in columns_new_names
        }

        # Determine if there are any columns in each category
        has_new_columns = len(columns_to_add) > 0
        has_renamed_columns = len(columns_to_rename) > 0
        has_deleted_columns = len(columns_to_delete) > 0
        has_changed_columns_datatype = len(columns_datatype_to_change) > 0
        has_changed_partition_key = sorted(
            new_partitions) != sorted(existing_partition_fields)
        has_changed_data_layout = set(existing_data_layout) != set(target_data_layout)

        if any([
            has_deleted_columns,
            has_new_columns,
            has_changed_columns_datatype,
            has_renamed_columns,
            has_changed_partition_key,
            has_changed_data_layout
        ]):

            # Archive the old table
            self.spark.sql(f"""
                ALTER TABLE {self.full_table_name} RENAME TO {self.full_table_name}_{archive_time}
            """)

            # Create new table with provided DDL
            spark.sql(ddl)
            # delta_table = DeltaTable.forName(self.spark, self.full_table_name)

            # load the archived data
            df_archive = self.spark.table("`%(catalog)s`.%(table)s_%(time)s" % {
                "catalog": self.catalog.name,
                "table": self.full_table_name,
                "time": archive_time,
            })

            # Rename columns
            for old_name, new_name in rename_mapping.items():
                print("Rename column `%s` to `%s`" % (old_name, new_name))
                df_archive = df_archive.withColumnRenamed(old_name, new_name)

            # Remove deleted columns
            for column_name in columns_to_delete:
                print("Drop column `%s`" % column_name)
                df_archive = df_archive.drop(column_name)

            # Add new columns for migration with null values
            for c in columns_to_add:
                print("Add column `%s`" % c.name)
                df_archive = df_archive.withColumn(
                    c.name,
                    lit(None).cast(c.dataType)
                )

            # cast columns if possible
            if has_changed_columns_datatype:
                for c in columns_datatype_to_change:
                    print("Change datatype of `%s` to %s" %
                          (c.name, c.dataType))
                    df_archive = df_archive.withColumn(
                        c.name,
                        F.col(c.name).cast(c.dataType)
                    )

            # Insert data into the final structure
            try:
                # Add warning to migrate deleted columns manually.
                if has_deleted_columns:
                    print(
                        "The following columns have been removed. Please migrate manually "
                        "from `%s_%s` if data needs to be restored: %s" % {
                            self.table_name,
                            archive_time,
                            ", ".join(columns_to_delete),
                        }
                    )
                else:
                    (
                        df_archive
                        .select(*schema.fieldNames())
                        .write
                        .format("delta")
                        .mode("overwrite")
                        .insertInto("%s.%s" % (self.catalog.name, self.full_table_name))
                    )
            except Exception as e:
                raise ValueError(
                    f"Tried automatic Migration, but failed. Please migrate manually! "
                    f"Failed due to {e}"
                )

            return 0

        else:
            print("No Changes deteced")
            return 2

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