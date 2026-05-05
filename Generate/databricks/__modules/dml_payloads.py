from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from datam8.model import EntityWrapper, Model
from datam8_model.attribute import HistoryType
from datam8_model.model import ExternalModelSource, ModelEntity
from datam8_model.zone import Zone
from payload_common import (
    ExternalSource,
    InternalSource,
    ModelEntityPayload,
    get_external_zone,
    get_one,
    zone_folder_name,
)


class MergeConfig:
    """Small container for merge, SCD, and assignment details used by DML templates.

    DML means "Data Manipulation Language": the code that inserts, updates, or
    merges data into a table. This class centralizes the rules that decide which
    columns are inserted, which columns are updated, and how rows are matched.
    """

    def __init__(
        self,
        entity: ModelEntity,
        history: dict[str, list[str]],
        attribute_names: list[str],
        *,
        write_mode: str,
        include_source_timestamp: bool,
        include_source_table: bool,
        include_business_function: bool,
    ) -> None:
        """Store all values needed to build merge logic for one entity."""
        self.entity = entity
        self.history = history
        self.attribute_names = attribute_names
        self.write_mode = write_mode
        self.include_source_timestamp = include_source_timestamp
        self.include_source_table = include_source_table
        self.include_business_function = include_business_function

    @staticmethod
    def assignment_literal(column: str, expression: str) -> dict[str, str]:
        """Build one column assignment in the structure expected by templates."""
        return {"column": column, "expression": repr(expression)}

    @staticmethod
    def scd0_helper_name(column: str) -> str:
        """Create a stable helper column name for comparing SCD0 values."""
        sanitized = re.sub(r"\W+", "_", column or "").strip("_") or "value"
        return f"__scd0__{sanitized}"

    @property
    def business_keys(self) -> list[str]:
        """Return the columns that identify one business row."""
        return self.history["business_keys"]

    @property
    def sk_columns(self) -> set[str]:
        """Return generated surrogate key columns that should not be overwritten."""
        return {
            attr.name
            for attr in self.entity.attributes
            if any(
                ref.property.lower() == "attribute_type" and ref.value.lower() == "sk"
                for ref in attr.properties or []
            )
        }

    @property
    def enabled(self) -> bool:
        """Return whether merge mode can run for this entity."""
        return self.write_mode == "merge" and bool(self.business_keys)

    @property
    def assignment_names(self) -> list[str]:
        """Return model columns that should receive insert or update assignments."""
        if self.write_mode == "merge" and self.sk_columns:
            return [name for name in self.attribute_names if name not in self.sk_columns]
        return self.attribute_names

    @property
    def scd0_columns(self) -> list[str]:
        """Return columns that should never change after insert."""
        return self.history["scd0"]

    @property
    def scd1_columns(self) -> list[str]:
        """Return columns that should be updated in place when values change."""
        columns = [name for name in self.history["scd1"] if name not in self.business_keys]
        if self.write_mode == "merge" and self.sk_columns:
            columns = [name for name in columns if name not in self.sk_columns]
        return columns

    @property
    def scd2_non_business_columns(self) -> list[str]:
        """Return non-key columns that should create a new history version when changed."""
        columns = [name for name in self.history["scd2"] if name not in self.business_keys]
        if self.write_mode == "merge" and self.sk_columns:
            columns = [name for name in columns if name not in self.sk_columns]
        return columns

    @property
    def has_scd2_history(self) -> bool:
        """Return whether SCD2 versioning is needed."""
        return bool(self.scd2_non_business_columns)

    @property
    def scd0_helper_columns(self) -> list[dict[str, str]]:
        """Return helper column mappings used to compare SCD0 values."""
        return [
            {"column": column, "helper": self.scd0_helper_name(column)}
            for column in self.scd0_columns
        ]

    @property
    def scd0_helper_lookup(self) -> dict[str, str]:
        """Return a lookup from original SCD0 column name to helper column name."""
        return {entry["column"]: entry["helper"] for entry in self.scd0_helper_columns}

    @property
    def scd1_update_assignments(self) -> list[dict[str, str]]:
        """Return assignments for SCD1 updates."""
        assignments = [
            self.assignment_literal(name, f"src.`{name}`") for name in self.scd1_columns
        ]
        if self.scd1_columns:
            assignments.append(
                self.assignment_literal("__UpdateTimestampUTC", "src.__UpdateTimestampUTC")
            )
        return assignments

    @property
    def scd1_change_condition(self) -> str:
        """Return the SQL condition that detects SCD1 value changes."""
        return " OR ".join(
            f"NOT (tgt.`{column}` <=> src.`{column}`)" for column in self.scd1_columns
        )

    @property
    def insert_assignments(self) -> list[dict[str, str]]:
        """Return all assignments used when a new row is inserted."""
        technical_columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
        if self.include_business_function:
            technical_columns.append("__BusinessFunction")
        if self.include_source_table:
            technical_columns.append("__SourceTable")
        if self.include_source_timestamp:
            technical_columns.append("__InsertTimestampSourceUTC")

        assignments = [
            self.assignment_literal(column, f"src.{column}") for column in technical_columns
        ]
        assignments.extend(
            self.assignment_literal(name, f"src.`{name}`") for name in self.assignment_names
        )
        return assignments

    @property
    def merge_condition(self) -> str:
        """Return the SQL condition that matches source and target rows by business key."""
        return " AND ".join(f"tgt.`{col}` <=> src.`{col}`" for col in self.business_keys)


class DmlPayload(ModelEntityPayload):
    """Render payload for the main DML notebook of a model entity.

    One instance represents the notebook that loads one modeled table. It knows
    whether the data comes from external extracts, other modeled tables, or
    transformation functions.
    """

    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        model: Model,
        transformations: list[dict[str, Any]],
    ) -> None:
        """Initialize source, transformation, and merge information for one entity."""
        super().__init__(wrapper, model)
        self.transformations = transformations
        self.external_source_items = [
            ExternalSource(model, wrapper, source)
            for source in wrapper.entity.sources or []
            if getattr(source, "dataSource", None)
        ]
        self.internal_source_items: list[InternalSource] = []
        if not transformations:
            for source in wrapper.entity.sources or []:
                if getattr(source, "dataSource", None):
                    continue
                self.internal_source_items.append(InternalSource(model, wrapper, source))

    def get_output_path(self) -> Path:
        """Return where the generated DML notebook should be written."""
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.wrapper.locator.entityName or self.entity.name}.py",
        )

    @property
    def history(self) -> dict[str, list[str]]:
        """Group attributes by business key, SCD0, SCD1, and SCD2 behavior."""
        history = {
            "business_keys": [attr.name for attr in self.entity.attributes if attr.isBusinessKey],
            "scd0": [],
            "scd1": [],
            "scd2": [],
        }
        for attr in self.entity.attributes:
            match attr.history:
                case HistoryType.SCD0:
                    history["scd0"].append(attr.name)
                case HistoryType.SCD2:
                    history["scd2"].append(attr.name)
                case _:
                    history["scd1"].append(attr.name)
        return history

    @property
    def attribute_columns(self) -> list[str]:
        """Return all business attribute column names in model order."""
        return [attr.name for attr in self.entity.attributes]

    @property
    def source_mode(self) -> str:
        """Return the loading strategy used by this notebook."""
        if self.transformations:
            return "transformation"
        if self.delta_source_items:
            return "source_delta"
        return "none"

    @property
    def has_external_source(self) -> bool:
        """Return whether the entity reads directly from external sources."""
        return bool(self.external_source_items)

    @property
    def has_internal_source(self) -> bool:
        """Return whether the entity reads from other modeled entities."""
        return bool(self.internal_source_items)

    @property
    def include_source_timestamp(self) -> bool:
        """Return whether the generated schema includes the source insert timestamp."""
        return self.source_mode == "source_delta"

    @property
    def include_source_table(self) -> bool:
        """Return whether the generated schema includes the source table name."""
        return self.source_mode == "source_delta"

    @property
    def include_business_function(self) -> bool:
        """Return whether the generated schema includes the transformation function name."""
        return self.source_mode == "transformation"

    @property
    def write_mode(self) -> str:
        """Return the configured write mode, defaulting to `overwrite`."""
        return self.wrapper_property("write_mode", "overwrite")

    @property
    def spark_write_mode(self) -> str:
        """Return the Spark write mode for non-merge writes."""
        return {"overwrite": "overwrite", "append": "append"}.get(self.write_mode, "overwrite")

    @property
    def external_sources(self) -> list[ExternalSource]:
        """Return prepared external source wrappers for the template."""
        return self.external_source_items

    @property
    def internal_sources(self) -> list[InternalSource]:
        """Return prepared internal source wrappers for the template."""
        return self.internal_source_items

    @property
    def delta_source_items(self) -> list[ExternalSource | InternalSource]:
        """Return sources that can participate in delta-style loading."""
        if self.external_source_items:
            return self.external_source_items
        return self.internal_source_items

    @property
    def delta_sources(self) -> list[ExternalSource | InternalSource]:
        """Return delta source wrappers using the name expected by older templates."""
        return self.delta_source_items

    @property
    def needs_latest_snapshot_handling(self) -> bool:
        """Return whether external extracts need latest-snapshot filtering."""
        return bool(self.external_source_items)

    @property
    def final_function_key(self) -> str | None:
        """Return the key of the last transformation function, if one exists."""
        return self.transformations[-1]["key"] if self.transformations else None

    @property
    def business_keys(self) -> list[str]:
        """Return the business key columns for this entity."""
        return self.history["business_keys"]

    @property
    def non_business_columns(self) -> list[str]:
        """Return attribute columns that are not business keys."""
        return [name for name in self.attribute_columns if name not in self.business_keys]

    @property
    def schema_columns(self) -> list[str]:
        """Return technical and business columns expected in the final dataframe."""
        columns = ["__InsertTimestampUTC", "__UpdateTimestampUTC"]
        if self.include_business_function:
            columns.append("__BusinessFunction")
        if self.include_source_table:
            columns.append("__SourceTable")
        if self.include_source_timestamp:
            columns.append("__InsertTimestampSourceUTC")
        columns.extend(self.attribute_columns)
        return columns

    @property
    def write_schema_columns(self) -> list[str]:
        """Return columns written by Spark, excluding generated surrogate keys."""
        return [column for column in self.schema_columns if column not in self.surrogate_key_columns]

    @property
    def merge_config(self) -> MergeConfig:
        """Return the merge configuration for this entity."""
        return MergeConfig(
            self.entity,
            self.history,
            self.attribute_columns,
            write_mode=self.write_mode,
            include_source_timestamp=self.include_source_timestamp,
            include_source_table=self.include_source_table,
            include_business_function=self.include_business_function,
        )

    @property
    def merge_conditions_flat(self) -> str:
        """Return the merge join condition as plain SQL text."""
        return self.merge_config.merge_condition

    @property
    def source_references(self) -> list[Any]:
        """Return source references; currently kept empty for template compatibility."""
        return []

    @property
    def has_lookup_dimensions(self) -> bool:
        """Return whether dimension lookup generation is enabled."""
        return False

    @property
    def dimension_lookups(self) -> list[Any]:
        """Return dimension lookup definitions; currently none are generated."""
        return []

    @property
    def insert_assignments(self) -> list[dict[str, str]]:
        """Return insert assignments from the merge configuration."""
        return self.merge_config.insert_assignments

    @property
    def scd0_columns(self) -> list[str]:
        """Return SCD0 columns for the template."""
        return self.history["scd0"]

    @property
    def scd0_helper_columns(self) -> list[dict[str, str]]:
        """Return SCD0 helper columns for the template."""
        return self.merge_config.scd0_helper_columns

    @property
    def scd0_helper_lookup(self) -> dict[str, str]:
        """Return a lookup from SCD0 column to helper column."""
        return self.merge_config.scd0_helper_lookup

    @property
    def scd1_columns(self) -> list[str]:
        """Return SCD1 columns for the template."""
        return self.history["scd1"]

    @property
    def scd1_non_business_columns(self) -> list[str]:
        """Return SCD1 columns excluding business keys."""
        return [name for name in self.scd1_columns if name not in self.business_keys]

    @property
    def scd2_columns(self) -> list[str]:
        """Return SCD2 columns for the template."""
        return self.history["scd2"]

    @property
    def scd2_non_business_columns(self) -> list[str]:
        """Return SCD2 columns excluding business and surrogate keys."""
        return self.merge_config.scd2_non_business_columns

    @property
    def has_scd2_history(self) -> bool:
        """Return whether any attribute is configured as SCD2."""
        return bool(self.scd2_columns)

    @property
    def external_merge_config(self) -> MergeConfig | None:
        """Return merge settings for external-source loading, if applicable."""
        return self.source_merge_config if self.external_source_items else None

    @property
    def internal_merge_config(self) -> MergeConfig | None:
        """Return merge settings for internal-source loading, if applicable."""
        return self.source_merge_config if self.internal_source_items and not self.transformations else None

    @property
    def source_merge_config(self) -> MergeConfig | None:
        """Return merge settings for direct source loading, if merge mode is valid."""
        if self.merge_config.enabled and self.delta_source_items and not self.transformations:
            return self.merge_config
        return None

    @property
    def final_merge_config(self) -> MergeConfig | None:
        """Return merge settings for transformation output, if merge mode is valid."""
        if self.merge_config.enabled and self.transformations:
            return self.merge_config
        return None

    @property
    def calculated_columns(self) -> list[dict[str, str]]:
        """Return columns whose values are calculated with an expression."""
        columns: list[dict[str, str]] = []
        for attr in self.entity.attributes:
            expr = getattr(attr, "calculation", None) or getattr(attr, "expression", None)
            if expr:
                columns.append(
                    {
                        "name": attr.name,
                        "expression": expr,
                        "expression_literal": repr(expr),
                    }
                )
        return columns


class DmlExternalPayload(ModelEntityPayload):
    """Render payload for an external-source extraction notebook.

    This notebook reads from a configured source system and writes into the raw
    external landing table.
    """

    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        model: Model,
        source: ExternalModelSource,
    ) -> None:
        """Initialize extraction data for one external source definition."""
        super().__init__(wrapper, model)
        self.source = source
        self.external_source = ExternalSource(model, wrapper, source)
        self.zone_wrapper = get_external_zone(model)
        self.data_source_entry = get_one(model.dataSources, self.external_source.data_source).entity

    def get_data(self) -> object:
        """Return this object as the template data object."""
        return self

    def get_output_path(self) -> Path:
        """Return where the generated external DML notebook should be written."""
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.table_name}.py",
        )

    @property
    def data_source_display(self) -> str:
        """Return the readable source system name."""
        return self.data_source_entry.displayName or self.external_source.data_source

    @property
    def table_name(self) -> str:
        """Return the generated external landing table name."""
        return self.external_source.table_name

    @property
    def full_table_name(self) -> str:
        """Return the full generated external landing table name."""
        return self.external_source.full_table_name

    @property
    def data_source(self) -> str:
        """Return the configured data source key."""
        return self.external_source.data_source

    @property
    def source_name(self) -> str:
        """Return the source alias or table name to read from."""
        return self.external_source.source_name

    @property
    def source_location(self) -> str:
        """Return the physical source location, such as a table or query name."""
        return self.external_source.source_location

    @property
    def data_source_type(self) -> str:
        """Return the type of source system, for example a database type."""
        return self.external_source.data_source_type

    @property
    def data_source_extended_properties(self) -> dict[str, Any]:
        """Return additional source system settings configured in the model."""
        return self.external_source.data_source_extended_properties

    @property
    def column_renames(self) -> list[dict[str, str]]:
        """Return source-to-target column renames."""
        return self.external_source.column_renames

    @property
    def delta_column_details(self) -> list[dict[str, str]]:
        """Return source columns used to detect delta changes."""
        return self.external_source.delta_column_details

    @property
    def target_columns(self) -> list[str]:
        """Return target column names written by the extraction notebook."""
        return self.external_source.target_columns

    @property
    def extract_mode(self) -> str | None:
        """Return the configured extraction mode, such as `delta` or `overwrite`."""
        return self.external_source.extract_mode

    @property
    def write_mode(self) -> str:
        """Return whether extracted data should overwrite or append to the landing table."""
        return "overwrite" if self.extract_mode == "overwrite" else "append"

    @property
    def use_connector(self) -> bool:
        """Return whether a Databricks connector id is configured for this source."""
        return bool(getattr(self.data_source_entry, "connector", None))

    @property
    def connector_id(self) -> str | None:
        """Return the configured Databricks connector id, if any."""
        return getattr(self.data_source_entry, "connector", None)

    @property
    def is_query(self) -> bool:
        """Return whether the source location should be treated as a query."""
        return str(self.extract_mode or "").lower() == "query"

    @property
    def query_plan(self) -> dict[str, Any]:
        """Return query-related flags used by the extraction template."""
        return {
            "is_query": self.is_query,
            "has_delta_filter": str(self.extract_mode or "").lower() == "delta",
            "timestamp_delta": False,
            "delta_columns_csv": ", ".join(item["source"] for item in self.delta_column_details),
        }

    @property
    def driver(self) -> str:
        """Return the JDBC driver class used by the SQL Server extractor."""
        return "com.microsoft.sqlserver.jdbc.SQLServerDriver"

    @property
    def connection_secret_key(self) -> str:
        """Return the Databricks secret key name for the data source password."""
        return f"datasource-{self.external_source.data_source}-password"

    @property
    def delta_column(self) -> str | None:
        """Return the target-side delta column name, if one is configured."""
        if self.delta_column_details:
            return self.delta_column_details[0]["target"]
        return None

    @property
    def source_delta_column(self) -> str | None:
        """Return the source-side delta column name, if one is configured."""
        if self.delta_column_details:
            return self.delta_column_details[0]["source"]
        return None


class DmlFunctionPayload(ModelEntityPayload):
    """Render payload for a Python transformation function file.

    The generator copies model-side Python functions next to the generated DML
    notebook so Databricks can import and call them.
    """

    def __init__(
        self,
        wrapper: EntityWrapper[ModelEntity],
        zone: EntityWrapper[Zone],
        model: Model,
        transform: dict[str, Any],
    ) -> None:
        """Initialize payload data for one transformation script."""
        super().__init__(wrapper, model)
        self.zone_wrapper = zone
        self.transform = transform

    def get_data(self) -> object:
        """Return this object as the template data object."""
        return self

    def get_output_path(self) -> Path:
        """Return where the copied transformation script should be written."""
        return Path(
            "notebooks",
            zone_folder_name(self.zone_wrapper),
            "dml",
            *self.wrapper.locator.folders[1:],
            f"{self.wrapper.locator.entityName}_functions",
            self.transform["script_name"],
        )

    @property
    def content(self) -> str:
        """Return the original Python script content."""
        return self.transform["script_content"]


