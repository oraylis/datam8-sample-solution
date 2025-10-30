# Databricks notebook source
import json
import uuid


class LoggingFramework:
    """Logging Framework for DataM8 by ORAYLIS."""

    @staticmethod
    def is_hive(catalog_name: str) -> bool:
        if catalog_name in ["hive_metastore", "spark_catalog"]:
          return True

        return False

    @staticmethod
    def prepare_logging_framework() -> None:
        """This method prepares the schema and all needed tables for the Logging Framework."""

        LoggingFramework.create_logging_schema()
        LoggingFramework.create_table_logging_extractions()
        LoggingFramework.create_table_logging_loads()
        LoggingFramework.create_view_logging_loads_jobs()
        LoggingFramework.set_object_owner()

    @staticmethod
    def set_object_owner() -> None:
        "Set the catlaog object owner, same as catalog."
        owner = spark.conf.get("datam8.catalog.owner")
        catalog_name = spark.conf.get("datam8.catalog.name")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")

        if LoggingFramework.is_hive(catalog_name):
            return

        ddl = "ALTER TABLE `%(catalog)s`.`%(schema)s`.%(table)s SET OWNER TO %(owner)s"
        tables = ["loads", "extractions", "v_loads_jobs"]

        for t in tables:
            spark.sql(ddl % {
                "catalog": catalog_name,
                "schema": zone,
                "table": t,
                "owner": owner,
            })

        spark.sql("ALTER DATABASE `%(catalog)s`.`%(database)s` SET OWNER TO %(owner)s" % {
            "catalog": catalog_name,
            "database": zone,
            "owner": owner,
        })

    @staticmethod
    def remove_logging_framework() -> None:
        """This method removes the schema and all tables of the Logging Framework."""

        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        spark.sql("DROP SCHEMA IF EXISTS `%s`.`%s` CASCADE" % (catalog_name, zone))

    @staticmethod
    def create_logging_schema() -> None:
        """This method creates the schema for logging purposes."""

        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())
        ddl = "CREATE SCHEMA IF NOT EXISTS `%(catalog)s`.`%(zone)s`" % {
            "catalog": catalog_name,
            "zone": zone,
        }
        
        if LoggingFramework.is_hive(catalog_name):
            data_lake_name = spark.conf.get("datam8.datalake.name")
            container_name = spark.conf.get("datam8.datalake.container.name")
            ddl += " LOCATION 'abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s'" % {
                "container": container_name,
                "lake": data_lake_name,
                "zone": zone,
            }

        spark.sql(ddl)

    @staticmethod
    def create_table_logging_extractions() -> None:
        """This method creates the table for logging extractions."""

        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        ddl = """
            CREATE TABLE IF NOT EXISTS `%(catalog)s`.`%(zone)s`.extractions
            (
                Extraction_UUID STRING NOT NULL,
                Table_Name STRING NOT NULL,
                Insert_Time_UTC TIMESTAMP NOT NULL,
                Status String NOT NULL,
                Row_Count BIGINT
            )
            USING DELTA
            CLUSTER BY (
                Table_Name
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
            }

        if LoggingFramework.is_hive(catalog_name):
            data_lake_name = spark.conf.get("datam8.datalake.name")
            container_name = spark.conf.get("datam8.datalake.container.name")
            ddl += " LOCATION 'abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/extractions'" % {
                "container": container_name,
                "lake": data_lake_name,
                "zone": zone,
            }

        spark.sql(ddl)

        spark.sql(
            """
            ALTER TABLE `%s`.`%s`.Extractions
            SET TBLPROPERTIES ('delta.isolationLevel' = 'Serializable')
            """ % (catalog_name, zone)
        )

    @staticmethod
    def create_table_logging_loads() -> None:
        """This method creates the table for logging loads"""

        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        ddl = """
            CREATE TABLE IF NOT EXISTS `%(catalog)s`.`%(zone)s`.loads
            (
                Load_UUID STRING NOT NULL,
                Target_Zone STRING NOT NULL,
                Job_Name STRING NOT NULL,
                Table_Name STRING NOT NULL,
                Insert_Time_UTC TIMESTAMP NOT NULL,
                Status String NOT NULL
            )
            USING DELTA
            CLUSTER BY (
                Target_Zone,
                Job_Name,
                Table_Name
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
            }

        spark.sql(ddl)

        if LoggingFramework.is_hive(catalog_name):
            data_lake_name = spark.conf.get("datam8.datalake.name")
            container_name = spark.conf.get("datam8.datalake.container.name")
            ddl += " LOCATION 'abfss://%(container)s@%(lake)s.dfs.core.windows.net/%(zone)s/loads'" % {
                "container": container_name,
                "lake": data_lake_name,
                "zone": zone,
            }

        spark.sql("""
            ALTER TABLE `%(catalog)s`.`%(zone)s`.Loads
            SET TBLPROPERTIES ('delta.isolationLevel' = 'Serializable')
            """ % {
                "catalog": catalog_name,
                "zone": zone,
              }
        )

    @staticmethod
    def create_view_logging_loads_jobs() -> None:
        """This method creates the view to aggregate logging.loads on a job level."""
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        spark.sql("""
            CREATE OR REPLACE VIEW `%(catalog)s`.`%(zone)s`.v_loads_jobs
            AS
            SELECT
                loads.Load_UUID
            ,   loads.Target_Zone
            ,   loads.Job_Name
            ,   min(loads.Insert_Time_UTC) as Start_Time_UTC
            ,   max(loads.Insert_Time_UTC) as End_Time_UTC
            ,   int(max(loads.Insert_Time_UTC)
                    - min(loads.Insert_Time_UTC)
                    ) as Duration_Seconds
            ,   count(distinct loads.Table_Name)                 as Count_Tables_Processed
            ,   coalesce(max(current_status.`Status`), 'Unkown') as `Status`
            FROM
              `%(catalog)s`.`%(zone)s`.loads
            LEFT JOIN (
                SELECT
                    Load_UUID
                ,   `Status`
                ,   row_number() over(
                        PARTITION BY Load_UUID
                        ORDER BY Insert_Time_UTC desc
                    ) as RANK
                FROM `%(catalog)s`.`%(zone)s`.loads
            ) current_status
                ON  current_status.Load_UUID = loads.Load_UUID
                AND current_status.RANK = 1
            GROUP BY
                loads.Load_UUID
            ,   loads.Target_Zone
            ,   loads.Job_Name
        """ % {
            "catalog": catalog_name,
            "zone": zone,
        })

    @staticmethod
    def start_extraction(table_name: str, status: str = "Started") -> str:
        """
        This method creates the initial logging entry for when an extraction is started.

        Args:
            table_name: Name of the table that gets extracted.
            status: New Status for the new extraction.

        Returns:
            extraction_uuid that is used for logging this extraction.
        """
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())
        extraction_uuid = str(uuid.uuid4())

        spark.sql(
            """
            INSERT INTO `%(catalog)s`.`%(zone)s`.extractions (
                Extraction_UUID, Table_Name, Insert_Time_UTC, Status
            ) VALUES (
                '%(extraction_uuid)s', '%(table)s', current_timestamp(), '%(status)s'
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
                "extraction_uuid": extraction_uuid,
                "table": table_name,
                "status": status,
            }
        )

        return extraction_uuid

    @staticmethod
    def end_extraction(extraction_uuid: str, row_count: int, table_name: str, status: str = "Completed") -> None:
        """This method updates the logging entry to mark completion of an extraction.

        Args:
            extraction_uuid: UUID of the extraction record, that shall get marked as completed.
            row_count: Number of rows that cot extracted.
            table_name: Name of the table that gets extracted.
            status: New Status for the given extraction.
        """
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        spark.sql(
            """
            INSERT INTO `%(catalog)s`.`%(zone)s`.extractions (
                Extraction_UUID, Table_Name, Insert_Time_UTC, Status, Row_Count
            ) VALUES (
                '%(extraction_uuid)s', '%(table)s', current_timestamp(), '%(status)s', %(row_count)s
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
                "extraction_uuid": extraction_uuid,
                "table": table_name,
                "status": status,
                "row_count": row_count,
            }
        )

    @staticmethod
    def start_load(target_zone: str, load_job_name: str, table_name: str = None) -> str:
        """This method creates the initial logging entry for when a load job is started.

        Args:
            target_zone: Name of the zone, that the load job targets.
            load_job_name: Name of the load job that gets executed.
            table_name: Name of the table that gets loaded.

        Returns:
            load_uuid that is used for logging this load job.
        """
        status_starting = "Starting"
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())
        load_uuid = str(uuid.uuid4())

        spark.sql(
            """
            INSERT INTO `%(catalog)s`.`%(zone)s`.loads (
                Load_UUID, Target_Zone, Job_Name, Table_Name, Insert_Time_UTC, Status
            ) VALUES (
                '%(load_uuid)s', '%(target_zone)s', '%(job)s', '%(table)s', current_timestamp(), '%(status)s'
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
                "load_uuid": load_uuid,
                "target_zone": target_zone,
                "job": load_job_name,
                "table": table_name,
                "status": status_starting,
            }
        )

        return load_uuid

    @staticmethod
    def update_load(load_uuid: str, target_zone: str, load_job_name: str,
                    table_name: str, status: str
                    ) -> None:
        """This method updates the status for a given load job log entry.

        Args:
            load_uuid: UUID of the load to update.
            status: New status to set for the given load.
            table_name: Name of the table that gets loaded.
        """
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        spark.sql(
            """
            INSERT INTO `%(catalog)s`.`%(zone)s`.loads (
                Load_UUID, Target_Zone, Job_Name, Table_Name, Insert_Time_UTC, Status
            ) VALUES (
                '%(load_uuid)s', '%(target_zone)s', '%(job)s', '%(table)s', current_timestamp(), '%(status)s'
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
                "load_uuid": load_uuid,
                "target_zone": target_zone,
                "job": load_job_name,
                "table": table_name,
                "status": status,
            }
        )

    @staticmethod
    def complete_load(load_uuid: str, target_zone: str, load_job_name: str,
                      table_name: str = None, status: str = "Completed"
                      ) -> None:
        """This method marks a log entry for a given load job log entry as completed.

        Args:
            load_uuid: UUID of the load to complete.
            status: Final status to set for the given load.
            table_name: Name of the table that was loaded completely.
        """
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        zone = spark.conf.get("datam8.zone.logging.name", "logging")
        catalog_name = spark.conf.get("datam8.catalog.name", spark.catalog.currentCatalog())

        spark.sql(
            """
            INSERT INTO `%(catalog)s`.`%(zone)s`.loads (
                Load_UUID, Target_Zone, Job_Name, Table_Name, Insert_Time_UTC, Status
            ) VALUES (
                '%(load_uuid)s', '%(target_zone)s', '%(job)s', '%(table)s', current_timestamp(), '%(status)s'
            )
            """ % {
                "catalog": catalog_name,
                "zone": zone,
                "load_uuid": load_uuid,
                "target_zone": target_zone,
                "job": load_job_name,
                "table": table_name,
                "status": status,
            }
        )

    @staticmethod
    def get_job_name() -> str | None:
        """
        This method returns the job name or None, if not run in job context.

        Returns:
            job_name: Name of the job
        """
        for tag in json.loads(spark.conf.get("spark.databricks.clusterUsageTags.clusterAllTags")):
            if tag["key"] == "RunName":
                return tag["value"]

        return None

    @staticmethod
    def get_value_dict() -> dict:
        return {
            var: dbutils.jobs.taskValues.get(
                taskKey="Generate_Load_UUID",
                key=var,
                default=(-1 if var == "load_uuid" else "Debug"),
                debugValue=(-1 if var == "load_uuid" else "Debug"),
                )
            for var in ("load_uuid", "target_zone", "load_job_name",)
        }
