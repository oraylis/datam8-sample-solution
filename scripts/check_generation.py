"""Offline checks for the small public AdventureWorks example."""
from __future__ import annotations
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from check_public_sources import check_public_sources
from databricks_jobs import generated_resources, execution_plan
from generation_checks import check_graph, check_notebook_markdown_cells
from bundle_assets import required_assets

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",default="all")
    args=parser.parse_args()
    revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    if os.environ.get("SAMPLE_REVIEW_COMMIT") != revision:
        parser.error("Explicit manual review of this exact sample commit is required before checks")
    descriptor=ROOT/"ORAYLISDatabricksSample.dm8s"
    targets=json.loads(descriptor.read_text())["generatorTargets"]
    names=[t["name"] for t in targets]
    selected=names if args.target=="all" else [args.target]
    if set(selected)-set(names):parser.error("Available targets: "+", ".join(names))
    check_public_sources()
    subprocess.run([sys.executable,"-m","datam8","validate","-s",str(descriptor)],cwd=ROOT,check=True)
    for name in selected:
        subprocess.run([sys.executable,"-m","datam8","generate","-s",str(descriptor),name,"--clean-output"],cwd=ROOT,check=True)
        output=ROOT/next(t["outputPath"] for t in targets if t["name"]==name)
        for path in output.rglob("*.py"):ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        check_notebook_markdown_cells(output)
        if name=="databricks":
            resources=generated_resources(output.parent)
            manifest=json.loads((output/"manifest.json").read_text())
            execution_plan(resources,manifest,required_phases=manifest["lifecycle"])
            for job in resources["jobs"].values():check_graph(job["tasks"])
            required_assets(output.parent)
        print("PASS generate-only "+name)

if __name__=="__main__":main()

