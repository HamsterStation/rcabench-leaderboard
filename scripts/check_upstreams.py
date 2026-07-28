#!/usr/bin/env python3
"""Update buildable algorithm pins that opt in to upstream tracking."""

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


def check_registry(registry_path: Path, *, apply: bool = False) -> dict[str, list[dict[str, str]]]:
    raw = registry_path.read_text()
    registry = json.loads(raw)
    updates: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    replacements: list[tuple[str, str]] = []

    for name, image in registry["images"].items():
        if not image.get("watch", True):
            skipped.append({"image": name, "reason": "upstream tracking disabled"})
            continue

        head = remote_head(image["source"])
        if head == image["commit"]:
            continue

        before = image["commit"]
        suffix = image.get("tag_suffix", "")
        next_image = f"ghcr.io/hamsterstation/rcabench-{name}:{head[:8]}{suffix}"
        updates.append({"image": name, "before": before, "after": head})
        replacements.extend(((before, head), (image["image"], next_image)))

    if apply and updates:
        # Replace exact JSON string values so automated PRs do not reformat the registry.
        for before, after in replacements:
            old = json.dumps(before)
            if raw.count(old) != 1:
                raise ValueError(f"expected one registry occurrence of {before!r}")
            raw = raw.replace(old, json.dumps(after), 1)
        registry_path.write_text(raw)

    return {"updates": updates, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/algorithms.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(json.dumps(check_registry(args.registry, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
