"""Stage generated Databricks resources and shared notebooks inside the bundle root."""

from pathlib import Path
import shutil


def stage_bundle_assets(solution_root: Path) -> Path:
    solution_root = solution_root.resolve()
    bundle_root = solution_root / "deployment" / "databricks"
    generated = solution_root / "output" / "databricks"
    utilities = solution_root / "utils"
    if not generated.is_dir():
        raise FileNotFoundError(f"Generate the Databricks target first: {generated}")
    if not utilities.is_dir():
        raise FileNotFoundError(f"Shared Databricks notebooks not found: {utilities}")

    staged_output = bundle_root / "output"
    staged_utils = bundle_root / "utils"
    for destination in (staged_output, staged_utils):
        resolved_destination = destination.resolve()
        if not resolved_destination.is_relative_to(bundle_root.resolve()):
            raise ValueError(f"Refusing to clear a staging path outside the bundle root: {destination}")
        if destination.exists():
            shutil.rmtree(destination)
    shutil.copytree(generated, staged_output / "databricks")
    shutil.copytree(utilities, staged_utils)
    return bundle_root


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    bundle = stage_bundle_assets(root)
    print(f"Staged Databricks bundle assets in {bundle}")
