# Power BI / Fabric Deployment (manual)

This folder contains a manual deployment setup, independent from datam8 generator execution.

## Files

- `powerbi.yml`: Target/workspace mapping and deploy defaults.
- `azure-pipelines.powerbi.yml`: Azure DevOps pipeline for Fabric CI/CD.
- `.deploy/deploy-to-fabric.py`: Python runner using `fabric-cicd`.

## Prerequisites

- Service principal is enabled for Fabric APIs and has access to target workspaces.
- Azure DevOps variable groups:
  - `fabric_cicd_group_sensitive`: `aztenantid`, `azclientid`, `azspnsecret`
  - `fabric_cicd_group_non_sensitive`: optional non-secret values
- `powerbi.yml` workspace names are set for `dev` and `prod`.

## Usage

1. Create an Azure DevOps pipeline from `Output/powerbi-tabular/azure-pipelines.powerbi.yml`.
2. Run with parameter `target_env=dev` or `target_env=prod`.
3. Optionally override item types using `item_types_in_scope` (for example `SemanticModel,Report`).

## Notes

- Deployment source path defaults to `Output/powerbi-tabular/generated/powerbi-tabular`.
- `delete_orphans` is `false` by default to avoid accidental deletions.
