from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import (
    LEGACY_DATASET_REVISIONS,
    SUMMARY_DIGEST_DATASETS,
    SUPPORTED_DATASET_ADAPTERS,
    manifest_path,
    read_manifest,
)
from .ops_lite import normalize_ops_lite


def validate_manifest_partition(config: dict[str, Any], snapshot: str | Path) -> dict[str, int]:
    manifests = {
        split: read_manifest(manifest_path(config, snapshot, split))
        for split in ("all", "train", "test")
    }
    for split, cases in manifests.items():
        expected = int(config["dataset"]["expected_cases"][split])
        if len(cases) != expected:
            raise ValueError(f"{split} manifest has {len(cases)} cases; expected {expected}")
    all_cases = set(manifests["all"])
    train_cases = set(manifests["train"])
    test_cases = set(manifests["test"])
    if train_cases & test_cases:
        raise ValueError("train and test manifests overlap")
    if train_cases | test_cases != all_cases:
        raise ValueError("train and test manifests do not exactly partition all cases")
    return {split: len(cases) for split, cases in manifests.items()}


def normalize_dataset(
    config: dict[str, Any], config_path: Path, snapshot: Path, adapter: str
) -> dict[str, Any]:
    if adapter not in SUPPORTED_DATASET_ADAPTERS:
        raise ValueError(f"unsupported dataset adapter: {adapter}")
    dataset = config["dataset"]
    if adapter == "ops-lite":
        pinned = dataset.get("pinned_split_manifests", {})
        metadata = normalize_ops_lite(
            snapshot,
            expected_manifest_sha256=dataset.get("manifest_sha256"),
            expected_cases=int(dataset["expected_cases"]["all"]),
            test_size=int(dataset["expected_cases"]["test"]),
            seed=int(dataset.get("split_seed", 42)),
            pinned_train_manifest=config_path.parent / pinned["train"] if pinned else None,
            pinned_test_manifest=config_path.parent / pinned["test"] if pinned else None,
            source_revision=dataset["revision"],
        )
    else:
        all_manifest = manifest_path(config, snapshot, "all")
        digest = hashlib.sha256(all_manifest.read_bytes()).hexdigest()
        legacy = (dataset["repo_id"], dataset["revision"]) in LEGACY_DATASET_REVISIONS
        summary_digest = dataset["repo_id"] in SUMMARY_DIGEST_DATASETS
        if not legacy and not summary_digest and digest != dataset["manifest_sha256"]:
            raise ValueError(
                f"all manifest digest mismatch: expected {dataset['manifest_sha256']}, "
                f"found {digest}"
            )
        metadata = {
            "schema_version": 1,
            "adapter": "native",
            "source_revision": dataset["revision"],
            "manifest_sha256": digest,
        }
    metadata["manifest_counts"] = validate_manifest_partition(config, snapshot)
    return metadata


def format_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, indent=2)
