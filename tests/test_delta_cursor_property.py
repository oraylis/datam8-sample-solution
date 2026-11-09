import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generate/databricks-lake/__modules"))

from metadata_utils import delta_cursor_mappings, require_delta_cursor
from payload_helpers import _raw_mapping_projection


class DeltaCursorPropertyTests(unittest.TestCase):
    def test_delta_source_cursor_is_marked_on_mapping(self):
        sources = json.loads((ROOT / "base/DataSources.json").read_text())["dataSources"]
        delta_sources = []
        for path in (ROOT / "model").rglob("*.json"):
            if path.name == ".properties.json":
                continue
            entity = json.loads(path.read_text())
            for source in entity.get("sources", []):
                if "dataSource" not in source:
                    continue
                mode = next((p["value"] for p in source.get("properties", [])
                             if p["property"] == "extract_mode"), None)
                if mode == "delta":
                    delta_sources.append(source.get("mapping", []))
        self.assertTrue(delta_sources)
        for mappings in delta_sources:
            self.assertEqual(len(delta_cursor_mappings(mappings)), 1)

    def test_missing_or_ambiguous_delta_cursor_fails(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            require_delta_cursor([], "test source")
        mappings = [
            {"source": "ModifiedAt", "properties": {"extract_mode": "delta"}},
            {"source": "UpdatedAt", "properties": {"extract_mode": "delta"}},
        ]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            require_delta_cursor(mappings, "test source")

    def test_model_mapping_property_objects_are_recognized(self):
        cursor = SimpleNamespace(properties=[SimpleNamespace(property="extract_mode", value="delta")])
        non_cursor = SimpleNamespace(properties=[SimpleNamespace(property="extract_mode", value="full")])
        self.assertIs(require_delta_cursor([non_cursor, cursor], "test source"), cursor)

    def test_raw_projection_uses_mapping_extract_mode_for_delta_column(self):
        class Resolver:
            @staticmethod
            def map_source_type_to_canonical(_source, source_type):
                return "datetime" if source_type == "datetime2" else None

        projection = _raw_mapping_projection(
            [
                {
                    "source": "ModifiedDate",
                    "target": "ModifiedDate",
                    "source_data_type": {"type": "datetime2"},
                    "properties": {"extract_mode": "delta"},
                },
                {
                    "source": "UpdatedBy",
                    "target": "UpdatedBy",
                    "source_data_type": {"type": "nvarchar"},
                    "properties": {},
                },
            ],
            resolver=Resolver(),
            data_source_name="AdventureWorks",
        )
        self.assertEqual(
            projection["delta_column_details"],
            [{"sourceName": "ModifiedDate", "canonicalDataType": "datetime"}],
        )


if __name__ == "__main__":
    unittest.main()
