"""Validate and generate selected sample targets in a disposable solution copy."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_lakeflow import check_notebook_markdown_cells

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "ORAYLISDatabricksSample.dm8s"


def run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env={**os.environ, "PYTHONUTF8": "1"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="all")
    args = parser.parse_args()
    targets = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))["generatorTargets"]
    names = [item["name"] for item in targets]
    selected = names if args.target == "all" else [args.target]
    unknown = sorted(set(selected) - set(names))
    if unknown:
        parser.error(f"Unknown target(s): {', '.join(unknown)}. Available: {', '.join(names)}")

    with tempfile.TemporaryDirectory(prefix="datam8-generation-") as temporary:
        copy = Path(temporary) / "solution"
        shutil.copytree(
            ROOT,
            copy,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "__pycache__", ".ruff_cache", ".databricks", "generated"
            ),
        )
        solution_file = copy / DESCRIPTOR.name
        run(["datam8", "validate", "--solution", str(solution_file)], cwd=copy)
        for name in selected:
            run(
                ["datam8", "generate", name, "--solution", str(solution_file), "--clean-output"],
                cwd=copy,
            )
            output_path = next(item["outputPath"] for item in targets if item["name"] == name)
            output = copy / output_path
            if not output.is_dir() or not any(path.is_file() for path in output.rglob("*")):
                raise RuntimeError(f"Target {name} generated no files at {output_path}")
            check_notebook_markdown_cells(output)
            if name == "databricks-lakeflow":
                run(
                    [
                        sys.executable,
                        str(copy / "scripts/check_lakeflow.py"),
                        "--worker",
                        str(copy),
                        name,
                    ],
                    cwd=copy,
                )
            print(f"PASS: {name}: {sum(path.is_file() for path in output.rglob('*'))} files")


if __name__ == "__main__":
    main()
