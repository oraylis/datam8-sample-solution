import sys
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from databricks_jobs import execute_root, execution_plan, execution_tree, get_run
from run_integration_tests import assert_no_rows, check_active, deploy_bundle, drop_stale_pipeline_event_logs, ingestion_destination_tables, is_classic_archive_object, is_lakeflow_internal_object, pipeline_event_log_objects, pipeline_materialization_objects, require_existing_deployment, reset_classic_migration_failures, reset_orphaned_dataset_tables, retire_legacy_ingestion_pipelines, reusable_source_preflight, save_source_preflight, selected_deployment_args, sql, stale_pipeline_event_log_objects


def job(children=()):
    return {
        "tags": {"platform": "databricks-lake"},
        "tasks": [{"run_job_task": {"job_id": f"${{resources.jobs.{child}.id}}"}} for child in children],
    }


def run(identifier, result="SUCCESS", tasks=()):
    return {"run_id": identifier, "state": {"life_cycle_state": "TERMINATED", "result_state": result}, "tasks": list(tasks)}


def task(identifier, result="SUCCESS", **kwargs):
    return {"run_id": identifier, "task_key": str(identifier), "state": {"result_state": result}, **kwargs}


class ExecutionPlanTests(unittest.TestCase):
    def test_resume_resets_only_owned_tables_with_proven_identity_migration_errors(self):
        root_run = {"tasks": [{"task_key": "Create_core_tables", "child_run_id": 99}]}
        manifest = {"datasets": [
            {"key": "core.masterdata_address_address", "zone": "core"},
            {"key": "core.masterdata_customer_customeraddress", "zone": "core"},
            {"key": "core.inventory_stock_inventory", "zone": "core"},
        ]}
        calls = []

        def call(method, path):
            calls.append((method, path))
            if path.endswith("run_id=99"):
                return {"tasks": [
                    {"task_key": "core_masterdata_address_address", "run_id": 11, "state": {"result_state": "FAILED"}},
                    {"task_key": "core_masterdata_customer_customeraddress", "run_id": 12, "state": {"result_state": "FAILED"}},
                    {"task_key": "core_inventory_stock_inventory", "run_id": 13, "attempt_number": 0, "state": {"result_state": "FAILED"}},
                    {"task_key": "core_inventory_stock_inventory", "run_id": 14, "attempt_number": 1, "state": {"result_state": "SUCCESS"}},
                ]}
            if "run_id=11" in path:
                return {"error": "DELTA_IDENTITY_COLUMNS_EXPLICIT_INSERT_NOT_SUPPORTED"}
            if "run_id=12" in path:
                return {"error": "permission denied"}
            if "/unity-catalog/tables/" in path:
                return {"owner": "run-sp"}
            return {"error": "source query failed"}

        statements = []

        def query(statement):
            statements.append(statement)
            if statement.startswith("SELECT table_name"):
                return [["masterdata_address_address_1793260128"]]
            return []

        reset = reset_classic_migration_failures(root_run, manifest, "sample_dev", "run-sp", call, query)
        self.assertEqual(reset, ["core.masterdata_address_address_1793260128"])
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(statements), 2)
        self.assertIn("LOWER(table_name)", statements[0])
        self.assertIn("DROP TABLE `sample_dev`.`core`.`masterdata_address_address_1793260128`", statements[-1])

    def test_bound_lakeflow_deployment_selects_jobs_and_schemas_without_pipeline_acl_changes(self):
        resources = {"jobs": {"daily": {}, "weekly": {}}, "pipelines": {"daily_pipeline": {}}, "schemas": {"raw": {}}}
        before = {"jobs": {"daily": {"id": 1}, "weekly": {"id": 2}}, "pipelines": {"daily_pipeline": {"id": "pipeline"}}, "schemas": {"raw": {"id": "sample.raw"}}}
        plan = {"plan": {
            "resources.pipelines.daily_pipeline": {"action": "skip"},
            "resources.pipelines.daily_pipeline.permissions": {"action": "update"},
        }}
        with patch("run_integration_tests.cli", return_value=json.dumps(plan)):
            self.assertEqual(
                selected_deployment_args("databricks-lakeflow", resources, before, Path("bundle"), None, "dev", full_refresh=False),
                ["--select", "jobs.daily,jobs.weekly,schemas.raw"],
            )
        self.assertEqual(selected_deployment_args("databricks", resources, before, Path("bundle"), None, "dev", full_refresh=False), [])
        before["pipelines"]["daily_pipeline"].pop("id")
        self.assertEqual(selected_deployment_args("databricks-lakeflow", resources, before, Path("bundle"), None, "dev", full_refresh=False), [])

    def test_manifest_execution_plan_runs_each_load_job_once_in_dependency_order(self):
        resources = {"jobs": {"create": job(("create_raw",)), "create_raw": job(), "first": job(), "second": job()}}
        manifest = {"target": "databricks", "lifecycle": ["create", "load"], "execution_plan": {
            "create": {"job": "create", "depends_on": []},
            "load": [{"job": "second", "depends_on": ["first"]}, {"job": "first", "depends_on": []}],
        }}
        self.assertEqual(execution_plan(resources, manifest), [("create", "create"), ("load", "first"), ("load", "second")])

    def test_load_execution_rejects_nested_jobs_and_uses_manifest_dependencies(self):
        resources = {"jobs": {
            "first": job(),
            "second": job(),
            "independent": job(),
        }}
        manifest = {"target": "databricks", "lifecycle": ["load"], "execution_plan": {"load": [
            {"job": "first", "depends_on": []},
            {"job": "second", "depends_on": ["first"]},
            {"job": "independent", "depends_on": []},
        ]}}
        self.assertEqual(
            execution_plan(resources, manifest, required_phases=("load",)),
            [("load", "first"), ("load", "independent"), ("load", "second")],
        )
        resources["jobs"]["second"] = job(("first",))
        with self.assertRaisesRegex(ValueError, "must not invoke another load job"):
            execution_plan(resources, manifest, required_phases=("load",))

    def test_manifest_execution_plan_rejects_missing_job_and_cycles(self):
        with self.assertRaisesRegex(ValueError, "outside this bundle"):
            execution_plan({"jobs": {}}, {"lifecycle": ["load"], "execution_plan": {"load": [{"job": "missing", "depends_on": []}]}})
        with self.assertRaisesRegex(ValueError, "Cycle"):
            execution_plan({"jobs": {"a": job(), "b": job()}}, {"lifecycle": ["load"], "execution_plan": {"load": [{"job": "a", "depends_on": ["b"]}, {"job": "b", "depends_on": ["a"]}]}})


class OrphanedDatasetResetTests(unittest.TestCase):
    def test_legacy_ingestion_retirement_is_limited_to_known_idle_destinations(self):
        exists = True
        calls = []

        def call(method, path, body=None):
            nonlocal exists
            calls.append((method, path))
            if method == "DELETE":
                exists = False
                return {}
            if not exists:
                raise RuntimeError("HTTP 404 not found")
            return {"state": "IDLE", "spec": {"ingestion_definition": {"objects": [
                {"table": {"destination_catalog": "sample", "destination_schema": "raw", "destination_table": "cart"}},
            ]}}}

        stale = {("pipelines", "ingest_mysql")}
        deployment = {"pipelines": {"ingest_mysql": {"id": "pipeline-id"}}}
        manifest = {"datasets": [{"zone": "raw", "name": "cart", "external": {"plugin": "mysql"}}]}
        self.assertEqual(retire_legacy_ingestion_pipelines(stale, deployment, "sample", manifest, call), ["ingest_mysql"])
        self.assertEqual([method for method, _ in calls].count("DELETE"), 1)

    def test_legacy_ingestion_retirement_refuses_foreign_destination_or_active_pipeline(self):
        stale = {("pipelines", "ingest_mysql")}
        deployment = {"pipelines": {"ingest_mysql": {"id": "pipeline-id"}}}
        manifest = {"datasets": [{"zone": "raw", "name": "cart", "external": {"plugin": "mysql"}}]}
        deletes = []

        def foreign(method, path, body=None):
            if method == "DELETE":
                deletes.append(path)
                return {}
            return {"state": "IDLE", "spec": {"ingestion_definition": {"objects": [
                {"table": {"destination_catalog": "sample", "destination_schema": "raw", "destination_table": "other"}},
            ]}}}

        with self.assertRaisesRegex(RuntimeError, "unexpected table"):
            retire_legacy_ingestion_pipelines(stale, deployment, "sample", manifest, foreign)
        self.assertFalse(deletes)

        def active(method, path, body=None):
            return {"state": "RUNNING", "spec": {"ingestion_definition": {"objects": []}}}

        with self.assertRaisesRegex(RuntimeError, "active"):
            retire_legacy_ingestion_pipelines(stale, deployment, "sample", manifest, active)

    def test_destinations_are_limited_to_declared_ingestion_tables(self):
        resources = {"pipelines": {"mysql": {"catalog": "sample", "ingestion_definition": {"objects": [
            {"table": {"destination_schema": "raw", "destination_table": "cart"}},
        ]}}}}
        self.assertEqual(ingestion_destination_tables(resources, "sample"), {"sample.raw.cart"})

    def test_reset_drops_only_expected_materialized_views_with_deleted_owners(self):
        manifest = {"datasets": [{"zone": "raw", "name": "cart", "external": {"plugin": "mysql"}}, {"zone": "stage", "name": "returns"}, {"zone": "stage", "name": "customer", "helper": "__history_customer"}]}
        metadata = {
            "sample.raw.cart": {"name": "cart", "table_type": "MATERIALIZED_VIEW", "pipeline_id": "deleted"},
            "sample.stage.returns": {"name": "returns", "table_type": "STREAMING_TABLE", "pipeline_id": "active"},
        }
        calls = []
        def call(method, path):
            calls.append(path)
            if path == "/api/2.0/pipelines/deleted":
                raise RuntimeError("Error: The specified pipeline was not found")
            if path == "/api/2.0/pipelines/active":
                return {"state": "IDLE"}
            if path.endswith("sample.raw.cart"):
                return metadata["sample.raw.cart"]
            if path.endswith("sample.stage.returns"):
                return metadata["sample.stage.returns"]
            raise RuntimeError("Error: Table does not exist")
        statements = []
        dropped = reset_orphaned_dataset_tables("sample", manifest, {"pipelines": {"mysql": {"id": "deleted"}, "current": {"id": "active"}}}, statements.append, call)
        self.assertEqual(dropped, ["sample.raw.cart"])
        self.assertEqual(statements, ["DROP MATERIALIZED VIEW `sample`.`raw`.`cart`"])

    def test_reset_refuses_a_table_owned_by_another_existing_pipeline(self):
        manifest = {"datasets": [{"zone": "raw", "name": "cart", "external": {"plugin": "mysql"}}]}
        def call(method, path):
            if path.endswith("sample.raw.cart"):
                return {"name": "cart", "table_type": "MATERIALIZED_VIEW", "pipeline_id": "other"}
            return {"pipeline_id": "other"}
        with self.assertRaisesRegex(RuntimeError, "another existing pipeline"):
            reset_orphaned_dataset_tables("sample", manifest, {"pipelines": {"mysql": {"id": "active"}}}, lambda _: None, call)

    def test_reset_skips_expected_tables_not_created_yet(self):
        manifest = {"datasets": [{"zone": "raw", "name": "cart"}]}
        def call(method, path):
            raise RuntimeError("Error: Table 'sample.raw.cart' does not exist.")
        self.assertEqual(reset_orphaned_dataset_tables("sample", manifest, {}, lambda _: None, call), [])


class ExecutionTests(unittest.TestCase):
    def test_long_sql_request_uses_a_temporary_json_file(self):
        request_files = []

        def fake_cli(args, **kwargs):
            request_path = Path(args[-1][1:])
            request_files.append(request_path)
            body = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertGreater(len(body["statement"]), 32767)
            self.assertEqual(body["warehouse_id"], "warehouse")
            return json.dumps({"status": {"state": "SUCCEEDED"}, "result": {"data_array": [["ok"]]}})

        with patch("run_integration_tests.cli", side_effect=fake_cli):
            self.assertEqual(sql("SELECT " + "x" * 32768, warehouse="warehouse", profile=None), [["ok"]])
        self.assertEqual(len(request_files), 1)
        self.assertFalse(request_files[0].exists())

    def test_only_bound_pipeline_event_logs_are_owned_objects(self):
        resources = {"pipelines": {"raw": {"schema": "raw"}, "curated": {"schema": "curated"}}}
        deployment = {"pipelines": {"raw": {"id": "7631ad58-bc1e-47e3-9392-2152b7cb7699"}, "curated": {}}}
        self.assertEqual(pipeline_event_log_objects(resources, deployment), {"raw.event_log_7631ad58_bc1e_47e3_9392_2152b7cb7699"})

    def test_stale_event_logs_are_limited_to_bound_pipelines_selected_for_retirement(self):
        stale = {("pipelines", "legacy_mysql"), ("jobs", "obsolete_job")}
        deployment = {"pipelines": {
            "legacy_mysql": {"id": "7631ad58-bc1e-47e3-9392-2152b7cb7699"},
            "unrelated": {"id": "11111111-1111-1111-1111-111111111111"},
        }}
        expected = {"raw.event_log_7631ad58_bc1e_47e3_9392_2152b7cb7699"}
        self.assertEqual(stale_pipeline_event_log_objects(stale, deployment), expected)
        statements = []
        dropped = drop_stale_pipeline_event_logs(
            stale,
            deployment,
            expected | {"raw.event_log_11111111_1111_1111_1111_111111111111"},
            "sample",
            statements.append,
        )
        self.assertEqual(dropped, sorted(expected))
        self.assertEqual(statements, ["DROP TABLE IF EXISTS `sample`.`raw`.`event_log_7631ad58_bc1e_47e3_9392_2152b7cb7699`"])

    def test_only_bound_pipeline_materializations_for_model_mvs_are_owned(self):
        resources = {"pipelines": {"pipeline_sales_daily": {"schema": "stage"}}}
        deployment = {"pipelines": {"pipeline_sales_daily": {"id": "d0926fd1-d088-44b0-8fa6-bb422306dc39"}}}
        manifest = {"datasets": [
            {"pipeline": "pipeline_sales_daily", "zone": "stage", "kind": "materialized_view", "name": "masterdata_customer_customer", "helper": "stage.__history_masterdata_customer_customer"},
            {"pipeline": "pipeline_sales_daily", "zone": "stage", "kind": "materialized_view", "name": "masterdata_customer_customer_en"},
            {"pipeline": "pipeline_sales_daily", "zone": "stage", "kind": "streaming_table", "name": "ignored_stream"},
            {"pipeline": "pipeline_other", "zone": "stage", "kind": "materialized_view", "name": "ignored_other_pipeline"},
        ]}
        self.assertEqual(
            pipeline_materialization_objects(resources, deployment, manifest),
            {
                "stage.__materialization_mat_d0926fd1_d088_44b0_8fa6_bb422306dc39_masterdata_customer_customer_1",
                "stage.__materialization_mat_d0926fd1_d088_44b0_8fa6_bb422306dc39___history_masterdata_customer_customer_1",
                "stage.__materialization_mat_d0926fd1_d088_44b0_8fa6_bb422306dc39_masterdata_customer_customer_en_1",
            },
        )

    def test_only_uuid_scoped_lakeflow_tables_for_manifest_datasets_are_owned(self):
        manifest = {"datasets": [
            {"zone": "stage", "kind": "materialized_view", "pipeline": "pipeline_sales", "name": "masterdata_customer_customer", "helper": "stage.__history_masterdata_customer_customer"},
            {"zone": "raw", "kind": "streaming_table", "pipeline": "ingest_mysql", "name": "commerce_cart_cartitem"},
        ]}
        self.assertTrue(is_lakeflow_internal_object("stage.__staging_62baad33_2742_4796_8097_9e1114d9fdc2_masterdata_customer_customer", manifest))
        self.assertTrue(is_lakeflow_internal_object("stage.__e4cd2959_b079_4b56_b9c9_1edc6d340950___history_masterdata_customer_customer", manifest))
        self.assertTrue(is_lakeflow_internal_object("stage.__materialization_mat_d0926fd1_d088_44b0_8fa6_bb422306dc39___history_masterdata_customer_customer_1", manifest))
        self.assertTrue(is_lakeflow_internal_object("raw.__materialization_mat_7631ad58_bc1e_47e3_9392_2152b7cb7699_commerce_cart_cartitem_1", manifest))
        self.assertFalse(is_lakeflow_internal_object("stage.__materialization_mat_62baad33_2742_4796_8097_9e1114d9fdc2_unrelated_1", manifest))
        self.assertFalse(is_lakeflow_internal_object("stage.__staging_not-a-uuid_masterdata_customer_customer", manifest))

    def test_classic_schema_archive_is_limited_to_manifest_tables_and_epoch_suffixes(self):
        manifest = {"datasets": [{"zone": "raw", "name": "sales_orders_salesorderheader"}]}
        self.assertTrue(is_classic_archive_object("raw.sales_orders_salesorderheader_1793088290", manifest))
        self.assertFalse(is_classic_archive_object("raw.unrelated_1793088290", manifest))
        self.assertFalse(is_classic_archive_object("raw.sales_orders_salesorderheader_backup", manifest))

    def test_active_job_guard_batches_workspace_run_checks(self):
        calls = []
        def api(method, path):
            calls.append(path)
            return {"runs": [], "next_page_token": None}
        with tempfile.TemporaryDirectory() as folder, patch("run_integration_tests.cli", return_value="[]"):
            check_active(api, {"jobs": {"one": {"id": 1}, "two": {"id": 2}}, "pipelines": {}}, Path(folder), None)
        self.assertEqual(len(calls), 1)
        self.assertIn("active_only=true", calls[0])

    def test_active_job_guard_rejects_a_running_sample_job(self):
        def api(method, path):
            return {"runs": [{"job_id": 2}]}
        with tempfile.TemporaryDirectory() as folder, patch("run_integration_tests.cli", return_value="[]"):
            with self.assertRaisesRegex(RuntimeError, "sample job is running"):
                check_active(api, {"jobs": {"one": {"id": 1}, "two": {"id": 2}}, "pipelines": {}}, Path(folder), None)

    def test_active_guard_allows_only_an_explicitly_retired_missing_pipeline(self):
        def api(method, path):
            if path.startswith("/api/2.2/jobs/runs/list"):
                return {"runs": [], "next_page_token": None}
            raise RuntimeError("The specified pipeline legacy-id was not found")

        summary = {"jobs": {}, "pipelines": {"legacy": {"id": "legacy-id"}}}
        with tempfile.TemporaryDirectory() as folder, patch("run_integration_tests.cli", return_value="[]"):
            check_active(api, summary, Path(folder), None, allowed_missing_pipeline_ids={"legacy-id"})
            with self.assertRaisesRegex(RuntimeError, "not found"):
                check_active(api, summary, Path(folder), None)

    def test_source_preflight_is_reused_only_for_same_bindings(self):
        manifest = {"datasets": [{"key": "raw.source", "external": {"plugin": "sqlserver", "connection_suffix": "sqlserver", "location": "[db].[table]", "database": "db"}}]}
        environment = {"host": "https://workspace.example.invalid", "connection_prefix": "sample_"}
        with tempfile.TemporaryDirectory() as folder:
            report_dir = Path(folder)
            saved = save_source_preflight(report_dir, "dev", manifest, environment, {"sqlserver": 10})
            self.assertEqual(reusable_source_preflight(report_dir, "dev", manifest, environment), saved)
            changed = {**environment, "connection_prefix": "other_"}
            self.assertIsNone(reusable_source_preflight(report_dir, "dev", manifest, changed))

    def test_deployment_and_execution_principals_are_checked_separately(self):
        from run_integration_tests import require_deployment_identity
        environment = {"deployment_principal": "deploy-sp", "run_principal": "run-sp", "host": "https://workspace.example.invalid"}
        configuration = {"run_as": {"service_principal_name": "run-sp"}, "workspace": {"host": environment["host"]}}
        require_deployment_identity(configuration, {"applicationId": "deploy-sp"}, environment)
        require_deployment_identity(configuration, {"userName": "deploy-sp", "applicationId": None}, environment)
        with self.assertRaisesRegex(RuntimeError, "deployment service principal"):
            require_deployment_identity(configuration, {"userName": "run-sp"}, environment)
        configuration["run_as"]["service_principal_name"] = "deploy-sp"
        with self.assertRaisesRegex(RuntimeError, "execution service principal"):
            require_deployment_identity(configuration, {"applicationId": "deploy-sp"}, environment)

    def test_local_dev_override_requires_the_exact_authenticated_user(self):
        from run_integration_tests import require_deployment_identity
        environment = {"deployment_principal": "deploy-sp", "run_principal": "run-sp", "host": "https://workspace.example.invalid"}
        configuration = {"run_as": {"service_principal_name": "run-sp"}, "workspace": {"host": environment["host"]}}
        require_deployment_identity(configuration, {"userName": "f.kayser@oraylis.de"}, environment, local_user="f.kayser@oraylis.de")
        with self.assertRaisesRegex(RuntimeError, "requested user"):
            require_deployment_identity(configuration, {"userName": "someone-else@oraylis.de"}, environment, local_user="f.kayser@oraylis.de")

    def test_local_operator_identity_is_checked_separately_from_deployment_identity(self):
        from run_integration_tests import require_local_user_identity
        require_local_user_identity({"userName": "f.kayser@oraylis.de"}, "f.kayser@oraylis.de")
        with self.assertRaisesRegex(RuntimeError, "requested user"):
            require_local_user_identity({"userName": "someone-else@oraylis.de"}, "f.kayser@oraylis.de")

    def test_local_lakeflow_deployment_preserves_mixed_resource_owners(self):
        resources = {"jobs": {"daily": {}}, "pipelines": {"ingest": {}, "model": {}}, "schemas": {"raw": {}}}
        before = {"jobs": {"daily": {"id": "1"}}, "pipelines": {"ingest": {"id": "2"}, "model": {"id": "3"}}, "schemas": {"raw": {"id": "4"}}}
        operator_plan = {
            "ingest": {"action": "update", "permission_action": "skip"},
            "model": {"action": "update", "permission_action": "update"},
        }
        deployment_plan = {
            "ingest": {"action": "update", "permission_action": "update"},
            "model": {"action": "update", "permission_action": "skip"},
        }
        summary = {"jobs": {"daily": {"id": "1"}}, "pipelines": {"ingest": {"id": "2"}, "model": {"id": "3"}}, "schemas": {"raw": {"id": "4"}}}
        with patch("run_integration_tests.lakeflow_pipeline_plan", side_effect=[operator_plan, deployment_plan]), \
             patch("run_integration_tests.selected_deployment_args", side_effect=[["--select", "jobs.daily,schemas.raw,pipelines.ingest"], ["--select", "pipelines.model"]]) as select, \
             patch("run_integration_tests.cli") as run_cli, \
             patch("run_integration_tests.bundle_summary", return_value=summary):
            result = deploy_bundle("databricks-lakeflow", resources, before, Path("bundle"), "local", "deploy", "dev", full_refresh=True, local_user="f.kayser@oraylis.de")
        self.assertEqual(result, summary)
        self.assertEqual(select.call_count, 2)
        self.assertEqual(run_cli.call_count, 2)
        self.assertEqual(run_cli.call_args_list[0].kwargs["profile"], "local")
        self.assertEqual(run_cli.call_args_list[1].kwargs["profile"], "deploy")

    def test_local_lakeflow_deployment_refuses_unowned_pipeline_changes(self):
        resources = {"jobs": {}, "pipelines": {"daily": {}}, "schemas": {}}
        before = {"jobs": {}, "pipelines": {"daily": {"id": "1"}}, "schemas": {}}
        conflicting = {"daily": {"action": "update", "permission_action": "update"}}
        with patch("run_integration_tests.lakeflow_pipeline_plan", side_effect=[conflicting, conflicting]), \
             patch("run_integration_tests.cli") as run_cli:
            with self.assertRaisesRegex(RuntimeError, "No supplied deployment identity owns"):
                deploy_bundle("databricks-lakeflow", resources, before, Path("bundle"), "local", "deploy", "dev", full_refresh=False, local_user="f.kayser@oraylis.de")
        run_cli.assert_not_called()

    def test_local_lakeflow_skips_deployment_profile_when_it_has_no_owned_changes(self):
        resources = {"jobs": {"daily": {}}, "pipelines": {"ingest": {}, "model": {}}, "schemas": {"raw": {}}}
        before = {"jobs": {"daily": {"id": "1"}}, "pipelines": {"ingest": {"id": "2"}, "model": {"id": "3"}}, "schemas": {"raw": {"id": "4"}}}
        no_pipeline_changes = {
            "ingest": {"action": "skip", "permission_action": "skip"},
            "model": {"action": "skip", "permission_action": "skip"},
        }
        summary = {"jobs": {"daily": {"id": "1"}}, "pipelines": {"ingest": {"id": "2"}, "model": {"id": "3"}}, "schemas": {"raw": {"id": "4"}}}
        with patch("run_integration_tests.lakeflow_pipeline_plan", side_effect=[no_pipeline_changes, no_pipeline_changes]), \
             patch("run_integration_tests.selected_deployment_args", side_effect=[["--select", "jobs.daily,schemas.raw"], []]), \
             patch("run_integration_tests.cli") as run_cli, \
             patch("run_integration_tests.bundle_summary", return_value=summary):
            deploy_bundle("databricks-lakeflow", resources, before, Path("bundle"), "local", "deploy", "dev", full_refresh=False, local_user="f.kayser@oraylis.de")
        self.assertEqual(run_cli.call_count, 1)
        self.assertEqual(run_cli.call_args.kwargs["profile"], "local")

    def test_cli_uses_profile_specific_azure_config_dir_without_affecting_other_profiles(self):
        from run_integration_tests import cli_environment
        profile_map = json.dumps({"run-sp": "C:/temp/run-az"})
        with patch.dict(os.environ, {"DATABRICKS_PROFILE_AZURE_CONFIG_DIRS": profile_map}):
            self.assertEqual(cli_environment("run-sp")["AZURE_CONFIG_DIR"], "C:/temp/run-az")
            self.assertIsNone(cli_environment("local-user"))

    def test_existing_deployment_guard_rejects_unbound_and_removed_resources(self):
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            require_existing_deployment({"jobs": {"existing": {}}}, {"jobs": {}})
        with self.assertRaisesRegex(RuntimeError, "refusing resource deletion"):
            require_existing_deployment({"jobs": {}}, {"jobs": {"existing": {"id": "1"}}})

    def test_zero_key_in_integrity_result_is_still_a_violation(self):
        with patch("run_integration_tests.sql", return_value=[["0"]]):
            with self.assertRaises(RuntimeError):
                assert_no_rows("SELECT CustomerSID FROM invalid_rows", warehouse="test", profile=None)

    def test_task_pagination(self):
        def api(method, path):
            if "page_token=" in path:
                return {"tasks": [task(2)]}
            return {"tasks": [task(1)], "next_page_token": "next page"}
        self.assertEqual([t["run_id"] for t in get_run(api, 10)["tasks"]], [1, 2])

    def test_successful_retry_is_accepted_and_failed_attempt_is_reported(self):
        first = task(11, "FAILED", task_key="retry", attempt_number=0)
        second = task(12, task_key="retry", attempt_number=1)
        tree = execution_tree(lambda method, path: run(1, tasks=[second, first]), 1)
        self.assertEqual(tree["errors"], [])
        self.assertEqual(tree["runs"][0]["tasks"][0]["run_id"], 12)
        self.assertEqual(len(tree["runs"][0]["tasks"][0]["attempts"]), 2)

    def test_execute_root_repairs_only_selected_failed_tasks(self):
        calls = []
        completed = run(90, tasks=[task(91, task_key="refresh_sales_daily", attempt_number=1)])

        def api(method, path, body=None):
            calls.append((method, path, body))
            if path == "/api/2.2/jobs/runs/get?run_id=90&include_history=true":
                return {"repair_history": [
                    {"type": "ORIGINAL"},
                    {"type": "REPAIR", "id": 900},
                    {"type": "REPAIR", "id": 3},
                ]}
            if path == "/api/2.2/jobs/runs/repair":
                return {"repair_id": 2}
            if path == "/api/2.2/jobs/runs/get?run_id=90":
                return completed
            raise AssertionError(f"Unexpected API call: {method} {path}")

        receipts = []
        result = execute_root(
            api,
            17,
            timeout=10,
            poll_seconds=0,
            record=receipts.append,
            repair_run_id=90,
            rerun_tasks=["refresh_sales_daily"],
        )
        self.assertEqual(result["result"], "passed")
        self.assertIn(
            ("POST", "/api/2.2/jobs/runs/repair", {"run_id": 90, "rerun_tasks": ["refresh_sales_daily"], "latest_repair_id": 3}),
            calls,
        )
        self.assertEqual(receipts[0]["repair_id"], 2)
        self.assertEqual(receipts[0]["repaired_tasks"], ["refresh_sales_daily"])

    def test_parent_success_does_not_hide_disabled_grandchild(self):
        responses = {
            "/api/2.2/jobs/runs/get?run_id=1": run(1, tasks=[task(11, run_job_task={"job_id": 2})]),
            "/api/2.2/jobs/runs/get-output?run_id=11": {"run_job_output": {"run_id": 2}},
            "/api/2.2/jobs/runs/get?run_id=2": run(2, tasks=[task(21, run_job_task={"job_id": 3})]),
            "/api/2.2/jobs/runs/get-output?run_id=21": {"run_job_output": {"run_id": 3}},
            "/api/2.2/jobs/runs/get?run_id=3": run(3, tasks=[task(31, "DISABLED")]),
        }
        tree = execution_tree(lambda method, path: responses[path], 1)
        self.assertEqual(len(tree["runs"]), 3)
        self.assertTrue(any("DISABLED" in error for error in tree["errors"]))

    def test_missing_nested_run_is_failure(self):
        responses = {
            "/api/2.2/jobs/runs/get?run_id=1": run(1, tasks=[task(11, run_job_task={"job_id": 2})]),
            "/api/2.2/jobs/runs/get-output?run_id=11": {},
        }
        self.assertTrue(execution_tree(lambda method, path: responses[path], 1)["errors"])

    def test_pipeline_requires_completed_update_in_task_window(self):
        responses = {
            "/api/2.2/jobs/runs/get?run_id=1": run(1, tasks=[task(11, start_time=100, end_time=200, pipeline_task={"pipeline_id": "p"})]),
            "/api/2.0/pipelines/p/updates": {"updates": [{"creation_time": 150, "update_id": "u", "state": "FAILED"}]},
        }
        self.assertTrue(any("FAILED" in error for error in execution_tree(lambda method, path: responses[path], 1)["errors"]))

    def test_timeout_cancels_parent_and_child(self):
        cancellations = []
        def api(method, path, body=None):
            if path.endswith("run-now"):
                return {"run_id": 1}
            if path.endswith("cancel"):
                cancellations.append(body["run_id"])
                return {}
            if "get-output" in path:
                return {"run_job_output": {"run_id": 2}}
            identifier = int(path.split("run_id=")[1])
            return {"state": {"life_cycle_state": "RUNNING"}, "tasks": [task(11, run_job_task={"job_id": 2})] if identifier == 1 else [task(21)]}
        with patch("databricks_jobs.time.monotonic", side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                execute_root(api, 90, timeout=1, record=lambda value: None)
        self.assertEqual(cancellations, [1, 2])


if __name__ == "__main__":
    unittest.main()
