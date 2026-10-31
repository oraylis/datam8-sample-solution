"""Apply non-secret environment bindings to the local solution and restore them."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def model_cli(*arguments, data=None):
    result = subprocess.run([sys.executable, "-m", "datam8", "-s", str(ROOT / "ORAYLISDatabricksSample.dm8s"), *arguments, "--json"],
                            input=json.dumps(data) if data is not None else None, capture_output=True, text=True,
                            encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}, timeout=180)
    response = json.loads(result.stdout)
    if result.returncode or not response.get("ok"):
        raise RuntimeError("DataM8 operation failed: " + " ".join(arguments[:2]) + ": " + str(response.get("error")))
    return response


@contextmanager
def source_bindings(configuration):
    originals = {}
    try:
        for source, binding in configuration["source_bindings"].items():
            locator = "dataSources/" + source
            original = model_cli("show", locator)["item"]["data"]["extendedProperties"]
            originals[locator] = original
            changes = {key: value for key, value in binding.items() if key != "connection_suffix"}
            changes["unityCatalogConnection"] = binding["connection_suffix"]
            model_cli("update", locator, "--file", "-", data={"extendedProperties": {**original, **changes}})
        yield
    finally:
        errors = []
        for locator, original in originals.items():
            try:
                model_cli("update", locator, "--file", "-", data={"extendedProperties": original})
            except Exception as error:
                errors.append(f"{locator}: {error}")
        if errors:
            raise RuntimeError("Could not restore neutral local bindings: " + "; ".join(errors))
