import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from databricks_jobs import execute_root
from integration_auth import AzureOidcSession, sanitize
from integration_state import PhaseBudget, affected_tasks, job_fingerprints
from prepare_resume import prepare
from integration_migration import refresh_datasets


class IntegrationStateTests(unittest.TestCase):
    def test_selected_migration_refreshes_only_owned_datasets_in_dependency_order(self):
        manifest = {"datasets": [
            {"key": "raw.events", "pipeline": "ingest", "dependencies": []},
            {"key": "stage.events", "pipeline": "model", "dependencies": ["raw.events"]},
            {"key": "core.events", "pipeline": "model", "dependencies": ["stage.events"]},
        ]}
        deployment = {"pipelines": {"ingest": {"id": "i"}, "model": {"id": "m"}}}
        starts = []
        def api(method, path, body=None):
            if "/unity-catalog/tables/" in path:
                return {"pipeline_id": "i" if ".raw." in path else "m"}
            if method == "POST":
                starts.append((path, body))
                return {"update_id": "update"}
            if "/updates/" in path:
                return {"update": {"state": "COMPLETED"}}
            return {"state": "IDLE"}
        selected = ["core.events", "stage.events", "raw.events"]
        result = refresh_datasets(selected, manifest, deployment, "sample", api, lambda _: None)
        self.assertEqual(starts, [
            ("/api/2.0/pipelines/i/updates", {"full_refresh_selection": ["sample.raw.events"]}),
            ("/api/2.0/pipelines/m/updates", {"full_refresh_selection": ["sample.core.events", "sample.stage.events"]}),
        ])
        starts.clear()
        refresh_datasets(selected, manifest, deployment, "sample", api, lambda _: None, previous=result)
        self.assertEqual(starts, [])
        with self.assertRaisesRegex(ValueError, "outside"):
            refresh_datasets(["raw.foreign"], manifest, deployment, "sample", api, lambda _: None)
        self.assertEqual(starts, [])

    def test_artifact_resume_selects_new_result_not_an_embedded_old_resume_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "resume.json").write_text(json.dumps({"environment": "dev", "targets": ["old"]}))
            (root / "integration-dev-new.json").write_text(json.dumps({"environment": "dev", "targets": ["current"]}))
            prepare(root, root / "selected.json")
            self.assertEqual(json.loads((root / "selected.json").read_text())["targets"], ["current"])

    def test_bound_internal_table_is_filtered_before_legacy_metadata_calls(self):
        import run_integration_tests as runner
        pipeline = "e4cd2959-b079-4b56-b9c9-1edc6d340950"
        internal = "__" + pipeline.replace("-", "_") + "___history_customer"
        manifest = {"lifecycle": ["load"], "target": "databricks-lakeflow", "execution_plan": {"load": [{"job": "daily", "depends_on": []}]}, "datasets": [{"key": "stage.customer", "zone": "stage", "name": "customer", "kind": "materialized_view", "pipeline": "p", "helper": "__history_customer"}]}
        resources = {"jobs": {"daily": {"tasks": []}}, "pipelines": {"p": {"schema": "stage", "serverless": True}}}
        summary = {"jobs": {"daily": {"id": "7"}}, "pipelines": {"p": {"id": pipeline}}}
        environment = {"host": "https://workspace", "catalogs": {"databricks-lakeflow": "sample"}, "deployment_principal": "deploy", "run_principal": "run", "warehouse_id": "warehouse", "test_mode": "smoke"}
        args = SimpleNamespace(profile=None, deployment_profile=None, validation_profile=None, local_user=None, environment="prod", reset=False, resume_full_refresh=False, force_lock=False)
        def api(method, path, body=None, **kwargs):
            if path.endswith("/Me"):
                return {"applicationId": "deploy"}
            if "/jobs/get" in path:
                return {"settings": {"run_as": {"service_principal_name": "run"}}}
            if "/pipelines/" in path:
                return {"spec": {"serverless": True}, "run_as_user_name": "run"}
            raise AssertionError("Unexpected metadata call: " + path)
        def sql(statement, **kwargs):
            if statement.startswith("SHOW SCHEMAS"):
                return [["stage"]]
            if "SELECT table_schema,table_name" in statement:
                return [["stage", internal]]
            return []
        records = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bundle/generated").mkdir(parents=True)
            (root / "bundle/generated/manifest.json").write_text(json.dumps(manifest))
            config = {"run_as": {"service_principal_name": "run"}, "workspace": {"host": environment["host"], "file_path": "/files"}}
            def cli(arguments, **kwargs):
                return json.dumps({"applicationId": "deploy"} if arguments[-1].endswith("/Me") else config)
            with patch.object(runner, "ROOT", root), patch.object(runner, "TARGETS", {"databricks-lakeflow": {"bundle_path": "bundle"}}), patch.object(runner, "cli", side_effect=cli), patch.object(runner, "api", side_effect=api), patch.object(runner, "sql", side_effect=sql), patch.object(runner, "check_catalog"), patch.object(runner, "generated_resources", return_value=resources), patch.object(runner, "required_assets", return_value=[]), patch.object(runner, "bundle_summary", return_value=summary), patch.object(runner, "check_active"), patch.object(runner, "deploy_bundle", return_value=summary), patch.object(runner, "reusable_source_preflight", return_value={"sample_counts": {}, "checked_at": "now"}):
                self.assertEqual(runner.test_target("databricks-lakeflow", args, environment, records.append)["result"], "passed")
        self.assertTrue(any(value.get("deployment") == "passed" for value in records))

    def test_known_success_after_lost_receipt_never_starts_another_job(self):
        calls = []
        def api(method, path, body=None):
            calls.append((method, path, body))
            return {"job_id": 7, "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}, "tasks": [{"task_key": "load", "state": {"result_state": "SUCCESS"}}]}
        self.assertEqual(execute_root(api, 7, resume_run_id=19, record=lambda _: None, timeout=30)["result"], "passed")
        self.assertTrue(all(method == "GET" for method, _, _ in calls))

    def test_run_now_has_stable_idempotency_receipt(self):
        calls = []
        def api(method, path, body=None):
            calls.append((method, path, body))
            if path.endswith("run-now"):
                return {"run_id": 1}
            return {"state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}, "tasks": [{"task_key": "load", "state": {"result_state": "SUCCESS"}}]}
        execute_root(api, 7, record=lambda _: None, timeout=30, idempotency_token="stable-step")
        self.assertEqual(calls[0][2]["idempotency_token"], "stable-step")

    def test_partial_zone_run_uses_only_and_reports_excluded_tasks(self):
        calls = []
        def api(method, path, body=None):
            calls.append((method, path, body))
            if path.endswith("run-now"):
                return {"run_id": 1}
            return {"state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}, "tasks": [
                {"task_key": "changed", "state": {"result_state": "SUCCESS"}},
                {"task_key": "unchanged", "state": {"result_state": "EXCLUDED"}},
            ]}
        result = execute_root(api, 7, record=lambda _: None, timeout=30, only_tasks=["changed"], idempotency_token="zone-step")
        self.assertEqual(calls[0][2]["only"], ["changed"])
        self.assertEqual(result["result"], "passed")
        self.assertTrue(result["runs"][0]["tasks"][1]["excluded"])

    def test_safe_errors_and_artifacts_remove_credentials_recursively(self):
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
        value = {"error": "Config: actions_id_token_request_token=" + jwt, "nested": {"authorization": "Bearer private"}}
        safe = json.dumps(sanitize(value))
        self.assertNotIn(jwt, safe)
        self.assertNotIn("Bearer private", safe)
        self.assertIn("REDACTED", safe)

    def test_oidc_renewal_before_targets_and_at_thirty_minutes(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        response.read.return_value = b'{"value":"ephemeral-assertion"}'
        env = {"GITHUB_ACTIONS": "true", "DATABRICKS_AUTH_TYPE": "azure-cli", "ARM_CLIENT_ID": "client", "ARM_TENANT_ID": "tenant", "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example/?id=1", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token"}
        with patch.dict(os.environ, env), patch("integration_auth.urlopen", return_value=response), patch("integration_auth.subprocess.run", return_value=Mock(returncode=0)) as login, patch("integration_auth.time.monotonic", side_effect=[0, 100, 1801, 1801]):
            auth = AzureOidcSession()
            auth.ensure()
            auth.ensure()
            auth.ensure()
        self.assertEqual(login.call_count, 2)

    def test_phase_budget_is_shared_across_repetitions(self):
        budget = PhaseBudget({"load": 5390})
        with patch("integration_state.time.monotonic", side_effect=[0, 11]):
            with budget.measure("load"):
                pass
        with self.assertRaises(TimeoutError):
            budget.remaining("load")

    def test_changed_task_only_invalidates_its_dependents(self):
        definition = {"tasks": [{"task_key": "a"}, {"task_key": "b", "depends_on": [{"task_key": "a"}]}, {"task_key": "independent"}]}
        self.assertEqual(affected_tasks(definition, {"a": "new", "b": "same", "independent": "same"}, {"a": "old", "b": "same", "independent": "same"}), ["a", "b"])

    def test_ddl_evidence_is_not_invalidated_by_an_unrelated_notebook(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "generated/notebooks").mkdir(parents=True)
            ddl = root / "generated/notebooks/create.py"
            load = root / "generated/notebooks/load.py"
            ddl.write_text("create table")
            load.write_text("load table")
            resources = {"jobs": {key: {"tasks": [{"notebook_task": {"notebook_path": "${workspace.root_path}/${var.notebook_path}/" + key}}]} for key in ("create", "load")}}
            before = job_fingerprints(root, resources)
            load.write_text("changed load")
            after = job_fingerprints(root, resources)
            self.assertEqual(before["create"], after["create"])
            self.assertNotEqual(before["load"], after["load"])

    def test_job_task_order_does_not_invalidate_cross_platform_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            resources = {"jobs": {"daily": {"tasks": [{"task_key": "a"}, {"task_key": "b"}]}}}
            before = job_fingerprints(root, resources)
            resources["jobs"]["daily"]["tasks"].reverse()
            self.assertEqual(before, job_fingerprints(root, resources))
            (root / "generated/clusters").mkdir(parents=True)
            (root / "generated/clusters/cluster.yml").write_text("variables: {cluster: {default: changed}}")
            self.assertNotEqual(before, job_fingerprints(root, resources))
