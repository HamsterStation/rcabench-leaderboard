from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from huggingface_hub import HfApi, hf_hub_download

from .config import (
    LEGACY_DATASET_REVISIONS,
    SUMMARY_DIGEST_DATASETS,
    load_dataset_registry,
    load_registered_configs,
)


def _case_name(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} contains an empty case name")
    value = value.strip()
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"{description} contains an unsafe case name: {value!r}")
    return value


def parse_manifest(content: bytes, description: str) -> list[str]:
    try:
        cases = [_case_name(line, description) for line in content.decode().splitlines() if line]
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} is not UTF-8") from exc
    if len(cases) != len(set(cases)):
        raise ValueError(f"{description} contains duplicate cases")
    return cases


def validate_partition(
    manifests: dict[str, list[str]], expected_cases: dict[str, Any]
) -> dict[str, int]:
    for split in ("all", "train", "test"):
        expected = int(expected_cases[split])
        actual = len(manifests[split])
        if actual != expected:
            raise ValueError(f"{split} manifest has {actual} cases; expected {expected}")
    all_cases = set(manifests["all"])
    train_cases = set(manifests["train"])
    test_cases = set(manifests["test"])
    if train_cases & test_cases:
        raise ValueError("train and test manifests overlap")
    if train_cases | test_cases != all_cases:
        raise ValueError("train and test manifests do not exactly partition all cases")
    return {split: len(manifests[split]) for split in ("all", "train", "test")}


def validate_injection(content: bytes, description: str) -> None:
    try:
        injection = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is not valid UTF-8 JSON") from exc
    ground_truth = injection.get("ground_truth") if isinstance(injection, dict) else None
    sources = ground_truth if isinstance(ground_truth, list) else [ground_truth]
    if not sources or not all(isinstance(source, dict) for source in sources):
        raise ValueError(f"{description} ground_truth must be an object or object list")
    services = []
    for source in sources:
        value = source.get("service")
        services.extend(value if isinstance(value, list) else [value])
    if not any(isinstance(service, str) and service.strip() for service in services):
        raise ValueError(f"{description} ground_truth.service must contain a service name")


class HFDatasetFiles:
    def __init__(self, repo_id: str, revision: str, token: str | None):
        self.repo_id = repo_id
        self.revision = revision
        self.token = token

    def read(self, filename: str) -> bytes:
        local = hf_hub_download(
            repo_id=self.repo_id,
            repo_type="dataset",
            revision=self.revision,
            filename=filename,
            token=self.token,
        )
        return Path(local).read_bytes()


def _sample(cases: list[str], size: int) -> list[str]:
    if len(cases) <= size:
        return cases
    if size == 1:
        return [cases[0]]
    return [cases[round(index * (len(cases) - 1) / (size - 1))] for index in range(size)]


def _validate_native(
    config: dict[str, Any], read: Callable[[str], bytes], sample_size: int
) -> dict[str, Any]:
    dataset = config["dataset"]
    manifest_bytes = {
        split: read(dataset["manifests"][split]) for split in ("all", "train", "test")
    }
    manifests = {
        split: parse_manifest(content, f"{split} manifest")
        for split, content in manifest_bytes.items()
    }
    digest = hashlib.sha256(manifest_bytes["all"]).hexdigest()
    legacy = (dataset["repo_id"], dataset["revision"]) in LEGACY_DATASET_REVISIONS
    summary_digest = dataset["repo_id"] in SUMMARY_DIGEST_DATASETS
    if not legacy and not summary_digest and digest != dataset["manifest_sha256"]:
        raise ValueError(f"all manifest digest mismatch: {digest}")
    counts = validate_partition(manifests, dataset["expected_cases"])
    all_manifest = PurePosixPath(dataset["manifests"]["all"])
    summary_path = str(all_manifest.parent / "summary.json")
    summary = json.loads(read(summary_path))
    if summary.get("manifest_sha256") != dataset["manifest_sha256"]:
        raise ValueError("manifests/summary.json digest does not match dataset.manifest_sha256")
    summary_counts = {
        "all": int(summary.get("total", 0)),
        "train": int(summary.get("train", 0)),
        "test": int(summary.get("test", 0)),
    }
    if summary_counts != counts:
        raise ValueError(
            f"manifest summary counts do not match manifests: {summary_counts} != {counts}"
        )
    data_dir = PurePosixPath(dataset.get("data_dir", "."))
    sampled = _sample(manifests["all"], sample_size)
    for case in sampled:
        injection_path = str(data_dir / case / "converted" / "injection.json")
        validate_injection(read(injection_path), injection_path)
    return {"counts": counts, "manifest_sha256": digest, "sampled_cases": sampled}


def _validate_ops_lite(
    config: dict[str, Any], config_path: Path, read: Callable[[str], bytes], sample_size: int
) -> dict[str, Any]:
    dataset = config["dataset"]
    source = read("manifest.jsonl")
    digest = hashlib.sha256(source).hexdigest()
    if digest != dataset["manifest_sha256"]:
        raise ValueError(f"OPS-Lite manifest digest mismatch: {digest}")
    try:
        records = [json.loads(line) for line in source.decode().splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OPS-Lite manifest.jsonl is invalid") from exc
    names = [_case_name(record.get("name"), "manifest.jsonl") for record in records]
    if len(names) != len(set(names)):
        raise ValueError("OPS-Lite manifest.jsonl contains duplicate cases")
    pinned = dataset.get("pinned_split_manifests")
    if not isinstance(pinned, dict):
        raise ValueError("OPS-Lite requires pinned_split_manifests")
    manifests = {
        "all": names,
        "train": parse_manifest((config_path.parent / pinned["train"]).read_bytes(), "train"),
        "test": parse_manifest((config_path.parent / pinned["test"]).read_bytes(), "test"),
    }
    counts = validate_partition(manifests, dataset["expected_cases"])
    sampled = _sample(names, sample_size)
    for case in sampled:
        injection_path = f"cases/{case}/injection.json"
        validate_injection(read(injection_path), injection_path)
    return {"counts": counts, "sampled_cases": sampled}


def changed_datasets(root: Path, base_root: Path) -> list[str]:
    registry_path = root / "config/datasets.json"
    registry = load_dataset_registry(registry_path)["datasets"]
    base_path = base_root / "config/datasets.json"
    base = load_dataset_registry(base_path)["datasets"] if base_path.is_file() else {}
    removed = set(base) - set(registry)
    if removed:
        raise ValueError(
            f"dataset removal requires a separate maintainer change: {sorted(removed)}"
        )
    changed = []
    for name, entry in registry.items():
        base_entry = base.get(name)
        config_path = root / "config" / entry["config"]
        base_config = base_root / "config" / base_entry["config"] if base_entry else None
        config_changed = base_config is None or config_path.read_bytes() != base_config.read_bytes()
        if entry != base_entry or config_changed:
            changed.append(name)
    return sorted(changed)


def validate_submissions(root: Path, base_root: Path, sample_size: int = 3) -> dict[str, Any]:
    registry_path = root / "config/datasets.json"
    registry = load_dataset_registry(registry_path)["datasets"]
    configs = load_registered_configs(registry_path)
    changed = changed_datasets(root, base_root)
    base_registry = load_dataset_registry(base_root / "config/datasets.json")["datasets"]
    base_configs = (
        load_registered_configs(base_root / "config/datasets.json") if base_registry else {}
    )
    token = os.getenv("HF_TOKEN")
    results = []
    for name in changed:
        entry = registry[name]
        config = configs[name]
        dataset = config["dataset"]
        legacy = (dataset["repo_id"], dataset["revision"]) in LEGACY_DATASET_REVISIONS
        base_dataset = base_configs.get(name, {}).get("dataset", {})
        if legacy and (
            base_dataset.get("repo_id"), base_dataset.get("revision")
        ) != (dataset["repo_id"], dataset["revision"]):
            raise ValueError(f"new dataset {name} must use a 40-character Hugging Face commit SHA")
        info = HfApi(token=token).dataset_info(
            dataset["repo_id"], revision=dataset["revision"]
        )
        if not legacy and info.sha != dataset["revision"]:
            raise ValueError(
                f"dataset {name} revision resolves to {info.sha}, not {dataset['revision']}"
            )
        files = HFDatasetFiles(dataset["repo_id"], dataset["revision"], token)
        config_path = root / "config" / entry["config"]
        if entry["adapter"] == "native":
            report = _validate_native(config, files.read, sample_size)
        elif entry["adapter"] == "ops-lite":
            report = _validate_ops_lite(config, config_path, files.read, sample_size)
        else:  # Registry validation keeps this unreachable.
            raise ValueError(f"unsupported adapter: {entry['adapter']}")
        results.append(
            {
                "dataset": name,
                "repo_id": dataset["repo_id"],
                "revision": dataset["revision"],
                "adapter": entry["adapter"],
                **report,
            }
        )
    return {"status": "valid", "changed_datasets": changed, "results": results}
