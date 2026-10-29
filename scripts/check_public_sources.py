"""Reject concrete source endpoints and secret values in public sample metadata."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check_public_sources():
    for source in json.loads((ROOT / "Base/DataSources.json").read_text())["dataSources"]:
        fields = source.get("extendedProperties", {})
        for key, value in fields.items():
            if not isinstance(value, str):
                continue
            if key in {"host", "server", "serverName"} and not value.endswith(".example.invalid"):
                raise ValueError(f"{source['name']}: public source host must use .example.invalid")
            if key in {"base_url", "token_url"} and not (urlsplit(value).hostname or "").endswith(".example.invalid"):
                raise ValueError(f"{source['name']}: public API URL must use .example.invalid")
            if key in {"password", "client_secret", "api_key", "bearer_token", "connectionstring"} and not value.startswith("ref://sample/"):
                raise ValueError(f"{source['name']}: public secret field must contain a sample reference")
            if key in {"username", "user"} and value != "sample_reader":
                raise ValueError(f"{source['name']}: public source user must be sample_reader")
    for folder in (ROOT / "Base", ROOT / "Model"):
        for path in folder.rglob("*.json"):
            text = path.read_text()
            if ".cloudapp.azure.com" in text or "aut0ora0dev" in text:
                raise ValueError("Concrete source infrastructure found in " + str(path.relative_to(ROOT)))


if __name__ == "__main__":
    check_public_sources()
    print("PASS public source metadata contains neutral endpoints and secret references")
