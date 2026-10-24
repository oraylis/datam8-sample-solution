import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from databricks_jobs import execute_root, execution_tree, get_run, lifecycle_roots
from run_integration_tests import assert_no_rows, require_existing_deployment


def job(phase=None, children=()):
    return {
        "tags": {"datam8_phase": phase} if phase else {},
        "tasks": [{"run_job_task": {"job_id": f"${{resources.jobs.{child}.id}}"}} for child in children],
    }


def run(identifier, result="SUCCESS", tasks=()):
    return {"run_id": identifier, "state": {"life_cycle_state": "TERMINATED", "result_state": result}, "tasks": list(tasks)}


def task(identifier, result="SUCCESS", **kwargs):
    return {"run_id": identifier, "task_key": str(identifier), "state": {"result_state": result}, **kwargs}


class RootDiscoveryTests(unittest.TestCase):
    def test_arbitrary_names_and_additional_nested_load_groups(self):
        resources = {"jobs": {
            "initialize": job("create", ["ddl"]), "ddl": job(),
            "refresh": job("load", ["first", "second", "third"]),
            "first": job(), "second": job(), "third": job(),
        }}
        self.assertEqual(lifecycle_roots(resources), [("create", "initialize"), ("load", "refresh")])

    def test_unknown_root_is_not_silently_skipped(self):
        with self.assertRaisesRegex(ValueError, "datam8_phase"):
            lifecycle_roots({"jobs": {"a": job("create"), "b": job("load"), "extra": job()}})

    def test_cycle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Cycle"):
            lifecycle_roots({"jobs": {"a": job("create", ["b"]), "b": job("load", ["a"])}})

    def test_external_job_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "in this bundle"):
            lifecycle_roots({"jobs": {"a": {"tasks": [{"run_job_task": {"job_id": 77}}]}}})


class ExecutionTests(unittest.TestCase):
    def test_deployment_identity_matches_shared_service_principal(self):
        from run_integration_tests import require_deployment_identity
        configuration = {"run_as": {"service_principal_name": "test-sp"}}
        require_deployment_identity(configuration, {"userName": "test-sp"})
        with self.assertRaisesRegex(RuntimeError, "configured run_as"):
            require_deployment_identity(configuration, {"userName": "user@example.invalid"})

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
