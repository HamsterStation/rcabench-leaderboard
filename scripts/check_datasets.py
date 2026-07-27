#!/usr/bin/env python3
"""Pin new revisions from trusted, registered Hugging Face datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rcabench_leaderboard.config import load_dataset_registry
from rcabench_leaderboard.ops_lite import iterative_train_test_split


def _request(url: str) -> bytes:
    headers = {"User-Agent": "rcabench-leaderboard-dataset-watcher/1"}
    if token := os.getenv("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _repo_sha(repo_id: str, revision: str | None = None) -> str:
    encoded = urllib.parse.quote(repo_id, safe="/")
    suffix = f"/revision/{urllib.parse.quote(revision, safe='')}" if revision else ""
    value = json.loads(_request(f"https://huggingface.co/api/datasets/{encoded}{suffix}"))
    sha = value.get("sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError(f"Hugging Face returned no valid revision for {repo_id}")
    return sha


def _file(repo_id: str, revision: str, path: str) -> bytes:
    encoded_repo = urllib.parse.quote(repo_id, safe="/")
    encoded_revision = urllib.parse.quote(revision, safe="")
    encoded_path = urllib.parse.quote(path, safe="/")
    return _request(
        f"https://huggingface.co/datasets/{encoded_repo}/resolve/{encoded_revision}/{encoded_path}"
    )


def _write_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(json.dumps(config, indent=2) + "\n")


def _update_fse(config_path: Path, config: dict[str, Any], revision: str) -> None:
    dataset = config["dataset"]
    summary = json.loads(_file(dataset["repo_id"], revision, "manifests/summary.json"))
    required = ("manifest_sha256", "total", "train", "test")
    if any(key not in summary for key in required):
        raise ValueError("FSE manifests/summary.json is missing required version fields")
    dataset["revision"] = revision
    dataset["manifest_sha256"] = summary["manifest_sha256"]
    dataset["expected_cases"] = {
        "all": int(summary["total"]),
        "train": int(summary["train"]),
        "test": int(summary["test"]),
    }
    _write_config(config_path, config)


def _update_ops_lite(config_path: Path, config: dict[str, Any], revision: str) -> None:
    dataset = config["dataset"]
    manifest = _file(dataset["repo_id"], revision, "manifest.jsonl")
    records = [json.loads(line) for line in manifest.decode().splitlines() if line.strip()]
    names = [record.get("name") for record in records]
    if not records or not all(isinstance(name, str) and name for name in names):
        raise ValueError("OPS-Lite manifest contains an invalid case name")
    if len(names) != len(set(names)):
        raise ValueError("OPS-Lite manifest contains duplicate case names")
    old_counts = dataset["expected_cases"]
    test_ratio = int(old_counts["test"]) / int(old_counts["all"])
    test_size = max(1, min(len(records) - 1, round(len(records) * test_ratio)))
    train, test = iterative_train_test_split(
        records, test_size=test_size, seed=int(dataset.get("split_seed", 42))
    )
    pinned = dataset["pinned_split_manifests"]
    for split, cases in (("train", train), ("test", test)):
        target = config_path.parent / pinned[split]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(cases) + "\n")
    dataset["revision"] = revision
    dataset["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
    dataset["expected_cases"] = {
        "all": len(records),
        "train": len(train),
        "test": len(test),
    }
    _write_config(config_path, config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/datasets.json"))
    parser.add_argument("--datasets", default="all", help="comma-separated dataset names or all")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    registry = load_dataset_registry(args.registry)
    selected = set(registry["datasets"])
    if args.datasets != "all":
        selected = {name.strip() for name in args.datasets.split(",") if name.strip()}
        unknown = selected - set(registry["datasets"])
        if unknown:
            raise ValueError(f"unknown datasets: {', '.join(sorted(unknown))}")
    updates = []
    for name, entry in sorted(registry["datasets"].items()):
        if name not in selected or not entry.get("watch", False):
            continue
        config_path = args.registry.parent / entry["config"]
        config = json.loads(config_path.read_text())
        dataset = config["dataset"]
        current_sha = _repo_sha(dataset["repo_id"], dataset["revision"])
        head_sha = _repo_sha(dataset["repo_id"])
        if current_sha == head_sha:
            continue
        updates.append({"dataset": name, "before": dataset["revision"], "after": head_sha})
        if args.apply:
            adapter = entry.get("update_adapter")
            if adapter == "fse":
                _update_fse(config_path, config, head_sha)
            elif adapter == "ops-lite":
                _update_ops_lite(config_path, config, head_sha)
            else:
                raise ValueError(f"dataset {name} has no supported update adapter")
    print(json.dumps({"updates": updates}, indent=2))


if __name__ == "__main__":
    main()
