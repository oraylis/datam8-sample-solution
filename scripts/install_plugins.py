"""Install the pinned metadata plugins locally; plugin sources stay Git-ignored."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, help="Optional local datam8-plugins checkout")
    args = parser.parse_args()
    lock = json.loads((ROOT / "plugins.lock.json").read_text())
    token = os.getenv("DATAM8_PLUGINS_READ_TOKEN")
    if not args.repository and not token:
        raise RuntimeError(
            "datam8-plugins is private. Set DATAM8_PLUGINS_READ_TOKEN or pass a local --repository checkout."
        )
    files = []
    for plugin in lock["plugins"]:
        for name, expected in plugin["sha256"].items():
            relative = f"plugins/{plugin['id']}/{name}"
            if args.repository:
                import subprocess
                content = subprocess.check_output(["git", "-C", str(args.repository), "show", f"{lock['commit']}:{relative}"])
            else:
                repository = lock["repository"].removeprefix("https://github.com/")
                request = Request(
                    f"https://raw.githubusercontent.com/{repository}/{lock['commit']}/{relative}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urlopen(request, timeout=60) as response:
                    content = response.read()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("Plugin checksum mismatch: " + relative)
            if name == "plugin.json" and json.loads(content)["version"] != plugin["version"]:
                raise ValueError("Plugin version mismatch: " + relative)
            files.append((ROOT / "Plugins" / plugin["id"] / name, content))
    for path, content in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"Installed {len(lock['plugins'])} verified plugins at {lock['commit']}")


if __name__ == "__main__":
    main()
