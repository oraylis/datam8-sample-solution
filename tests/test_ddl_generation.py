import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Generate/databricks-lake/__modules"))

from payload_helpers import build_create_table_sql


class DdlGenerationTests(unittest.TestCase):
    def test_complete_create_statement_is_generated_with_runtime_catalog_only(self):
        statement = build_create_table_sql(
            zone="stage",
            full_table_name="masterdata_customer_customer",
            columns=[
                {
                    "name": "CustomerSID",
                    "delta_type": "BIGINT",
                    "delta_nullable": False,
                    "delta_comment": None,
                    "metadata": {"surrogate_key": True},
                },
                {
                    "name": "CustomerName",
                    "delta_type": "STRING",
                    "delta_nullable": True,
                    "delta_comment": "Customer's display name",
                    "metadata": {},
                },
            ],
            partitions=["CustomerID"],
            table_comment="Customer's current profile",
            table_properties={"delta.columnMapping.mode": "name"},
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS `{catalog_name}`.`stage`.`masterdata_customer_customer`", statement)
        self.assertIn("`CustomerSID` BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL", statement)
        self.assertIn("COMMENT 'Customer''s display name'", statement)
        self.assertIn("PRIMARY KEY (`CustomerSID`) RELY", statement)
        self.assertIn("CLUSTER BY (`CustomerID`)", statement)
        self.assertIn("TBLPROPERTIES ('delta.columnMapping.mode'='name')", statement)
        self.assertTrue(statement.endswith(";"))


if __name__ == "__main__":
    unittest.main()
