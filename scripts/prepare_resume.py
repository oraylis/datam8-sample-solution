"""Select and sanitize a downloaded integration report without printing its contents."""
import json
import sys
import os
import base64
import gzip
import io
from pathlib import Path

from integration_auth import sanitize


def prepare(source, destination):
    candidates = []
    for path in source.glob("integration-*.json"):
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if report.get("environment") and report.get("targets"):
            candidates.append((path.name, report))
    if not candidates:
        raise ValueError("Artifact contains no integration report")
    report = sorted(candidates, key=lambda item: item[0])[-1][1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sanitize(report), indent=2) + "\n", encoding="utf-8")
    cache = source / ("source-preflight-" + report["environment"] + ".json")
    if cache.exists():
        (destination.parent / cache.name).write_text(json.dumps(sanitize(json.loads(cache.read_text())), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "--from-environment":
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(os.environ["INTEGRATION_RESUME_EVIDENCE"], validate=True))) as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Resume evidence exceeds one MiB")
        report = json.loads(raw)
        if report.get("test_mode") != "full" or not report.get("targets"):
            raise ValueError("Operator evidence must be an integration report")
        destination = Path(sys.argv[2])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(sanitize(report), indent=2) + "\n", encoding="utf-8")
    else:
        prepare(Path(sys.argv[1]), Path(sys.argv[2]))
