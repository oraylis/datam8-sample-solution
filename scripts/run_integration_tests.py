"""Deploy and exercise existing Databricks bundles, then verify their catalog data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

from bundle_assets import required_assets
from solution_bindings import source_bindings
from validate_sample_data import validate_data, validate_append_fixture, business_fingerprints, table, identifier
from databricks_jobs import execute_root, execution_plan, generated_resources, get_run, execution_tree
from integration_auth import SESSION, sanitize
from integration_state import PhaseBudget, job_fingerprints, task_fingerprints, affected_tasks
from integration_migration import refresh_datasets
from contextlib import contextmanager
import uuid
import copy

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "Output/e2e-test-reports"
TARGETS = json.loads((ROOT / "tests/integration/targets.json").read_text(encoding="utf-8"))
ENVIRONMENTS = json.loads((ROOT / "tests/integration/environments.json").read_text(encoding="utf-8"))
SCHEMAS = ("raw", "stage", "core", "curated")
SOURCE_PREFLIGHT_TTL_SECONDS = 2 * 60 * 60
sys.path.insert(0, str(ROOT / "Generate/shared"))
from uc_sources import database_query


def generated_fingerprint(bundle: Path) -> str:
    """Hash generated paths and bytes so resume evidence is revision-specific."""
    root = bundle / "generated"
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def cli(args: list[str], *, cwd: Path, profile: str | None, timeout: int = 3600) -> str:
    if profile is None:
        SESSION.ensure()
    command = ["databricks"] + (["--profile", profile] if profile else []) + args
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=cli_environment(profile))
    if result.returncode:
        raise RuntimeError(sanitize(f"Databricks command failed: {' '.join(args)}\n{result.stderr}"))
    return result.stdout


def cli_environment(profile: str | None) -> dict[str, str] | None:
    """Select an isolated Azure CLI cache for profiles authenticated through azure-cli."""
    profile_dirs = os.getenv("DATABRICKS_PROFILE_AZURE_CONFIG_DIRS")
    if not profile_dirs:
        return None
    try:
        mapping = json.loads(profile_dirs)
    except json.JSONDecodeError as error:
        raise RuntimeError("DATABRICKS_PROFILE_AZURE_CONFIG_DIRS must be a JSON object") from error
    if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()):
        raise RuntimeError("DATABRICKS_PROFILE_AZURE_CONFIG_DIRS must map profile names to paths")
    config_dir = mapping.get(profile) if profile else None
    if not config_dir:
        return None
    environment = os.environ.copy()
    environment["AZURE_CONFIG_DIR"] = config_dir
    return environment


def sql(statement: str, *, warehouse: str, profile: str | None, timeout: int = 1800) -> list[list[str]]:
    payload = json.dumps({"warehouse_id": warehouse, "statement": statement, "wait_timeout": "50s"})
    # Large manifest-driven validation statements can exceed Windows' 32,767
    # character process command-line limit. The Databricks CLI accepts @file
    # request bodies, so keep the SQL out of argv on every platform.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as request_file:
        request_file.write(payload)
        request_path = Path(request_file.name)
    try:
        result = cli(["--output", "json", "api", "post", "/api/2.0/sql/statements", "--json", "@" + str(request_path)], cwd=ROOT, profile=profile, timeout=90)
    finally:
        request_path.unlink(missing_ok=True)
    response = json.loads(result)
    deadline = time.monotonic() + timeout
    while response["status"]["state"] in {"PENDING", "RUNNING"}:
        if time.monotonic() >= deadline:
            cli(["--output", "json", "api", "post", f"/api/2.0/sql/statements/{response['statement_id']}/cancel", "--json", "{}"], cwd=ROOT, profile=profile, timeout=60)
            raise TimeoutError(f"SQL statement timed out: {statement[:120]}")
        time.sleep(5)
        response = json.loads(cli(["--output", "json", "api", "get", f"/api/2.0/sql/statements/{response['statement_id']}"] , cwd=ROOT, profile=profile, timeout=60))
    if response["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {response['status']}")
    return response.get("result", {}).get("data_array", [])


def api(method: str, path: str, body: dict | None = None, *, profile: str | None):
    args = ["--output", "json", "api", method.lower(), path]
    if body is not None:
        args += ["--json", json.dumps(body)]
    attempts = 4 if method.upper() == "GET" else 1
    for attempt in range(attempts):
        try:
            response = cli(args, cwd=ROOT, profile=profile, timeout=120)
            break
        except RuntimeError as error:
            message = str(error).lower()
            transient = any(marker in message for marker in (
                "lookup ", "dial tcp", "wsarecv", "connection aborted", "connection reset",
                "temporarily unavailable", "temporary failure", "tls handshake timeout",
                "i/o timeout", "unexpected eof", "http 429", "http 502", "http 503", "http 504",
            ))
            if not transient or attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    return json.loads(response) if response.strip() else {}


def bundle_summary(bundle: Path, profile: str | None, environment: str = "dev") -> dict:
    return json.loads(cli(["--output", "json", "bundle", "summary", "--force-pull", "--target", environment], cwd=bundle, profile=profile, timeout=120))["resources"]


def require_existing_deployment(resources: dict, summary: dict) -> None:
    for kind, values in summary.items():
        unexpected = set(values) - set(resources.get(kind, {}))
        if unexpected:
            raise RuntimeError(f"Deployment state has unexpected {kind}: {sorted(unexpected)}; refusing resource deletion")
    for kind, values in resources.items():
        for key in values:
            if not summary.get(kind, {}).get(key, {}).get("id"):
                raise RuntimeError(f"Existing bundle resource is not bound: {kind}.{key}; refusing to create a second deployment")


def selected_deployment_args(
    name: str,
    resources: dict,
    before: dict,
    bundle: Path,
    profile: str | None,
    environment: str,
    *,
    full_refresh: bool,
    defer_owner_mismatch: bool = False,
    include_jobs_and_schemas: bool = True,
) -> list[str]:
    """Select changed resources without trying to rewrite unchanged pipeline ACLs."""
    if name != "databricks-lakeflow":
        return []
    if not all(
        before.get(kind, {}).get(key, {}).get("id")
        for kind, values in resources.items()
        for key in values
    ):
        return []
    plan_args = ["--output", "json", "bundle", "plan", "--target", environment]
    if full_refresh:
        plan_args += ["--var", "pipeline_full_refresh=true"]
    plan = json.loads(cli(plan_args, cwd=bundle, profile=profile, timeout=300))["plan"]
    selected = []
    if include_jobs_and_schemas:
        selected.extend(f"jobs.{key}" for key in resources.get("jobs", {}))
        selected.extend(f"schemas.{key}" for key in resources.get("schemas", {}))
    for key in resources.get("pipelines", {}):
        address = f"resources.pipelines.{key}"
        action = plan.get(address, {}).get("action", "skip")
        permission_action = plan.get(address + ".permissions", {}).get("action", "skip")
        if action == "skip":
            continue
        if permission_action != "skip":
            if defer_owner_mismatch:
                continue
            raise RuntimeError(
                f"Lakeflow pipeline {key} needs a spec update while its owner permissions also differ; "
                "refusing to transfer pipeline ownership during a local-user deployment"
            )
        selected.append(f"pipelines.{key}")
    return ["--select", ",".join(selected)] if selected else []


def lakeflow_pipeline_plan(bundle: Path, profile: str | None, environment: str, *, full_refresh: bool) -> dict:
    args = ["--output", "json", "bundle", "plan", "--target", environment]
    if full_refresh:
        args += ["--var", "pipeline_full_refresh=true"]
    plan = json.loads(cli(args, cwd=bundle, profile=profile, timeout=300))["plan"]
    result = {}
    prefix = "resources.pipelines."
    for address in plan:
        if not address.startswith(prefix) or address.endswith(".permissions"):
            continue
        key = address.removeprefix(prefix)
        result[key] = {
            "action": plan.get(address, {}).get("action", "skip"),
            "permission_action": plan.get(address + ".permissions", {}).get("action", "skip"),
        }
    return result


def deploy_bundle(
    name: str,
    resources: dict,
    before: dict,
    bundle: Path,
    operator_profile: str | None,
    deployment_profile: str | None,
    environment: str,
    *,
    full_refresh: bool,
    force_lock: bool = False,
    local_user: str | None = None,
) -> dict:
    """Deploy changed resources through the identity that already owns them."""
    if local_user and name == "databricks-lakeflow" and operator_profile != deployment_profile:
        operator_plan = lakeflow_pipeline_plan(bundle, operator_profile, environment, full_refresh=full_refresh)
        deployment_plan = lakeflow_pipeline_plan(bundle, deployment_profile, environment, full_refresh=full_refresh)
        pending = {
            key
            for plan in (operator_plan, deployment_plan)
            for key, actions in plan.items()
            if actions["action"] != "skip"
        }
        deployable = {
            key
            for plan in (operator_plan, deployment_plan)
            for key, actions in plan.items()
            if actions["action"] != "skip" and actions["permission_action"] == "skip"
        }
        unresolved = pending - deployable
        if unresolved:
            raise RuntimeError(
                "No supplied deployment identity owns changed Lakeflow pipelines: "
                + ", ".join(sorted(unresolved))
            )
        operator_selection = selected_deployment_args(
            name, resources, before, bundle, operator_profile, environment,
            full_refresh=full_refresh, defer_owner_mismatch=True,
        )
        deployment_selection = selected_deployment_args(
            name, resources, before, bundle, deployment_profile, environment,
            full_refresh=full_refresh, defer_owner_mismatch=True,
            include_jobs_and_schemas=False,
        )
        stages = [(operator_profile, operator_selection)]
        if deployment_selection:
            stages.append((deployment_profile, deployment_selection))
    else:
        profile = operator_profile if local_user else deployment_profile
        stages = [(
            profile,
            selected_deployment_args(
                name, resources, before, bundle, profile, environment,
                full_refresh=full_refresh,
            ),
        )]

    for profile, selected_args in stages:
        deploy_args = ["bundle", "deploy", "--target", environment, *selected_args]
        if force_lock:
            deploy_args.append("--force-lock")
        if full_refresh:
            deploy_args += ["--var", "pipeline_full_refresh=true"]
        cli(deploy_args, cwd=bundle, profile=profile, timeout=900)
    return bundle_summary(bundle, deployment_profile, environment)


def pipeline_event_log_objects(resources: dict, deployment: dict) -> set[str]:
    """Return only Lakeflow event-log tables belonging to already-bound pipelines."""
    deployed = deployment.get("pipelines", {})
    result = set()
    for key, pipeline in resources.get("pipelines", {}).items():
        pipeline_id = deployed.get(key, {}).get("id")
        schema = pipeline.get("schema") or pipeline.get("target")
        if not schema:
            objects = (pipeline.get("ingestion_definition") or {}).get("objects", [])
            schema = next((item.get("table", {}).get("destination_schema") for item in objects if item.get("table", {}).get("destination_schema")), None)
        if pipeline_id and schema:
            result.add(schema + ".event_log_" + str(pipeline_id).replace("-", "_"))
    return result


def stale_pipeline_event_log_objects(stale: set[tuple[str, str]], deployment: dict) -> set[str]:
    """Return raw event logs owned by the explicitly approved retired pipelines."""
    pipelines = deployment.get("pipelines", {})
    return {
        "raw.event_log_" + str(pipelines[key]["id"]).replace("-", "_")
        for kind, key in stale
        if kind == "pipelines" and pipelines.get(key, {}).get("id")
    }


def drop_stale_pipeline_event_logs(stale: set[tuple[str, str]], deployment: dict, actual: set[str], catalog: str, query) -> list[str]:
    """Drop only the event-log tables for pipelines retired by the selected-target reset."""
    owned = stale_pipeline_event_log_objects(stale, deployment)
    dropped = []
    for qualified_name in sorted(owned & actual):
        schema, name = qualified_name.split(".", 1)
        query(f"DROP TABLE IF EXISTS {identifier(catalog)}.{identifier(schema)}.{identifier(name)}")
        dropped.append(qualified_name)
    return dropped


def ingestion_destination_tables(resources: dict, catalog_name: str) -> set[str]:
    """Return the exact catalog-qualified tables managed by ingestion pipelines."""
    result = set()
    for pipeline in resources.get("pipelines", {}).values():
        definition = pipeline.get("ingestion_definition") or {}
        for item in definition.get("objects", []):
            table = item.get("table") or {}
            catalog = table.get("destination_catalog") or pipeline.get("catalog")
            if not catalog or catalog == "${var.catalog_name}":
                catalog = catalog_name
            schema = table.get("destination_schema")
            name = table.get("destination_table")
            if catalog and schema and name:
                result.add(f"{catalog}.{schema}.{name}")
    return result


def reset_orphaned_dataset_tables(catalog: str, manifest: dict, deployment: dict, query, call) -> list[str]:
    """Drop only source-ingestion tables whose former pipeline has been deleted."""
    destinations = {}
    for dataset in manifest.get("datasets", []):
        zone = dataset.get("zone")
        # Lakeflow Connect owns external raw destinations. The downstream
        # streaming tables and materialized views belong to their existing
        # model pipelines and must never be treated as ingestion orphans.
        if zone != "raw" or not dataset.get("external"):
            continue
        destinations[f"{catalog}.{zone}.{dataset['name']}"] = zone
    active_pipeline_ids = {
        str(value["id"])
        for value in deployment.get("pipelines", {}).values()
        if value.get("id")
    }
    pipeline_exists = {}
    dropped = []
    zone_order = {zone: index for index, zone in enumerate(SCHEMAS)}
    ordered_names = sorted(destinations, key=lambda name: (-zone_order[destinations[name]], name))

    def get_table_metadata(full_name):
        try:
            return call("GET", "/api/2.1/unity-catalog/tables/" + quote(full_name, safe="."))
        except RuntimeError as error:
            message = str(error).lower()
            if "http 404" in message or "not found" in message or "does not exist" in message:
                return None
            raise

    with ThreadPoolExecutor(max_workers=8) as pool:
        metadata_by_name = dict(zip(ordered_names, pool.map(get_table_metadata, ordered_names)))

    for full_name in ordered_names:
        metadata = metadata_by_name[full_name]
        if metadata is None:
            continue
        old_pipeline_id = metadata.get("pipeline_id") or metadata.get("properties", {}).get("pipelines.pipelineId")
        if not old_pipeline_id:
            continue
        if old_pipeline_id not in pipeline_exists:
            try:
                call("GET", "/api/2.0/pipelines/" + str(old_pipeline_id))
            except RuntimeError as error:
                message = str(error).lower()
                if "http 404" not in message and "not found" not in message:
                    raise
                pipeline_exists[old_pipeline_id] = False
            else:
                pipeline_exists[old_pipeline_id] = True
        if pipeline_exists[old_pipeline_id]:
            if old_pipeline_id in active_pipeline_ids:
                continue
            raise RuntimeError(
                f"Expected ingestion table {full_name} is owned by another existing pipeline "
                f"{old_pipeline_id}; refusing to delete or transfer it"
            )
        table_type = metadata.get("table_type")
        if table_type not in {"MATERIALIZED_VIEW", "STREAMING_TABLE"}:
            raise RuntimeError(
                f"Orphaned ingestion table {full_name} has unexpected type "
                f"{table_type}; refusing to delete it"
            )
        zone = destinations[full_name]
        drop = "DROP MATERIALIZED VIEW" if table_type == "MATERIALIZED_VIEW" else "DROP TABLE"
        query(f"{drop} {identifier(catalog)}.{identifier(zone)}.{identifier(metadata['name'])}")
        dropped.append(full_name)
    return dropped


def retire_legacy_ingestion_pipelines(stale: set[tuple[str, str]], deployment: dict, catalog: str, manifest: dict, call) -> list[str]:
    """Retire only the four prior connection-wide ingestions before job-scoped replacement."""
    expected = {
        f"{item['zone']}.{item['name']}"
        for item in manifest.get("datasets", [])
        if item.get("zone") == "raw" and item.get("external")
    }
    retired = []
    for kind, key in sorted(stale):
        if kind != "pipelines":
            continue
        pipeline_id = deployment.get("pipelines", {}).get(key, {}).get("id")
        if not pipeline_id:
            raise RuntimeError(f"Legacy pipeline {key} has no bound ID; refusing retirement")
        try:
            pipeline = call("GET", "/api/2.0/pipelines/" + str(pipeline_id))
        except RuntimeError as error:
            message = str(error).lower()
            if "http 404" in message or "not found" in message:
                retired.append(key)
                continue
            raise
        if pipeline.get("state") not in {"IDLE", "FAILED"}:
            raise RuntimeError(f"Legacy pipeline {key} is active; refusing retirement")
        definition = (pipeline.get("spec") or {}).get("ingestion_definition") or {}
        objects = definition.get("objects") or []
        destinations = set()
        for item in objects:
            table = item.get("table") or {}
            destination_catalog = table.get("destination_catalog")
            destination = f"{table.get('destination_schema')}.{table.get('destination_table')}"
            if destination_catalog and destination_catalog != catalog:
                raise RuntimeError(f"Legacy pipeline {key} targets another catalog; refusing retirement")
            if destination not in expected:
                raise RuntimeError(f"Legacy pipeline {key} owns an unexpected table {destination}; refusing retirement")
            destinations.add(destination)
        if not destinations:
            raise RuntimeError(f"Legacy pipeline {key} has no verifiable managed destinations; refusing retirement")
        call("DELETE", "/api/2.0/pipelines/" + str(pipeline_id))
        deadline = time.monotonic() + 120
        while True:
            try:
                call("GET", "/api/2.0/pipelines/" + str(pipeline_id))
            except RuntimeError as error:
                message = str(error).lower()
                if "http 404" in message or "not found" in message:
                    break
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out retiring legacy pipeline {key}")
            time.sleep(2)
        retired.append(key)
    return retired


def pipeline_materialization_objects(resources: dict, deployment: dict, manifest: dict) -> set[str]:
    """Return only engine materialization tables tied to bound MV datasets."""
    deployed = deployment.get("pipelines", {})
    result = set()
    for key, pipeline in resources.get("pipelines", {}).items():
        pipeline_id = deployed.get(key, {}).get("id")
        schema = pipeline.get("schema") or pipeline.get("target")
        if not pipeline_id or not schema:
            continue
        for dataset in manifest.get("datasets", []):
            if dataset.get("pipeline") != key or dataset.get("kind") != "materialized_view":
                continue
            result.add(
                schema
                + ".__materialization_mat_"
                + str(pipeline_id).replace("-", "_")
                + "_"
                + dataset["name"]
                + "_1"
            )
            if dataset.get("helper"):
                helper = dataset["helper"] if "." in dataset["helper"] else schema + "." + dataset["helper"]
                result.add(
                    helper.split(".", 1)[0]
                    + ".__materialization_mat_"
                    + str(pipeline_id).replace("-", "_")
                    + "_"
                    + helper.split(".", 1)[1]
                    + "_1"
                )
    return result


def is_lakeflow_internal_object(qualified_name: str, manifest: dict) -> bool:
    """Recognize UUID-scoped staging/materialization tables for manifest datasets."""
    schema, separator, name = qualified_name.partition(".")
    if not separator:
        return False
    uuid = r"[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}"
    for dataset in manifest.get("datasets", []):
        if dataset.get("zone") != schema or not dataset.get("pipeline"):
            continue
        names = {dataset["name"]}
        helper = dataset.get("helper")
        if helper:
            helper_schema, separator, helper_name = helper.partition(".")
            if not separator:
                helper_schema, helper_name = schema, helper
            if helper_schema == schema:
                names.add(helper_name)
        for object_name in names:
            if object_name.startswith("__history_") and re.fullmatch(r"__" + uuid + "_" + re.escape(object_name), name):
                return True
            if re.fullmatch(r"__staging_" + uuid + "_" + re.escape(object_name), name):
                return True
            if re.fullmatch(r"__materialization_mat_" + uuid + "_" + re.escape(object_name) + r"_1", name):
                return True
    return False


def classify_owned_legacy_objects(actual: set[str], expected: set[str], target: str, environment: dict, deployment: dict, call) -> tuple[set[str], set[str]]:
    """Recognize stale model names only when Unity Catalog proves target ownership."""
    candidates = sorted(actual - expected)
    if not candidates:
        return set(), set()
    pipeline_ids = {
        str(pipeline["id"])
        for pipeline in deployment.get("pipelines", {}).values()
        if pipeline.get("id")
    }

    def inspect(name):
        try:
            metadata = call("GET", "/api/2.1/unity-catalog/tables/" + quote(environment["catalogs"][target] + "." + name, safe="."))
        except RuntimeError as error:
            message = str(error).lower()
            if "http 404" in message or "not found" in message or "does not exist" in message:
                return name, False
            raise
        if target == "databricks":
            return name, metadata.get("owner") == environment["run_principal"]
        pipeline_id = metadata.get("pipeline_id") or metadata.get("properties", {}).get("pipelines.pipelineId")
        return name, str(pipeline_id) in pipeline_ids

    with ThreadPoolExecutor(max_workers=8) as pool:
        ownership = dict(pool.map(inspect, candidates))
    owned = {name for name, matches in ownership.items() if matches}
    foreign = set(candidates) - owned
    return owned, foreign


def require_deployment_identity(configuration: dict, identity: dict, environment: dict, *, local_user: str | None = None) -> None:
    if local_user:
        actual_user = identity.get("userName")
        if not actual_user or actual_user.casefold() != local_user.casefold():
            raise RuntimeError(f"Authenticate locally as the requested user {local_user}")
    elif (identity.get("applicationId") or identity.get("userName")) != environment["deployment_principal"]:
        raise RuntimeError("Authenticate as the selected environment's deployment service principal")
    if configuration.get("run_as", {}).get("service_principal_name") != environment["run_principal"]:
        raise RuntimeError("Bundle run_as differs from the selected environment's execution service principal")
    if configuration.get("workspace", {}).get("host", "").rstrip("/") != environment["host"]:
        raise RuntimeError("Bundle points at another workspace")


def require_owned_classic_reset(actual, catalog, owner, call):
    def inspect(key):
        metadata = call("GET", "/api/2.1/unity-catalog/tables/" + quote(catalog + "." + key, safe="."))
        if metadata.get("owner") != owner:
            raise RuntimeError("Explicit reset refused: table is not owned by the selected run identity: " + key)
    if actual:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(inspect, sorted(actual)))


def require_local_user_identity(identity: dict, local_user: str | None) -> None:
    if local_user:
        actual_user = identity.get("userName")
        if not actual_user or actual_user.casefold() != local_user.casefold():
            raise RuntimeError(f"Authenticate locally as the requested user {local_user}")


def assert_no_rows(statement: str, *, warehouse: str, profile: str | None) -> None:
    rows = sql(statement, warehouse=warehouse, profile=profile)
    if rows:
        raise RuntimeError(f"Data integrity check failed: {statement}")


def source_preflight(manifest, environment, query, call, *, smoke):
    counts, tested = {}, set()
    database_checks = []
    for dataset in manifest["datasets"]:
        external = dataset.get("external")
        if not external:
            continue
        plugin = external["plugin"]
        if smoke and plugin in tested and plugin != "http_api":
            continue
        connection = environment["connection_prefix"] + external["connection_suffix"]
        if plugin == "http_api":
            path = "/api/2.0/unity-catalog/connections/" + connection + "/proxy/" + external["location"].lstrip("/")
            response = call("GET", path + "?page_size=1")
            if not response.get("items") or not isinstance(response.get("total"), int):
                raise RuntimeError("Required API endpoint returned no valid source snapshot")
            counts[dataset["key"]] = response["total"]
            if response.get("next_cursor"):
                following = call("GET", path + "?" + urlencode({"page_size": 1, "cursor": response["next_cursor"]}))
                if not following.get("items"):
                    raise RuntimeError("UC HTTP pagination smoke check failed")
        else:
            sql_text, predicate = database_query(connection, external["location"], external["service_name"] if plugin == "oracle" else external["database"], plugin)
            if smoke:
                statement = "SELECT '" + dataset["key"].replace("'", "''") + "' AS source_key, 1 AS row_count FROM (SELECT * FROM (" + sql_text + ") source"
                statement += " WHERE " + predicate.replace("[", "`").replace("]", "`") if predicate else ""
                statement += " LIMIT 1) source"
            else:
                statement = "SELECT '" + dataset["key"].replace("'", "''") + "' AS source_key, COUNT(*) AS row_count FROM (" + sql_text + ") source"
                statement += " WHERE " + predicate.replace("[", "`").replace("]", "`") if predicate else ""
            database_checks.append(statement)
        tested.add(plugin)
    if database_checks:
        for key, count in query(" UNION ALL ".join(database_checks)):
            if not count:
                raise RuntimeError("Required source returned no rows: " + key)
            if not smoke:
                counts[key] = int(count)
    if tested != {"sqlserver", "oracle", "mysql", "postgresql", "http_api"}:
        raise RuntimeError("Preflight did not cover all five required source families")
    return counts


def source_preflight_signature(manifest, environment):
    inventory = sorted([
        {
            "plugin": dataset["external"]["plugin"],
            "connection_suffix": dataset["external"]["connection_suffix"],
            "location": dataset["external"]["location"],
            "database": dataset["external"].get("database"),
            "service_name": dataset["external"].get("service_name"),
        }
        for dataset in manifest.get("datasets", [])
        if dataset.get("external")
    ], key=lambda item: json.dumps(item, sort_keys=True))
    binding = {
        "host": environment["host"],
        "connection_prefix": environment["connection_prefix"],
        "inventory": inventory,
    }
    encoded = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def reusable_source_preflight(report_dir: Path, environment_name: str, manifest: dict, environment: dict):
    path = report_dir / f"source-preflight-{environment_name}.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        checked_at = datetime.fromisoformat(result["checked_at"])
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        if (
            result.get("signature") == source_preflight_signature(manifest, environment)
            and 0 <= age < SOURCE_PREFLIGHT_TTL_SECONDS
        ):
            return result
    except (OSError, KeyError, ValueError, TypeError):
        pass
    return None


def save_source_preflight(report_dir: Path, environment_name: str, manifest: dict, environment: dict, sample_counts: dict):
    path = report_dir / f"source-preflight-{environment_name}.json"
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "signature": source_preflight_signature(manifest, environment),
        "sample_counts": sample_counts,
    }
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def check_catalog(call, catalog, environment):
    catalog_definition = call("GET", "/api/2.1/unity-catalog/catalogs/" + catalog)
    if catalog_definition.get("isolation_mode") != "ISOLATED":
        raise RuntimeError("Sample catalog must be ISOLATED")
    bindings = call("GET", "/api/2.1/unity-catalog/bindings/catalog/" + catalog).get("bindings", [])
    if {int(item["workspace_id"]) for item in bindings} != {environment["workspace_id"]}:
        raise RuntimeError("Catalog is not bound exclusively to its intended workspace")
    return catalog_definition


def validate_delta_cursors(manifest, environment, catalog, query):
    statements = []
    for dataset in manifest["datasets"]:
        external = dataset.get("external", {})
        if external.get("extract_mode") != "delta":
            continue
        cursor = external.get("cursor_column")
        target_cursor = external.get("target_cursor_column", cursor)
        if not cursor or not target_cursor:
            raise ValueError("Delta validation requires manifest cursor metadata: " + dataset["key"])
        dtype = next(column["type"] for column in dataset["columns"] if column["name"].casefold() == target_cursor.casefold())
        connection = environment["connection_prefix"] + external["connection_suffix"]
        source, predicate = database_query(connection, external["location"], external["service_name"] if external["plugin"] == "oracle" else external["database"], external["plugin"])
        where = " WHERE " + predicate if predicate else ""
        raw_max = "(SELECT MAX(" + identifier(target_cursor) + ") FROM " + table(catalog, dataset["key"]) + ")"
        source_max = "(SELECT MAX(CAST(" + identifier(cursor) + " AS " + dtype + ")) FROM (" + source + ") source" + where + ")"
        statements.append("SELECT '" + dataset["key"] + "' AS dataset, " + raw_max + " <=> " + source_max + " AS cursor_complete")
    failures = [key for key, complete in query(" UNION ALL ".join(statements)) if str(complete).lower() != "true"] if statements else []
    if failures:
        raise RuntimeError("Source cursor advanced beyond the extracted delta or extraction is incomplete: " + ", ".join(failures))
    return len(statements)


def check_active(call, summary, bundle: Path, profile: str | None, *, allowed_missing_pipeline_ids=(), resume_run_ids=(), resume_pipeline_ids=()):
    sample_job_ids = {int(job["id"]) for job in summary.get("jobs", {}).values() if job.get("id")}
    page = None
    while True:
        query = {"active_only": "true", "limit": "26"}
        if page:
            query["page_token"] = page
        response = call("GET", "/api/2.2/jobs/runs/list?" + urlencode(query))
        if any(int(run.get("job_id", -1)) in sample_job_ids and int(run.get("run_id", -1)) not in resume_run_ids for run in response.get("runs", [])):
            raise RuntimeError("An existing sample job is running; refusing concurrent integration")
        page = response.get("next_page_token")
        if not page:
            break
    pipeline_ids = [
        pipeline["id"]
        for pipeline in summary.get("pipelines", {}).values()
        if pipeline.get("id")
    ]
    if not pipeline_ids:
        return
    # Use the list endpoint once instead of spawning a CLI process for every
    # pipeline. This check runs before any writes and should stay scoped to the
    # exact pipelines in this bundle.
    listed = json.loads(cli(["--output", "json", "pipelines", "list-pipelines"], cwd=bundle, profile=profile, timeout=120))
    state_by_id = {str(item["pipeline_id"]): item.get("state") for item in listed}
    missing = set(pipeline_ids) - set(state_by_id)
    if missing:
        def get_state(pipeline_id):
            try:
                return pipeline_id, call("GET", f"/api/2.0/pipelines/{pipeline_id}").get("state")
            except RuntimeError as error:
                message = str(error).lower()
                if pipeline_id in allowed_missing_pipeline_ids and ("http 404" in message or "not found" in message):
                    return pipeline_id, "DELETED"
                raise
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as pool:
            states = list(pool.map(get_state, missing))
        state_by_id.update({str(pipeline_id): state for pipeline_id, state in states})
    allowed_missing = {str(pipeline_id) for pipeline_id in allowed_missing_pipeline_ids}
    if any(state_by_id.get(str(pipeline_id)) not in {"IDLE", "FAILED"} and str(pipeline_id) not in resume_pipeline_ids and not (str(pipeline_id) in allowed_missing and state_by_id.get(str(pipeline_id)) == "DELETED") for pipeline_id in pipeline_ids):
        raise RuntimeError("An existing sample pipeline is active")


@contextmanager
def reported_step(record, name):
    state = {"started_at": datetime.now(timezone.utc).isoformat(), "result": "running"}
    record({"steps": {name: state}})
    print("START " + name, flush=True)
    try:
        yield
        state["result"] = "passed"
    except Exception as error:
        state.update(result="failed", error=sanitize(str(error)))
        raise
    finally:
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        record({"steps": {name: state}})
        print(state["result"].upper() + " " + name, flush=True)


def test_target(name, args, environment, record, resume_record=None):
    SESSION.ensure(force=True)
    bundle = ROOT / TARGETS[name]["bundle_path"]
    catalog = environment["catalogs"][name]
    deployment_profile = args.deployment_profile or args.profile
    validation_profile = args.validation_profile or args.profile
    query = lambda statement: sql(statement, warehouse=environment["warehouse_id"], profile=args.profile)
    call = lambda method, path, body=None: api(method, path, body, profile=args.profile)
    config = json.loads(cli(["--output", "json", "bundle", "validate", "--target", args.environment], cwd=bundle, profile=deployment_profile, timeout=300))
    deployment_identity = json.loads(cli(["--output", "json", "api", "get", "/api/2.0/preview/scim/v2/Me"], cwd=bundle, profile=deployment_profile, timeout=120))
    require_deployment_identity(config, deployment_identity, environment)
    runtime_identity = call("GET", "/api/2.0/preview/scim/v2/Me")
    require_local_user_identity(runtime_identity, args.local_user)
    validation_identity = runtime_identity
    if validation_profile != args.profile:
        validation_identity = api("GET", "/api/2.0/preview/scim/v2/Me", profile=validation_profile)
        actual_validator = validation_identity.get("applicationId") or validation_identity.get("userName")
        if actual_validator != environment["run_principal"]:
            raise RuntimeError("Validation profile must authenticate as the selected environment's run service principal")
    check_catalog(call, catalog, environment)
    # Both runners use the same model-derived source inventory. Nothing is read
    # from a second solution or generated by an ad-hoc cloud test job.
    manifest = json.loads((bundle / "generated/manifest.json").read_text())
    asset_fingerprint = generated_fingerprint(bundle)
    record({"asset_fingerprint": asset_fingerprint})
    source_manifest = manifest
    # Check source reachability once per unchanged environment/target inventory;
    # reuse that pass for two hours while the bounded demo environment is up.
    # Resume reports can be older than the source-preflight TTL. Reuse only the
    # signed cache file, which validates both freshness and the current bindings.
    with reported_step(record, "source_preflight"):
        source_cache = reusable_source_preflight(REPORT_DIR, args.environment, source_manifest, environment)
        if source_cache:
            source_counts = source_cache["sample_counts"]
            source_preflight_status = "passed_cached"
        else:
            source_counts = source_preflight(source_manifest, environment, query, call, smoke=True)
            source_cache = save_source_preflight(REPORT_DIR, args.environment, source_manifest, environment, source_counts)
            source_preflight_status = "passed"
        record({"source_preflight": source_preflight_status, "source_preflight_at": source_cache["checked_at"], "source_counts_before": source_counts, "deployment_principal": deployment_identity.get("applicationId") or deployment_identity.get("userName"), "operator_principal": runtime_identity.get("userName") or runtime_identity.get("applicationId"), "validation_principal": validation_identity.get("userName") or validation_identity.get("applicationId"), "run_principal": environment["run_principal"]})
    resources = generated_resources(bundle)
    fingerprints = job_fingerprints(bundle, resources)
    old_fingerprints = (resume_record or {}).get("job_fingerprints", {})
    if not old_fingerprints and resume_record and resume_record.get("asset_fingerprint") == asset_fingerprint:
        old_fingerprints = fingerprints
    record({"job_fingerprints": fingerprints})
    record({"fingerprint_version": 2})
    task_hashes = task_fingerprints(bundle, resources)
    record({"task_fingerprints": task_hashes})
    evidence = {}
    for section in ("runs", "repeat_runs"):
        evidence[section] = copy.deepcopy((resume_record or {}).get(section, {}))
        for key, receipt in evidence[section].items():
            receipt.setdefault("asset_fingerprint", old_fingerprints.get(key, "unverified"))
            receipt.setdefault("task_fingerprints", (resume_record or {}).get("task_fingerprints", {}))
        record({section: evidence[section]})
    assets = required_assets(bundle)
    roots = execution_plan(resources, manifest, required_phases=manifest["lifecycle"])
    with reported_step(record, "inventory_and_reset"):
        before = bundle_summary(bundle, deployment_profile, args.environment)
        expected_stale = {("jobs", "load_all_tables")} if name == "databricks-lakeflow" else set()
        if name == "databricks-lakeflow":
            expected_stale.update(("pipelines", key) for key in (
                "ingest_mysql", "ingest_oracle", "ingest_postgresql", "ingest_sqlserver",
            ))
        if name == "databricks":
            obsolete_create_keys = {
                key for key in before.get("jobs", {})
                if key not in resources.get("jobs", {})
                and re.fullmatch(r"Create_(?:raw|stage|core|curated)_.+", key)
            }
            expected_stale.update(("jobs", key) for key in obsolete_create_keys)
            obsolete_layer_load_keys = {
                key for key in before.get("jobs", {})
                if key not in resources.get("jobs", {})
                and re.fullmatch(r"Load_.+_(?:raw|stage|core|curated)_\d+", key, re.IGNORECASE)
            }
            expected_stale.update(("jobs", key) for key in obsolete_layer_load_keys)
        stale_found = set()
        for kind, values in before.items():
            unexpected = set(values) - set(resources.get(kind, {}))
            allowed = {key for stale_kind, key in expected_stale if stale_kind == kind}
            if unexpected - allowed:
                raise RuntimeError("Unexpected resource in bundle state; refusing replacement")
            stale_found.update((kind, key) for key in unexpected)
        if stale_found != expected_stale.intersection({(kind, key) for kind, values in before.items() for key in values}):
            raise RuntimeError("Unexpected stale bundle resources; refusing deletion")
        if any(not before.get(kind, {}).get(key, {}).get("id") for kind, key in stale_found):
            raise RuntimeError("An obsolete bundle resource is not bound to this deployment")
        previously_bound = [
            (kind, key)
            for kind, values in resources.items()
            for key in values
            if before.get(kind, {}).get(key, {}).get("id")
        ]
        selected_stale_pipeline_ids = {
            str(before.get("pipelines", {}).get(key, {}).get("id"))
            for kind, key in expected_stale
            if kind == "pipelines" and before.get("pipelines", {}).get(key, {}).get("id")
        }
        known_runs = {int(run["root_run_id"]) for section in ("runs", "repeat_runs") for run in (resume_record or {}).get(section, {}).values() if run.get("root_run_id")}
        for run in (resume_record or {}).get("runs", {}).values():
            known_runs.update(int(item["root_run_id"]) for item in run.get("supplemental_runs", {}).values() if item.get("root_run_id"))
            known_runs.update(int(item["receipt"]["root_run_id"]) for item in run.get("pending_create_repairs", {}).values() if item.get("receipt", {}).get("root_run_id"))
        known_pipeline_ids = set()
        for run_identifier in list(known_runs):
            remote = get_run(call, run_identifier)
            if remote.get("state", {}).get("life_cycle_state") not in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                known_pipeline_ids.update(task["pipeline_task"]["pipeline_id"] for task in remote.get("tasks", []) if task.get("pipeline_task"))
            for old in (resume_record or {}).get("runs", {}).values():
                known_runs.update(int(item["run_id"]) for item in old.get("runs", []))
        check_active(call, before, bundle, args.profile, allowed_missing_pipeline_ids=selected_stale_pipeline_ids, resume_run_ids=known_runs, resume_pipeline_ids=known_pipeline_ids)
        existing = {row[0] for row in query(f"SHOW SCHEMAS IN {identifier(catalog)}")}
        if existing - set(SCHEMAS) - {"default", "information_schema"}:
            raise RuntimeError("Foreign schemas found in sample catalog")
        expected = {item["key"] for item in manifest["datasets"]}
        expected.update(item["helper"] if "." in item["helper"] else item["zone"] + "." + item["helper"] for item in manifest["datasets"] if item.get("helper"))
        expected.update(pipeline_event_log_objects(resources, before))
        expected.update(stale_pipeline_event_log_objects(expected_stale, before))
        expected.update(pipeline_materialization_objects(resources, before, manifest))
        actual = {schema + "." + name for schema, name in query(f"SELECT table_schema,table_name FROM {identifier(catalog)}.information_schema.tables WHERE table_schema IN ('raw','stage','core','curated')")}
        internal = {item for item in actual if is_lakeflow_internal_object(item, manifest) and any(
            str(pipeline.get("id", "")).replace("-", "_") in item
            for pipeline in before.get("pipelines", {}).values() if pipeline.get("id")
        )} if name == "databricks-lakeflow" else set()
        owned_legacy, unowned = classify_owned_legacy_objects(actual - internal, expected, name, environment, before, call)
        foreign = unowned
        if foreign:
            raise RuntimeError("Objects in the selected test catalog cannot be proven to belong to this target: " + str(sorted(foreign)))
        if owned_legacy:
            record({"retained_owned_legacy_objects": sorted(owned_legacy)})
        if not previously_bound and actual:
            raise RuntimeError("Unbound initial deployment must use an empty sample catalog")
        for object_kind, schema_column in (("routines", "routine_schema"), ("volumes", "volume_schema")):
            if query(f"SELECT 1 FROM {identifier(catalog)}.information_schema.{object_kind} WHERE {schema_column} IN ('raw','stage','core','curated') LIMIT 1"):
                raise RuntimeError("Foreign routines or volumes found in sample catalog")
        full = environment["test_mode"] == "full"
        native_reset = name == "databricks-lakeflow" and full and bool(actual) and args.reset
        resume_full_refresh = bool(
            (args.resume_full_refresh or resume_record and "reset_orphaned_dataset_tables" in resume_record)
            and not any(
                run.get("phase") == "load" and run.get("result") == "passed"
                for run in resume_record.get("runs", {}).values()
            )
        )
        needs_disable_full_refresh = native_reset or resume_full_refresh
        if name == "databricks-lakeflow" and not full and any(kind == "pipelines" for kind, _ in stale_found):
            raise RuntimeError("Legacy connection-wide ingestion pipelines require the controlled Dev reset before job-scoped deployment")
        if native_reset:
            retired = retire_legacy_ingestion_pipelines(stale_found, before, catalog, manifest, call)
            record({"retired_legacy_ingestion_pipelines": retired})
            event_logs = drop_stale_pipeline_event_logs(stale_found, before, actual, catalog, query)
            record({"dropped_retired_pipeline_event_logs": event_logs})
            orphaned = reset_orphaned_dataset_tables(catalog, manifest, before, query, call)
            record({"reset_orphaned_dataset_tables": orphaned})
        if full and name == "databricks" and args.reset:
            require_owned_classic_reset(actual, catalog, environment["run_principal"], call)
            for schema in reversed(SCHEMAS):
                if schema in existing:
                    query(f"DROP SCHEMA {identifier(catalog)}.{identifier(schema)} CASCADE")
    with reported_step(record, "deployment_and_assets"):
        after = deploy_bundle(
            name,
            resources,
            before,
            bundle,
            args.profile,
            deployment_profile,
            args.environment,
            full_refresh=native_reset or resume_full_refresh,
            force_lock=args.force_lock,
            local_user=args.local_user,
        )
        require_existing_deployment(resources, after)
        for kind, values in before.items():
            for key, value in values.items():
                if (kind, key) in stale_found:
                    continue
                if value.get("id") and after.get(kind, {}).get(key, {}).get("id") != value["id"]:
                    raise RuntimeError(f"Deployment replaced existing sample resource {kind}.{key}")
        for key, job in after.get("jobs", {}).items():
            settings = call("GET", "/api/2.2/jobs/get?job_id=" + str(job["id"]))["settings"]
            if settings.get("run_as", {}).get("service_principal_name") != environment["run_principal"]:
                raise RuntimeError("Deployed job has unexpected run_as: " + key)
            if name == "databricks":
                expected_job = resources.get("jobs", {}).get(key, {})
                declared_clusters = {
                    cluster.get("job_cluster_key")
                    for cluster in expected_job.get("job_clusters", [])
                }
                deployed_clusters = {
                    cluster.get("job_cluster_key")
                    for cluster in settings.get("job_clusters", [])
                }
                if declared_clusters != deployed_clusters:
                    raise RuntimeError("Deployed job clusters differ from the bundle definition: " + key)
                for task in settings.get("tasks", []):
                    if not task.get("notebook_task"):
                        continue
                    cluster_key = task.get("job_cluster_key")
                    if not cluster_key or cluster_key not in deployed_clusters:
                        raise RuntimeError("Notebook task is not assigned to its modeled job cluster: " + key)
                    if task.get("new_cluster") or task.get("existing_cluster_id"):
                        raise RuntimeError("Notebook task bypasses the job-level cluster property: " + key)
        for pipeline_key, pipeline in after.get("pipelines", {}).items():
            state = call("GET", "/api/2.0/pipelines/" + pipeline["id"])
            expected_pipeline = resources.get("pipelines", {}).get(pipeline_key, {})
            expected_clusters = expected_pipeline.get("clusters", [])
            actual_spec = state.get("spec", {})
            if expected_clusters:
                actual_clusters = {
                    cluster.get("label"): cluster
                    for cluster in actual_spec.get("clusters", [])
                }
                for expected_cluster in expected_clusters:
                    actual_cluster = actual_clusters.get(expected_cluster.get("label"))
                    if not actual_cluster or any(
                        actual_cluster.get(field) != expected_cluster.get(field)
                        for field in ("node_type_id", "num_workers", "driver_node_type_id", "policy_id")
                        if field in expected_cluster
                    ):
                        raise RuntimeError("Deployed pipeline compute differs from its model job cluster: " + pipeline_key)
                if actual_spec.get("serverless"):
                    raise RuntimeError("Pipeline has serverless enabled despite a classic model cluster: " + pipeline_key)
            elif expected_pipeline.get("serverless") and not actual_spec.get("serverless"):
                raise RuntimeError("Pipeline should use serverless compute: " + pipeline_key)
            if state.get("run_as_user_name") != environment["run_principal"]:
                raise RuntimeError("Deployed pipeline has an unexpected execution identity")
        def verify_asset(asset):
            remote = config["workspace"]["file_path"].rstrip("/") + "/" + asset
            if remote.endswith(".py") and (bundle / asset).read_text(encoding="utf-8").startswith("# Databricks notebook source"):
                remote = remote[:-3]
            call("GET", "/api/2.0/workspace/get-status?" + urlencode({"path": remote}))

        # Workspace status is a read-only check for each synced file. Bound
        # concurrency keeps the verification quick without flooding the API.
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(verify_asset, assets))
        record({"deployment": "passed", "resources": after, "asset_count": len(assets), "roots": roots})
    if not full:
        return {"result": "passed", "test_mode": "deployment-and-source-smoke", "full_data_acceptance": False}
    runs = evidence["runs"]
    repeat_runs = evidence["repeat_runs"]
    budget = PhaseBudget()
    if args.refresh_dataset:
        with reported_step(record, "selected_dataset_migration"), budget.measure("load"):
            refresh_datasets(args.refresh_dataset, manifest, after, catalog, call, record,
                             previous=(resume_record or {}).get("dataset_refreshes"), timeout=budget.remaining("load"))
    changed_jobs = {key for _, key in roots if runs.get(key, {}).get("asset_fingerprint") != fingerprints[key]}
    dependencies = {entry["job"]: set(entry.get("depends_on", [])) for entry in manifest["execution_plan"].get("load", [])}
    while True:
        downstream = {key for key, parents in dependencies.items() if parents & changed_jobs}
        if downstream <= changed_jobs:
            break
        changed_jobs |= downstream

    def run_step(phase, key, destination, *, repeat=False):
        prior = destination.get(key, {})
        unchanged = key not in changed_jobs and prior.get("asset_fingerprint") == fingerprints[key]
        if prior.get("result") == "passed" and unchanged and not prior.get("pending_create_repairs"):
            record({"reused_steps": {("repeat:" if repeat else "") + key: prior["root_run_id"]}})
            print(f"REUSE {key} repeat={repeat} run={prior['root_run_id']}", flush=True)
            return
        prior_id = prior.get("root_run_id")
        rerun = None
        if prior_id:
            remote = get_run(call, prior_id)
            if phase == "create" and (prior.get("pending_create_repairs") or prior.get("result") == "passed" and not unchanged):
                pending = prior.get("pending_create_repairs", {})
                if not pending:
                    old_root = next(item for item in prior["runs"] if item["run_id"] == prior_id)
                    for task in resources["jobs"][key]["tasks"]:
                        reference = task.get("run_job_task", {}).get("job_id", "")
                        match = re.fullmatch(r"\$\{resources.jobs.([^.]+).id\}", reference)
                        if not match:
                            raise RuntimeError("Create repair requires the manifest's existing nested zone jobs")
                        child = match[1]
                        changes = affected_tasks(resources["jobs"][child], task_hashes[child], prior.get("task_fingerprints", {}).get(child, {}))
                        if changes:
                            old_task = next(item for item in old_root["tasks"] if item["task_key"] == task["task_key"])
                            pending[child] = {"run_id": old_task["child_run_id"], "tasks": changes}
                destination[key] = {**prior, "result": "running", "pending_create_repairs": pending}
                supplemental = destination[key].setdefault("supplemental_runs", {})
                record({"runs": destination})
                for child, repair in list(pending.items()):
                    def child_receipt(value):
                        repair["receipt"] = value
                        record({"runs": destination})
                    previous_receipt = repair.get("receipt", {})
                    if previous_receipt.get("result") != "passed":
                        with reported_step(record, "create_repair:" + child), budget.measure("create"):
                            failed = previous_receipt.get("result") == "failed"
                            execute_root(call, int(after["jobs"][child]["id"]), timeout=budget.remaining("create"), record=child_receipt,
                                         repair_run_id=previous_receipt["root_run_id"] if failed else None,
                                         rerun_tasks=[task["task_key"] for run in previous_receipt.get("runs", []) for task in run.get("tasks", []) if not task.get("excluded") and task.get("state", {}).get("result_state") != "SUCCESS"] if failed else None,
                                         resume_run_id=previous_receipt.get("root_run_id") if previous_receipt and not failed else None,
                                         resume_repair_id=previous_receipt.get("repair_id"),
                                         only_tasks=repair["tasks"],
                                         idempotency_token=hashlib.sha256(json.dumps([args.execution_id, name, key, child, fingerprints[child]]).encode()).hexdigest())
                    supplemental[child] = repair["receipt"]
                    del pending[child]
                    record({"runs": destination, "phase_seconds": budget.consumed})
                tree = execution_tree(call, prior_id)
                if tree["errors"]:
                    raise RuntimeError("; ".join(tree["errors"]))
                destination[key] = {**tree, "phase": phase, "result": "passed", "asset_fingerprint": fingerprints[key], "task_fingerprints": task_hashes, "supplemental_runs": supplemental}
                record({"runs": destination})
                return
            if remote.get("state", {}).get("life_cycle_state") in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                if unchanged and remote.get("state", {}).get("result_state") == "SUCCESS":
                    tree = execution_tree(call, prior_id)
                    if tree["errors"]:
                        raise RuntimeError("; ".join(tree["errors"]))
                    destination[key] = {**tree, "phase": phase, "result": "passed", "asset_fingerprint": fingerprints[key], "task_fingerprints": task_hashes}
                    record({"repeat_runs" if repeat else "runs": destination})
                    print(f"RECONCILED {key} repeat={repeat} successful run={prior_id}", flush=True)
                    return
                if not unchanged:
                    rerun = affected_tasks(
                        resources["jobs"][key], task_hashes[key],
                        prior.get("task_fingerprints", {}).get(key, {}),
                    )
                    if not rerun:
                        rerun = [task["task_key"] for task in resources["jobs"][key]["tasks"]]
                else:
                    rerun = [task["task_key"] for task in remote.get("tasks", []) if task.get("state", {}).get("result_state") != "SUCCESS"]
        def receipt(value):
            destination[key] = {"phase": phase, "asset_fingerprint": fingerprints[key], "task_fingerprints": task_hashes, **value}
            record({"repeat_runs" if repeat else "runs": destination})
        token = hashlib.sha256(json.dumps([args.execution_id, name, key, repeat, fingerprints[key]]).encode()).hexdigest()
        with reported_step(record, ("repeat:" if repeat else phase + ":") + key):
            try:
                with budget.measure(phase):
                    execute_root(
                        call, int(after["jobs"][key]["id"]), timeout=budget.remaining(phase),
                        record=receipt, repair_run_id=prior_id if rerun else None,
                        rerun_tasks=rerun,
                        resume_run_id=prior_id if prior_id and not rerun else None,
                        resume_repair_id=prior.get("repair_id"),
                        idempotency_token=token,
                    )
            finally:
                record({"phase_seconds": budget.consumed})

    for phase, key in roots:
        run_step(phase, key, runs)
        if needs_disable_full_refresh:
            after = deploy_bundle(
                name, resources, before, bundle, args.profile, deployment_profile,
                args.environment, full_refresh=False, force_lock=args.force_lock,
                local_user=args.local_user,
            )
            needs_disable_full_refresh = False

    def validation_query(statement):
        try:
            with budget.measure("validate"):
                return sql(statement, warehouse=environment["warehouse_id"], profile=validation_profile, timeout=budget.remaining("validate"))
        finally:
            record({"phase_seconds": budget.consumed})
    with reported_step(record, "data_validation"):
        record({"append_fixture": validate_append_fixture(validation_query)})
        data = validate_data(validation_query, catalog, manifest)
        record({"data": data})
    repeat_status = "not_requested"
    if args.verify_repeat:
        repeat_status = "running"
        record({"repeat_without_full_refresh": repeat_status})
        baseline = (resume_record or {}).get("repeat_baseline_fingerprints") if not changed_jobs else None
        baseline = baseline or business_fingerprints(validation_query, catalog, manifest)
        record({"repeat_baseline_fingerprints": baseline})
        for phase, key in roots:
            if phase == "load":
                run_step(phase, key, repeat_runs, repeat=True)
        repeated = business_fingerprints(validation_query, catalog, manifest)
        record({"repeat_fingerprints": repeated})
        if baseline != repeated:
            changed = {key: {"before": baseline.get(key), "after": repeated.get(key)} for key in baseline.keys() | repeated.keys() if baseline.get(key) != repeated.get(key)}
            record({"repeat_without_full_refresh": "failed", "repeat_fingerprint_changes": changed})
            raise RuntimeError("Unchanged reload altered business data or history versions: " + ", ".join(sorted(changed)))
        data = validate_data(validation_query, catalog, manifest)
        repeat_status = "passed"
    record({"repeat_without_full_refresh": repeat_status, "phase_seconds": budget.consumed})
    source_after = source_preflight(source_manifest, environment, validation_query, call, smoke=False)
    record({"delta_cursor_checks": validate_delta_cursors(source_manifest, environment, catalog, validation_query)})
    for key, count in source_after.items():
        raw_count = data["counts"].get(key)
        item = next((entry for entry in manifest["datasets"] if entry["key"] == key), None)
        if item is None or raw_count is None or raw_count <= 0:
            raise RuntimeError("Raw extraction is incomplete: " + key)
        if name == "databricks" and item.get("external", {}).get("extract_mode", "full") == "full" and raw_count < count:
            raise RuntimeError("Full-source raw snapshots contain fewer rows than their source: " + key)
        if name == "databricks-lakeflow" and item.get("external", {}).get("extract_mode", "full") == "full" and raw_count != count:
            raise RuntimeError("Lakeflow full-source ingestion does not match the source snapshot: " + key)
    comparison_manifest = json.loads((ROOT / "Output/databricks-lakeflow/generated/manifest.json").read_text()) if args.target == "all" else manifest
    canonical = {item["key"]: item for item in comparison_manifest["datasets"]}
    source_changes = {key: {"before": source_counts[key], "after": source_after[key]} for key in source_counts.keys() & source_after.keys() if source_counts[key] != source_after[key]}
    return {"result": "passed", "test_mode": "full", "data": data, "repeat_without_full_refresh": repeat_status, "full_data_acceptance": bool(args.verify_repeat and repeat_status == "passed"), "fingerprints": business_fingerprints(validation_query, catalog, manifest, canonical), "source_counts_after": source_after, "source_changes_during_run": source_changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="dev")
    parser.add_argument("--target", default="all")
    parser.add_argument("--profile")
    parser.add_argument("--deployment-profile", help="Optional Databricks CLI profile used only for bundle validation, planning, state, and deployment")
    parser.add_argument("--validation-profile", help="Optional Databricks CLI profile used for table data validation; must be the environment's run service principal")
    parser.add_argument("--local-user", help="Allow this exact user identity for a local Dev run; CI and Prod must use the deployment service principal")
    parser.add_argument("--force-lock", action="store_true", help="Force a stale bundle lock after the runner confirms no selected-target job or pipeline is active")
    parser.add_argument("--verify-repeat", action="store_true", help="Explicitly repeat Load jobs and verify unchanged business data and history")
    parser.add_argument("--reset", action="store_true", help="Explicitly reset owned Dev data before a fresh test; incompatible with resume")
    parser.add_argument("--refresh-dataset", action="append", default=[], help="Explicitly full-refresh one manifest dataset during a Dev Lakeflow resume migration (repeatable)")
    parser.add_argument("--resume-report", type=Path, help="Resume failed or unrun work from a previous full Dev report without resetting successful target state")
    parser.add_argument("--resume-full-refresh", action="store_true", help="Run retried Lakeflow pipeline tasks as full refreshes after source or schema changes")
    args = parser.parse_args()
    if args.reset and (args.environment != "dev" or args.resume_report):
        parser.error("--reset requires a fresh Dev run without --resume-report")
    if args.verify_repeat and args.environment != "dev":
        parser.error("--verify-repeat is only supported by the full Dev suite")
    if args.refresh_dataset and (args.environment != "dev" or args.target != "databricks-lakeflow" or not args.resume_report):
        parser.error("--refresh-dataset requires an explicit Dev resume for databricks-lakeflow")
    selected = list(TARGETS) if args.target == "all" else [args.target]
    if any(name not in TARGETS for name in selected):
        parser.error("Unsupported integration target; available: " + ", ".join(TARGETS))
    environment = ENVIRONMENTS[args.environment]
    if args.local_user and args.environment != "dev":
        parser.error("--local-user is permitted only for the local Dev environment")
    if args.local_user and (not args.profile or not args.deployment_profile):
        parser.error("A local-user run requires separate --profile and --deployment-profile values")
    if environment["test_mode"] != ("smoke" if args.environment == "prod" else "full"):
        parser.error("Prod must remain deployment/smoke only; Dev runs full acceptance")
    previous_targets = {}
    if args.resume_report:
        previous = json.loads(args.resume_report.read_text(encoding="utf-8"))
        if previous.get("environment") != args.environment or previous.get("test_mode") != "full":
            parser.error("--resume-report must be a full report for the selected environment")
        if not set(selected).issubset(previous.get("selected_targets", [])):
            parser.error("--resume-report does not include every selected target")
        previous_targets = {item["target"]: item for item in previous.get("targets", [])}
        if any(name not in previous_targets for name in selected):
            parser.error("--resume-report is missing a selected target record")
    if args.resume_full_refresh and (
        not args.resume_report
        or args.environment != "dev"
        or selected != ["databricks-lakeflow"]
    ):
        parser.error("--resume-full-refresh requires a Dev resume run for databricks-lakeflow")
    if not args.profile and os.getenv("DATABRICKS_HOST", "").rstrip("/") != environment["host"]:
        parser.error("Authenticate to the selected environment using its deployment service principal")
    report_dir = REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"integration-{args.environment}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "environment": args.environment, "selected_targets": selected, "test_mode": environment["test_mode"], "targets": [], "result": "running"}
    args.execution_id = previous.get("execution_id", str(uuid.uuid4())) if args.resume_report else str(uuid.uuid4())
    report.update(schema_version=2, execution_id=args.execution_id, verify_repeat=args.verify_repeat, reset=args.reset)
    if args.resume_report:
        report["resumed_from"] = str(args.resume_report.resolve())
    def save():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(sanitize(report), indent=2) + "\n", encoding="utf-8")
        temporary.replace(report_path)
    def global_record(value):
        for key, item in value.items():
            if key == "steps":
                report.setdefault(key, {}).update(item)
            else:
                report[key] = item
        save()
    save()
    restart_warehouse = False
    try:
        with reported_step(global_record, "authentication_and_warehouse"):
            SESSION.ensure(force=True)
            warehouse = api("GET", "/api/2.0/sql/warehouses/" + environment["warehouse_id"], profile=args.profile)
            if not warehouse.get("enable_serverless_compute"):
                raise RuntimeError("Integration requires a serverless warehouse")
            restart_warehouse = warehouse.get("state") == "STOPPED"
            if restart_warehouse:
                api("POST", "/api/2.0/sql/warehouses/" + environment["warehouse_id"] + "/start", {}, profile=args.profile)
                deadline = time.monotonic() + 300
                while True:
                    warehouse = api("GET", "/api/2.0/sql/warehouses/" + environment["warehouse_id"], profile=args.profile)
                    if warehouse.get("state") == "RUNNING":
                        break
                    if time.monotonic() >= deadline:
                        api("POST", "/api/2.0/sql/warehouses/" + environment["warehouse_id"] + "/stop", {}, profile=args.profile)
                        raise TimeoutError("Serverless SQL warehouse did not start within five minutes")
                    time.sleep(5)
        with source_bindings(environment):
            generation_targets = selected
            for name in generation_targets:
                with reported_step(global_record, "generation:" + name):
                    subprocess.run([sys.executable, "scripts/check_generation.py", "--target", name], cwd=ROOT, check=True)
        for name in selected:
            prior = previous_targets.get(name)
            evidence_fields = {"runs", "repeat_runs", "job_fingerprints", "task_fingerprints", "fingerprint_version", "dataset_refreshes", "repeat_baseline_fingerprints", "asset_fingerprint"}
            evidence = {key: copy.deepcopy(value) for key, value in (prior or {}).items() if key in evidence_fields}
            result = {**evidence, "target": name, "catalog": environment["catalogs"][name], "result": "running", "started_at": datetime.now(timezone.utc).isoformat()}
            report["targets"].append(result)
            def record(value):
                for key, item in value.items():
                    if key in {"steps", "reused_steps"}:
                        result.setdefault(key, {}).update(item)
                    else:
                        result[key] = item
                save()
            try:
                record(test_target(name, args, environment, record, resume_record=prior))
            except Exception as error:
                record({"result": "failed", "error": sanitize(f"{type(error).__name__}: {error}")})
                print(f"FAIL {name}: {sanitize(str(error))}", flush=True)
            finally:
                record({"finished_at": datetime.now(timezone.utc).isoformat()})
        successful = [item for item in report["targets"] if item["result"] == "passed"]
        if len(successful) > 1 and environment["test_mode"] == "full":
            report["comparison"] = "passed" if all(item["fingerprints"] == successful[0]["fingerprints"] for item in successful[1:]) else "failed"
        report["result"] = "passed" if len(successful) == len(selected) and report.get("comparison") != "failed" else "failed"
    except Exception as error:
        report.update(result="failed", error=sanitize(str(error)))
    finally:
        save()
        try:
            if restart_warehouse:
                api("POST", "/api/2.0/sql/warehouses/" + environment["warehouse_id"] + "/stop", {}, profile=args.profile)
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    if api("GET", "/api/2.0/sql/warehouses/" + environment["warehouse_id"], profile=args.profile).get("state") == "STOPPED":
                        break
                    time.sleep(5)
                else:
                    raise TimeoutError("Serverless SQL warehouse did not stop within five minutes")
        except Exception as error:
            report.update(result="failed", cleanup_error=sanitize(str(error)))
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"Integration {report['result']}: {report_path}", flush=True)
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
