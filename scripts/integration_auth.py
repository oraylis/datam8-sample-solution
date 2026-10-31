"""Bounded GitHub/Entra session renewal and safe diagnostic serialization."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from urllib.request import Request, urlopen


def sanitize(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if re.search(r"(?i)token|secret|assertion|authorization|password", key) else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    for key, secret in os.environ.items():
        if re.search(r"(?i)token|secret|password|assertion", key) and len(secret) > 8:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED JWT]", text)
    text = re.sub(r"(?i)[a-z0-9.-]+\.cloudapp\.azure\.com", "[SOURCE_HOST]", text)
    text = re.sub(r"(?i)([\w-]*(?:token|secret|password|assertion|authorization)[\w-]*\s*[=:]\s*)(?:Bearer\s+)?[^\s,;\"']+", r"\1[REDACTED]", text)
    return text


class AzureOidcSession:
    """Renew the existing Entra federated login; never retry a cloud mutation."""

    def __init__(self):
        self.renewed_at = None
        self.lock = threading.Lock()

    def ensure(self, *, force=False):
        if not (os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("DATABRICKS_AUTH_TYPE") == "azure-cli"):
            return
        with self.lock:
            if not force and self.renewed_at is not None and time.monotonic() - self.renewed_at < 1800:
                return
            url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=api%3A%2F%2FAzureADTokenExchange"
            request = Request(url, headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
            try:
                with urlopen(request, timeout=30) as response:
                    assertion = json.load(response)["value"]
                result = subprocess.run([
                    "az", "login", "--service-principal", "--username", os.environ["ARM_CLIENT_ID"],
                    "--tenant", os.environ["ARM_TENANT_ID"], "--federated-token", assertion,
                    "--allow-no-subscriptions", "--output", "none",
                ], capture_output=True, text=True, timeout=120)
                if result.returncode:
                    raise RuntimeError(sanitize(result.stderr))
            except Exception as error:
                raise RuntimeError("Entra OIDC session renewal failed: " + sanitize(str(error))) from None
            self.renewed_at = time.monotonic()
            print("Entra OIDC session renewed", flush=True)


SESSION = AzureOidcSession()
