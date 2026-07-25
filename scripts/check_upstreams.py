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
    parser.add_argument("--config", type=Path, default=Path("config/benchmark.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    updates = []
    for name, algorithm in config["algorithms"].items():
        head = remote_head(algorithm["source"])
        if head == algorithm["commit"]:
            continue
        updates.append({"algorithm": name, "before": algorithm["commit"], "after": head})
        if args.apply:
            algorithm["commit"] = head
            algorithm["image"] = f"ghcr.io/hamsterstation/rcabench-{name}:{head[:8]}"
    if args.apply and updates:
        args.config.write_text(json.dumps(config, indent=2) + "\n")
    print(json.dumps({"updates": updates}, indent=2))


if __name__ == "__main__":
    main()

