import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Generate/shared"))
from uc_sources import database_query, fetch_http_rows


class Proxy:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.calls = []
        self.api_client = self

    def do(self, method, path, *, query):
        self.calls.append((method, path, query))
        result = next(self.pages)
        if isinstance(result, Exception):
            raise result
        return result


class SourceReaderTests(unittest.TestCase):
    def test_complete_cursor_snapshot_uses_only_uc_proxy(self):
        proxy = Proxy({"items": [{"id": 1}], "next_cursor": "next", "total": 2}, {"items": [{"id": 2}], "next_cursor": None, "total": 2})
        self.assertEqual(fetch_http_rows("sample_shipping", "shipments", proxy), [{"id": 1}, {"id": 2}])
        self.assertEqual(proxy.calls[1][2]["cursor"], "next")
        self.assertTrue(all(path.startswith("/api/2.0/unity-catalog/connections/sample_shipping/proxy/") for _, path, _ in proxy.calls))

    def test_partial_snapshots_fail(self):
        for pages in (({"items": [], "total": 1},), ({"items": []}, {"error": "access_denied"}), ({"items": [], "next_cursor": "same"}, {"items": [], "next_cursor": "same"})):
            with self.subTest(pages=pages):
                proxy = Proxy(*pages)
                if len(pages) == 2 and "error" in pages[1]:
                    pages[0]["next_cursor"] = "next"
                with self.assertRaises(ValueError):
                    fetch_http_rows("sample_shipping", "shipments", proxy)

    def test_nonretryable_error_does_not_disclose_response(self):
        with self.assertRaisesRegex(RuntimeError, "no snapshot was published") as error:
            fetch_http_rows("sample_shipping", "shipments", Proxy(RuntimeError("sensitive upstream details")))
        self.assertNotIn("sensitive", str(error.exception))

    def test_sqlserver_ordinary_table_and_filter(self):
        query, predicate = database_query("sample_sqlserver", "SELECT * FROM [SalesLT].[Customer] WHERE CustomerID > 100", "adventureworks", "sqlserver")
        self.assertIn("dbtable => 'SalesLT.Customer'", query)
        self.assertEqual(predicate, "CustomerID > 100")
        self.assertNotIn("host", query)

    def test_oracle_uses_service_binding(self):
        query, _ = database_query("sample_oracle", '"APP"."SUPPLIERS"', "SAMPLEPDB", "oracle")
        self.assertIn("service_name => 'SAMPLEPDB'", query)

    def test_proxy_endpoint_cannot_escape_connection(self):
        with self.assertRaises(ValueError):
            fetch_http_rows("sample_shipping", "../other", Proxy())


if __name__ == "__main__":
    unittest.main()
