"""Deploy Fabric (Power BI) artifacts using fabric-cicd.

This script is intentionally generic and reads all deployment-specific values
from powerbi.yml and Azure DevOps pipeline variables.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import requests
import yaml
from azure.identity import ClientSecretCredential
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items


FABRIC_RESOURCE = "https://api.fabric.microsoft.com/"
FABRIC_SCOPE = FABRIC_RESOURCE + ".default"
FABRIC_WORKSPACES_API = FABRIC_RESOURCE + "v1/workspaces"


def _parse_item_types(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []

    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (ValueError, SyntaxError):
        pass

    return [part.strip() for part in raw.split(",") if part.strip()]


def _workspace_id_for_name(
    workspace_name: str,
    token: str,
) -> str:
    response = requests.get(
        FABRIC_WORKSPACES_API,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()

    for workspace in response.json().get("value", []):
        if workspace.get("displayName") == workspace_name:
            workspace_id = workspace.get("id")
            if workspace_id:
                return workspace_id

    raise RuntimeError(f"Workspace '{workspace_name}' not found or not accessible.")


def _load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a YAML object.")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Fabric artifacts with fabric-cicd")
    parser.add_argument("--config", required=True, help="Path to powerbi.yml")
    parser.add_argument("--target-env", required=True, help="Deployment target key in config.targets")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument(
        "--item-types",
        default="",
        help="Optional override list, e.g. \"['SemanticModel','Report']\" or "
        '"SemanticModel,Report"',
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = _load_config(config_path)

    deployment_cfg = config.get("deployment", {}) or {}
    targets_cfg = config.get("targets", {}) or {}
    target_cfg = targets_cfg.get(args.target_env)
    if not target_cfg:
        raise KeyError(f"Target '{args.target_env}' is missing in powerbi.yml")

    workspace_name = str(target_cfg.get("workspace_name") or "").strip()
    if not workspace_name:
        raise ValueError(f"Target '{args.target_env}' has no workspace_name configured")

    environment_name = str(target_cfg.get("environment") or args.target_env).strip()
    repo_relative = str(deployment_cfg.get("repository_directory") or "./generated/powerbi-tabular").strip()
    repository_directory = (config_path.parent / repo_relative).resolve()

    if not repository_directory.exists():
        raise FileNotFoundError(f"Repository directory not found: {repository_directory}")

    override_item_types = _parse_item_types(args.item_types)
    item_types_in_scope = override_item_types or [
        str(item).strip()
        for item in (deployment_cfg.get("item_types_in_scope") or [])
        if str(item).strip()
    ]
    if not item_types_in_scope:
        raise ValueError("No item types configured. Set deployment.item_types_in_scope or --item-types")

    token_credential = ClientSecretCredential(
        tenant_id=args.tenant_id,
        client_id=args.client_id,
        client_secret=args.client_secret,
    )
    token = token_credential.get_token(FABRIC_SCOPE)

    workspace_id = _workspace_id_for_name(workspace_name, token.token)

    target_workspace = FabricWorkspace(
        workspace_id=workspace_id,
        environment=environment_name,
        repository_directory=str(repository_directory),
        item_type_in_scope=item_types_in_scope,
    )

    publish_all_items(target_workspace)

    if bool(deployment_cfg.get("delete_orphans", False)):
        unpublish_all_orphan_items(target_workspace)


if __name__ == "__main__":
    main()
