import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Generate" / "databricks-lakeflow" / "__modules"))

from dataset_plan import Dataset, extraction_plan, function_sources, source_extract_column, source_table
from native_payloads import ingestion_groups, job_compute, job_schedules, load_tasks, pipeline_groups
sys.path.insert(0, str(ROOT / "Generate" / "databricks-lakeflow" / "runtime"))
from dataset_frames import try_cast_expression


def dataset(key, job, zone, dependencies=()):
    return Dataset(
        key=key,
        name=key.split(".", 1)[1],
        zone=zone,
        job=job,
        kind="materialized_view",
        write_mode="overwrite",
        columns=[],
        dependencies=set(dependencies),
        job_display={"daily": "Sales (Daily)", "weekly": "Sales (Weekly)"}.get(job, job),
    )


class LakeflowPlanningTests(unittest.TestCase):
    def test_pipeline_compute_comes_from_nested_model_job_cluster(self):
        model = SimpleNamespace(propertyValues={
            "job": SimpleNamespace(entity=SimpleNamespace(
                name="sales_daily", property="jobs",
                properties=[SimpleNamespace(property="cluster", value="extra_small")],
            )),
            "cluster": SimpleNamespace(entity=SimpleNamespace(
                name="extra_small", property="cluster", node_type="Standard_D4ds_v5", num_workers=2,
            )),
        })
        self.assertEqual(job_compute(model, "sales_daily"), {
            "serverless": False,
            "clusters": [{"label": "default", "node_type_id": "Standard_D4ds_v5", "num_workers": 2}],
        })

    def test_pipeline_compute_rejects_missing_or_unresolved_job_cluster(self):
        missing = SimpleNamespace(propertyValues={
            "job": SimpleNamespace(entity=SimpleNamespace(name="daily", property="jobs", properties=[])),
        })
        with self.assertRaisesRegex(ValueError, "must reference a cluster property"):
            job_compute(missing, "daily")

        unresolved = SimpleNamespace(propertyValues={
            "job": SimpleNamespace(entity=SimpleNamespace(name="daily", property="jobs", properties=[SimpleNamespace(property="cluster", value="missing")])),
        })
        with self.assertRaisesRegex(ValueError, "unknown cluster"):
            job_compute(unresolved, "daily")

    def test_target_types_use_try_cast_after_model_mapping(self):
        self.assertEqual(try_cast_expression("Sales`Amount", "DECIMAL(19,2)"), "try_cast(`Sales``Amount` AS DECIMAL(19,2))")

    def test_source_extraction_modes_keep_full_delta_and_query_distinct(self):
        full = extraction_plan("full", "sqlserver", "[SalesLT].[Customer]", "ModifiedDate")
        self.assertEqual((full["schema"], full["table"], full["extract_mode"]), ("SalesLT", "Customer", "full"))
        self.assertIsNone(extraction_plan("query", "sqlserver", "SELECT * FROM SalesLT.Customer", None))
        self.assertIsNone(extraction_plan("full", "sqlserver", "SELECT * FROM SalesLT.Customer", None))
        with self.assertRaisesRegex(ValueError, "physical query-based source table"):
            extraction_plan("delta", "sqlserver", "SELECT * FROM SalesLT.Customer", "ModifiedDate")
        with self.assertRaisesRegex(ValueError, "exactly one mapped"):
            extraction_plan("delta", "sqlserver", "[SalesLT].[Customer]", None)
        self.assertEqual(extraction_plan("delta", "sqlserver", "[SalesLT].[Customer]", "ModifiedDate")["cursor_column"], "ModifiedDate")

    def test_source_table_parses_quoted_and_unquoted_names(self):
        self.assertEqual(source_table("SalesLT.Customer", "sqlserver"), {"schema": "SalesLT", "table": "Customer"})
        self.assertEqual(source_table('[SalesLT].[Customer]', "sqlserver"), {"schema": "SalesLT", "table": "Customer"})

    def test_delta_cursor_is_read_from_the_source_mapping(self):
        source = SimpleNamespace(mapping=[SimpleNamespace(sourceName="modifiedat", properties=[SimpleNamespace(property="extract_column", value="delta")])])
        self.assertEqual(source_extract_column(source), "modifiedat")
        source.mapping.append(SimpleNamespace(sourceName="updatedat", properties=[SimpleNamespace(property="extract_column", value="delta")]))
        with self.assertRaisesRegex(ValueError, "exactly one marked cursor"):
            source_extract_column(source)

    def test_same_model_job_spans_layers_in_one_stable_pipeline(self):
        raw = dataset("raw.orders", "daily", "raw")
        stage = dataset("stage.orders", "daily", "stage", [raw.key])
        core = dataset("core.orders", "daily", "core", [stage.key])
        curated = dataset("curated.sales", "weekly", "curated", [core.key])

        groups = pipeline_groups([raw, stage, core, curated])
        self.assertEqual([item[0] for item in groups], ["pipeline_daily", "pipeline_weekly"])
        self.assertEqual(groups[0][2], set())
        self.assertEqual(groups[1][2], {"pipeline_daily"})
        self.assertEqual([item.key for item in groups[0][1]], ["raw.orders", "stage.orders", "core.orders"])

    def test_each_load_job_refreshes_only_its_pipeline_and_ingestion(self):
        daily_raw = dataset("raw.daily_orders", "daily", "raw")
        daily_raw.external = {"connection_suffix": "sqlserver", "managed_ingestion": {"source": "daily"}}
        daily_stage = dataset("stage.daily_orders", "daily", "stage", [daily_raw.key])
        weekly_raw = dataset("raw.weekly_orders", "weekly", "raw")
        weekly_raw.external = {"connection_suffix": "sqlserver", "managed_ingestion": {"source": "weekly"}}
        weekly_stage = dataset("stage.weekly_orders", "weekly", "stage", [weekly_raw.key])
        weekly_fact = dataset("curated.sales", "weekly", "curated", [daily_stage.key, weekly_stage.key])
        values = [daily_raw, daily_stage, weekly_raw, weekly_stage, weekly_fact]

        groups = ingestion_groups(values)
        self.assertEqual(set(groups), {"ingest_daily_sqlserver", "ingest_weekly_sqlserver"})
        daily_tasks = load_tasks("pipeline_daily", values, full_refresh=False)
        weekly_tasks = load_tasks("pipeline_weekly", values, full_refresh=False)
        self.assertEqual([task["task_key"] for task in daily_tasks], ["refresh_ingest_daily_sqlserver", "refresh_daily"])
        self.assertEqual([task["task_key"] for task in weekly_tasks], ["refresh_ingest_weekly_sqlserver", "refresh_weekly"])
        self.assertNotIn("depends_on", weekly_tasks[0])
        self.assertEqual(weekly_tasks[1]["depends_on"], [{"task_key": "refresh_ingest_weekly_sqlserver"}])

        pipeline_plan = pipeline_groups(values)
        self.assertEqual(pipeline_plan[1][2], {"pipeline_daily"})

    def test_snapshot_merge_always_builds_native_cdc_history(self):
        value = dataset("stage.customer", "daily", "stage")
        value.write_mode = "merge"
        value.keys = ["CustomerID"]
        value.columns = [{"name": "CustomerID", "type": "bigint"}]
        value.validate()
        self.assertEqual(value.history_name, "stage.__history_customer")

        value.scd2 = ["LastName"]
        value.columns.append({"name": "LastName", "type": "string"})
        self.assertEqual(value.history_name, "stage.__history_customer")

    def test_pipeline_key_slug_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same technical pipeline key|Inconsistent display names"):
            pipeline_groups([dataset("raw.one", "sales-daily", "raw"), dataset("raw.two", "sales_daily", "raw")])

    def test_schedule_is_resolved_from_job_model_properties(self):
        model = SimpleNamespace(propertyValues={
            "schedule": SimpleNamespace(entity=SimpleNamespace(name="daily", property="schedules", cron="1 0")),
            "weekly": SimpleNamespace(entity=SimpleNamespace(name="weekly", property="schedules", cron="0 0 2 ? * SUN")),
            "job": SimpleNamespace(entity=SimpleNamespace(name="sales_daily", property="jobs", properties=[SimpleNamespace(property="schedules", value="daily")])),
            "weekly_job": SimpleNamespace(entity=SimpleNamespace(name="sales_weekly", property="jobs", properties=[SimpleNamespace(property="schedules", value="weekly")])),
        })
        self.assertEqual(job_schedules(model), {"sales_daily": "0 1 0 * * ?", "sales_weekly": "0 0 2 ? * SUN"})

    def test_model_rejects_cdc_options_on_materialized_views(self):
        value = dataset("curated.customer", "daily", "curated")
        value.sequence_by = "UpdatedAt"
        with self.assertRaisesRegex(ValueError, "only valid for streaming-table CDC"):
            value.validate()

    def test_model_rejects_delete_condition_without_cdc_sequence(self):
        value = dataset("core.customer", "daily", "core")
        value.kind = "streaming_table"
        value.write_mode = "merge"
        value.keys = ["CustomerID"]
        value.columns = [{"name": "CustomerID", "type": "int"}]
        value.delete_condition = "IsDeleted"
        with self.assertRaisesRegex(ValueError, "delete_condition requires sequence_by"):
            value.validate()

    def test_mutating_spark_sql_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transform.py"
            path.write_text('business_function = spark.sql("DELETE FROM sample")\n')
            wrapper = SimpleNamespace(source_file=path, entity=SimpleNamespace(
                name="Sample", transformations=[SimpleNamespace(kind="function", name="transform", stepNo=1, function=SimpleNamespace(source="transform.py"))]
            ))
            with self.assertRaisesRegex(ValueError, "contains an action or write"):
                function_sources(wrapper)


if __name__ == "__main__":
    unittest.main()
