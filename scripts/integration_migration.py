"""Explicit, manifest-scoped dataset refresh for an existing Dev deployment."""
from __future__ import annotations

import time
from urllib.parse import quote


def refresh_datasets(selected, manifest, deployment, catalog, api, record, *, previous=None, timeout=5400):
    datasets = {item["key"]: item for item in manifest["datasets"]}
    if set(selected) - datasets.keys():
        raise ValueError("Refresh selection contains objects outside the generated manifest")
    grouped = {}
    for key in selected:
        pipeline = datasets[key]["pipeline"]
        if not deployment.get("pipelines", {}).get(pipeline, {}).get("id"):
            raise ValueError("Dataset refresh requires a bound existing pipeline")
        grouped.setdefault(pipeline, []).append(catalog + "." + key)
    # Ingestion precedes modeled processing; within processing use the manifest DAG.
    pending = set(grouped)
    ordered = []
    while pending:
        ready = sorted(key for key in pending if not any(
            datasets[parent]["pipeline"] in pending and datasets[parent]["pipeline"] != key
            for item in datasets.values() if item["pipeline"] == key
            for parent in item.get("dependencies", [])
        ))
        if not ready:
            raise ValueError("Dataset refresh selection contains a pipeline dependency cycle")
        ordered.extend(ready)
        pending.difference_update(ready)
    receipts = dict(previous or {})
    deadline = time.monotonic() + timeout
    for key in ordered:
        pipeline_id = deployment["pipelines"][key]["id"]
        selection = sorted(grouped[key])
        receipt = receipts.get(key, {})
        if receipt and (receipt.get("pipeline_id") != pipeline_id or receipt.get("selection") != selection):
            raise ValueError("Stored migration evidence does not match the requested pipeline selection")
        if receipt.get("result") == "passed":
            continue
        attempts = list(receipt.get("attempts", []))
        if receipt.get("result") in {"failed", "timed_out"}:
            attempts.append({field: value for field, value in receipt.items() if field != "attempts"})
            receipt = {}
        if receipt and not receipt.get("update_id"):
            raise RuntimeError("Migration start has an unknown outcome; reconcile its recorded request before retrying")
        if not receipt:
            if api("GET", "/api/2.0/pipelines/" + pipeline_id).get("state") not in {"IDLE", "FAILED"}:
                raise RuntimeError("Selected migration pipeline is active")
            for name in selection:
                try:
                    metadata = api("GET", "/api/2.1/unity-catalog/tables/" + quote(name, safe="."))
                except RuntimeError as error:
                    if not any(marker in str(error).lower() for marker in ("not found", "does not exist", "http 404")):
                        raise
                    continue
                owner = metadata.get("pipeline_id") or metadata.get("properties", {}).get("pipelines.pipelineId")
                if owner != pipeline_id:
                    raise RuntimeError("Migration table does not belong to its selected pipeline: " + name)
            receipt = {"pipeline_id": pipeline_id, "selection": selection, "result": "starting", "requested_at_ms": int(time.time() * 1000), "attempts": attempts}
            receipts[key] = receipt
            record({"dataset_refreshes": receipts})
            result = api("POST", "/api/2.0/pipelines/" + pipeline_id + "/updates", {"full_refresh_selection": selection})
            receipt.update(update_id=result["update_id"], result="running")
            record({"dataset_refreshes": receipts})
        while time.monotonic() < deadline:
            update = api("GET", "/api/2.0/pipelines/" + pipeline_id + "/updates/" + receipt["update_id"])["update"]
            if update["state"] in {"COMPLETED", "FAILED", "CANCELED"}:
                receipt.update(result="passed" if update["state"] == "COMPLETED" else "failed", state=update["state"])
                record({"dataset_refreshes": receipts})
                if receipt["result"] != "passed":
                    raise RuntimeError("Selected dataset migration failed: " + key + " / " + receipt["update_id"])
                break
            time.sleep(15)
        else:
            api("POST", "/api/2.0/pipelines/" + pipeline_id + "/stop", {})
            receipt["result"] = "timed_out"
            stop_deadline = time.monotonic() + 120
            while time.monotonic() < stop_deadline:
                if api("GET", "/api/2.0/pipelines/" + pipeline_id).get("state") in {"IDLE", "FAILED"}:
                    receipt["cancellation"] = "confirmed"
                    break
                time.sleep(5)
            else:
                receipt["cancellation"] = "pending"
            record({"dataset_refreshes": receipts})
            raise TimeoutError("Dataset migration timed out; selected pipeline stop requested")
    return receipts
