#!/usr/bin/env python3
"""Update pinned algorithm commits to their upstream default-branch heads."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def remote_head(source: str) -> str:
    output = subprocess.check_output(["git", "ls-remote", source, "HEAD"], text=True)
    commit = output.split()[0]
    if len(commit) != 40:
        raise ValueError(f"unexpected HEAD for {source}: {commit}")
    return commit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/algorithms.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text())
    updates = []
    for name, image in registry["images"].items():
        head = remote_head(image["source"])
        if head == image["commit"]:
            continue
        updates.append({"image": name, "before": image["commit"], "after": head})
        if args.apply:
            image["commit"] = head
            suffix = image.get("tag_suffix", "")
            image["image"] = f"ghcr.io/hamsterstation/rcabench-{name}:{head[:8]}{suffix}"
    if args.apply and updates:
        args.registry.write_text(json.dumps(registry, indent=2) + "\n")
    print(json.dumps({"updates": updates}, indent=2))


if __name__ == "__main__":
    main()
