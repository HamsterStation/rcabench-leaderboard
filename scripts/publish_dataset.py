#!/usr/bin/env python3
"""Publish a validated RCABench folder and split manifests to Hugging Face."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

from rcabench_leaderboard.config import load_config, read_manifest


def validate_local_data(config, data_root: Path, manifests: Path) -> dict[str, int]:
    counts = {}
    all_cases: set[str] = set()
    for split in ("all", "train", "test"):
        cases = read_manifest(manifests / f"{split}.txt")
        expected = int(config["dataset"]["expected_cases"][split])
        if len(cases) != expected:
            raise ValueError(f"{split}: found {len(cases)} cases, expected {expected}")
        counts[split] = len(cases)
        if split == "all":
            all_cases = set(cases)
    if set(read_manifest(manifests / "train.txt")) & set(read_manifest(manifests / "test.txt")):
        raise ValueError("train and test manifests overlap")
    missing = [case for case in sorted(all_cases) if not (data_root / case / "converted").is_dir()]
    if missing:
        raise ValueError(f"{len(missing)} cases are missing converted data; first={missing[0]}")
    summary_path = manifests / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text())
        expected_hash = config["dataset"].get("manifest_sha256")
        if expected_hash and summary.get("manifest_sha256") != expected_hash:
            raise ValueError("manifest SHA256 does not match config/benchmark.json")
    return counts


def dataset_card(config, counts: dict[str, int], license_id: str) -> str:
    dataset = config["dataset"]
    return f"""---
license: {license_id}
task_categories:
- tabular-classification
tags:
- root-cause-analysis
- microservices
- rcabench
---

# FSE RCABench dataset

Versioned telemetry datapacks for the RCABench RCA leaderboard.

## Version

- Revision: `{dataset['revision']}`
- Manifest SHA256: `{dataset['manifest_sha256']}`
- All cases: {counts['all']}
- Train cases: {counts['train']}
- Test cases: {counts['test']}

The train/test split is fault-type stratified and balances marginal service
coverage. See the leaderboard repository for the exact evaluation protocol.

## Access and license

This repository is private by default. Access does not override the license or
redistribution terms of the original RCABench/FSE data source.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/benchmark.json"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--license-id", required=True, help="Hugging Face license identifier")
    parser.add_argument("--license-acknowledged", action="store_true")
    parser.add_argument("--public", action="store_true", help="default is a private dataset repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    counts = validate_local_data(config, args.data_root, args.manifests)
    print(json.dumps({"status": "validated", "counts": counts}, indent=2))
    if args.dry_run:
        return
    if not args.license_acknowledged:
        parser.error("actual upload requires --license-acknowledged")
    token = os.getenv("HF_TOKEN")
    if not token:
        parser.error("HF_TOKEN is required")

    dataset = config["dataset"]
    api = HfApi(token=token)
    api.create_repo(
        repo_id=dataset["repo_id"], repo_type="dataset", private=not args.public, exist_ok=True
    )
    api.upload_large_folder(
        repo_id=dataset["repo_id"],
        repo_type="dataset",
        folder_path=args.data_root,
        allow_patterns=["*/converted/**"],
    )
    api.upload_folder(
        repo_id=dataset["repo_id"],
        repo_type="dataset",
        folder_path=args.manifests,
        path_in_repo="manifests",
    )
    with tempfile.TemporaryDirectory() as temporary:
        card = Path(temporary) / "README.md"
        card.write_text(dataset_card(config, counts, args.license_id))
        api.upload_file(
            repo_id=dataset["repo_id"],
            repo_type="dataset",
            path_or_fileobj=card,
            path_in_repo="README.md",
        )
    try:
        api.create_tag(
            repo_id=dataset["repo_id"],
            repo_type="dataset",
            tag=dataset["revision"],
        )
    except Exception as exc:
        raise RuntimeError(
            f"data uploaded, but immutable tag {dataset['revision']} could not be created: {exc}"
        ) from exc
    print(f"published https://huggingface.co/datasets/{dataset['repo_id']}/tree/{dataset['revision']}")


if __name__ == "__main__":
    main()

