"""Exercise the public sample binding against the real bundled SQL Server host."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import polars as pl

from datam8.plugins import PluginManager, init_builtin_plugins
from datam8_model.data_source import DataSource, DataSourceType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Generate/databricks-lake/__modules"))
from metadata_utils import source_reader_kind


class PublicEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_types = json.loads((ROOT / "Base/DataSourceTypes.json").read_text())
        cls.source_type = DataSourceType.model_validate(source_types["dataSourceTypes"][0])
        init_builtin_plugins(plugin_id=cls.source_type.pluginId)
        cls.plugin_class = PluginManager().get_plugin(cls.source_type.pluginId)

    def test_saved_connection_forms_match_the_public_builtin(self):
        self.assertEqual(self.source_type.pluginId, "builtin:SQLServer")
        properties = {item.name: item for item in self.source_type.connectionProperties}
        for expected in self.plugin_class.get_connection_properties():
            actual = properties.pop(expected.name)
            self.assertEqual((actual.type, actual.required, actual.default),
                             (expected.type, expected.required, expected.default))
        self.assertFalse(properties)
        self.assertEqual(self.source_type.authModes, self.plugin_class.get_auth_modes())

    def test_real_builtin_metadata_preserves_source_types_and_sample_mappings(self):
        sources = json.loads((ROOT / "Base/DataSources.json").read_text())
        source = DataSource.model_validate(sources["dataSources"][0])
        source.extendedProperties["password"] = "fixture:sql-password"
        with patch("datam8.plugins.base.SecretResolver") as secrets:
            secrets.return_value.get_secret.return_value = "local-fixture-only"
            plugin = self.plugin_class(self.plugin_class.manifest(), source, self.source_type)
            secrets.return_value.get_secret.assert_called_once_with("fixture:sql-password")
        rows = pl.DataFrame({
            "ordinal": [1, 2], "name": ["CustomerID", "Amount"],
            "dataType": ["int", "decimal"], "maxLength": [None, None],
            "numericPrecision": [10, 18], "numericScale": [0, 2],
            "isNullable": ["NO", "YES"], "isPrimaryKey": [1, 0],
        })
        with patch.object(plugin, "_execute_query", return_value=rows) as query:
            fields = list(plugin.get_table_metadata("[SalesLT].[Fixture]").iter_source_fields())
        query.assert_called_once()
        self.assertEqual([(field.name, field.dataType) for field in fields],
                         [("CustomerID", "int"), ("Amount", "decimal")])
        self.assertEqual(fields[1].numbericScale, 2)
        mappings = {item.sourceType: item.targetType for item in self.source_type.dataTypeMapping}
        self.assertEqual([mappings[field.dataType] for field in fields], ["int", "decimal"])

    def test_host_binding_keeps_the_existing_generated_reader_kind(self):
        self.assertEqual(source_reader_kind(self.source_type.pluginId), "sqlserver")
        self.assertEqual(source_reader_kind("sqlserver"), "sqlserver")
        self.assertEqual(source_reader_kind("oracle"), "oracle")
        self.assertEqual(source_reader_kind("builtin:CsvFile"), "builtin:CsvFile")


if __name__ == "__main__":
    unittest.main()
