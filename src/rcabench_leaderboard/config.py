from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any


class ConfigError(ValueError):
    pass


DATASET_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HF_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_DATASET_ADAPTERS = frozenset({"native", "ops-lite"})
LEGACY_DATASET_REVISIONS = frozenset({("HamsterStation/rcabench-fse", "v1.0.0")})
SUMMARY_DIGEST_DATASETS = frozenset({"HamsterStation/rcabench-fse"})
DATASET_ENTRY_KEYS = frozenset({"config", "adapter", "watch", "update_adapter"})
DATASET_CONFIG_KEYS = frozenset(
    {
        "repo_id",
        "repo_type",
        "revision",
        "manifest_sha256",
        "split_seed",
        "pinned_split_manifests",
        "download_workers",
        "allow_patterns",
        "data_dir",
        "manifests",
        "expected_cases",
    }
)
ALGORITHM_OVERRIDE_KEYS = frozenset({"workers", "max_algorithm_errors", "schedule_priority"})


def _read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {description} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{description} must contain a JSON object: {path}")
    return value


def load_algorithm_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    registry = _read_json(registry_path, "algorithm registry")
    if registry.get("schema_version") != 1:
        raise ConfigError("algorithm registry schema_version must be 1")
    images = registry.get("images")
    algorithms = registry.get("algorithms")
    if not isinstance(images, dict) or not isinstance(algorithms, dict) or not algorithms:
        raise ConfigError("algorithm registry requires non-empty images and algorithms objects")
    resolved: dict[str, Any] = {}
    for name, definition in algorithms.items():
        image_ref = definition.get("image_ref")
        if image_ref not in images:
            raise ConfigError(f"algorithms.{name}.image_ref references unknown image {image_ref}")
        resolved[name] = {**deepcopy(images[image_ref]), **deepcopy(definition)}
    return {**registry, "algorithms": resolved}


def _safe_relative_path(value: Any, description: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{description} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ConfigError(f"{description} must be a safe relative path")
    return path


def _resolve_child(root: Path, value: Any, description: str) -> Path:
    relative = _safe_relative_path(value, description)
    target = (root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigError(f"{description} escapes {root}") from exc
    return target


def load_dataset_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    registry = _read_json(registry_path, "dataset registry")
    if registry.get("schema_version") != 1 or not isinstance(registry.get("datasets"), dict):
        raise ConfigError("dataset registry requires schema_version 1 and a datasets object")
    if not registry["datasets"]:
        raise ConfigError("dataset registry must contain at least one dataset")
    for name, entry in registry["datasets"].items():
        if not isinstance(name, str) or not DATASET_NAME_PATTERN.fullmatch(name):
            raise ConfigError(f"invalid dataset name: {name!r}")
        if not isinstance(entry, dict):
            raise ConfigError(f"datasets.{name} must be an object")
        unknown_keys = set(entry) - DATASET_ENTRY_KEYS
        if unknown_keys:
            raise ConfigError(
                f"datasets.{name} contains unsupported keys: {', '.join(sorted(unknown_keys))}"
            )
        config_path = _resolve_child(
            registry_path.parent, entry.get("config"), f"datasets.{name}.config"
        )
        if config_path.suffix != ".json":
            raise ConfigError(f"datasets.{name}.config must name a JSON file")
        adapter = entry.get("adapter")
        if adapter not in SUPPORTED_DATASET_ADAPTERS:
            allowed = ", ".join(sorted(SUPPORTED_DATASET_ADAPTERS))
            raise ConfigError(f"datasets.{name}.adapter must be one of: {allowed}")
        if "watch" in entry and not isinstance(entry["watch"], bool):
            raise ConfigError(f"datasets.{name}.watch must be a boolean")
        update_adapter = entry.get("update_adapter", adapter)
        if update_adapter not in SUPPORTED_DATASET_ADAPTERS:
            raise ConfigError(f"datasets.{name}.update_adapter is not supported")
    return registry


def load_registered_configs(path: str | Path) -> dict[str, dict[str, Any]]:
    registry_path = Path(path)
    registry = load_dataset_registry(registry_path)
    configs: dict[str, dict[str, Any]] = {}
    benchmark_ids: dict[str, str] = {}
    for name, entry in registry["datasets"].items():
        config_path = _resolve_child(
            registry_path.parent, entry["config"], f"datasets.{name}.config"
        )
        if not config_path.is_file() or config_path.is_symlink():
            raise ConfigError(f"datasets.{name}.config is not a regular file: {config_path}")
        config = load_config(config_path)
        benchmark_id = config["benchmark"].get("id")
        if not isinstance(benchmark_id, str) or not benchmark_id:
            raise ConfigError(f"datasets.{name} benchmark.id must be non-empty")
        if previous := benchmark_ids.get(benchmark_id):
            raise ConfigError(
                f"datasets {previous} and {name} use duplicate benchmark.id {benchmark_id!r}"
            )
        benchmark_ids[benchmark_id] = name
        configs[name] = config
    return configs


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    config = _read_json(config_path, "benchmark config")
    registry_name = config.get("algorithm_registry")
    if registry_name:
        if registry_name != "algorithms.json":
            raise ConfigError("algorithm_registry must be algorithms.json")
        registry_path = _resolve_child(
            config_path.parent, registry_name, "algorithm_registry"
        )
        registry = load_algorithm_registry(registry_path)
        algorithms = registry["algorithms"]
        overrides = config.get("algorithm_overrides", {})
        unknown = set(overrides) - set(algorithms)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ConfigError(f"overrides reference unknown algorithms: {names}")
        for name, override in overrides.items():
            if not isinstance(override, dict):
                raise ConfigError(f"algorithm_overrides.{name} must be an object")
            unsupported = set(override) - ALGORITHM_OVERRIDE_KEYS
            if unsupported:
                raise ConfigError(
                    f"algorithm_overrides.{name} contains unsafe keys: "
                    f"{', '.join(sorted(unsupported))}"
                )
        config["algorithms"] = {
            name: {**definition, **deepcopy(overrides.get(name, {}))}
            for name, definition in algorithms.items()
        }
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    for section in ("benchmark", "dataset", "algorithms"):
        if not isinstance(config.get(section), dict):
            raise ConfigError(f"missing object: {section}")

    dataset = config["dataset"]
    unknown_dataset_keys = set(dataset) - DATASET_CONFIG_KEYS
    if unknown_dataset_keys:
        raise ConfigError(
            f"dataset contains unsupported keys: {', '.join(sorted(unknown_dataset_keys))}"
        )
    for key in ("repo_id", "revision", "manifest_sha256", "manifests", "expected_cases"):
        if key not in dataset:
            raise ConfigError(f"dataset.{key} is required")
    if dataset.get("repo_type", "dataset") != "dataset":
        raise ConfigError("dataset.repo_type must be dataset")
    if not isinstance(dataset["repo_id"], str) or not HF_REPO_PATTERN.fullmatch(
        dataset["repo_id"]
    ):
        raise ConfigError("dataset.repo_id must be a Hugging Face owner/name")
    revision = dataset["revision"]
    if not isinstance(revision, str) or (
        not SHA_PATTERN.fullmatch(revision)
        and (dataset["repo_id"], revision) not in LEGACY_DATASET_REVISIONS
    ):
        raise ConfigError("dataset.revision must be an immutable 40-character commit SHA")
    digest = dataset["manifest_sha256"]
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        raise ConfigError("dataset.manifest_sha256 must be a lowercase SHA256 digest")
    if not isinstance(dataset["manifests"], dict) or not isinstance(
        dataset["expected_cases"], dict
    ):
        raise ConfigError("dataset.manifests and dataset.expected_cases must be objects")
    for split in ("all", "train", "test"):
        if split not in dataset["manifests"]:
            raise ConfigError(f"dataset.manifests.{split} is required")
        _safe_relative_path(dataset["manifests"][split], f"dataset.manifests.{split}")
        if int(dataset["expected_cases"].get(split, 0)) <= 0:
            raise ConfigError(f"dataset.expected_cases.{split} must be positive")
    expected = {name: int(dataset["expected_cases"][name]) for name in ("all", "train", "test")}
    if expected["all"] != expected["train"] + expected["test"]:
        raise ConfigError("dataset train and test counts must add up to all")
    _safe_relative_path(dataset.get("data_dir", "."), "dataset.data_dir")
    allow_patterns = dataset.get("allow_patterns")
    if allow_patterns is not None and (
        not isinstance(allow_patterns, list)
        or not allow_patterns
        or not all(isinstance(pattern, str) and pattern for pattern in allow_patterns)
    ):
        raise ConfigError("dataset.allow_patterns must be a non-empty string list")
    download_workers = int(dataset.get("download_workers", 8))
    if not 1 <= download_workers <= 64:
        raise ConfigError("dataset.download_workers must be between 1 and 64")
    pinned = dataset.get("pinned_split_manifests")
    if pinned is not None:
        if not isinstance(pinned, dict) or set(pinned) != {"train", "test"}:
            raise ConfigError("dataset.pinned_split_manifests requires train and test")
        for split, path in pinned.items():
            _safe_relative_path(path, f"dataset.pinned_split_manifests.{split}")

    algorithms = config["algorithms"]
    if not algorithms:
        raise ConfigError("algorithms must not be empty")
    for name, algorithm in algorithms.items():
        for key in ("display_name", "source", "commit", "image", "scope", "python"):
            if not algorithm.get(key):
                raise ConfigError(f"algorithms.{name}.{key} is required")
        if algorithm["scope"] not in dataset["manifests"]:
            raise ConfigError(f"algorithms.{name}.scope is not a configured manifest")
        workers = int(algorithm.get("workers", 0))
        if not 1 <= workers <= 64:
            raise ConfigError(f"algorithms.{name}.workers must be between 1 and 64")
        max_errors = int(algorithm.get("max_algorithm_errors", 0))
        scope_cases = int(dataset["expected_cases"][algorithm["scope"]])
        if not 0 <= max_errors <= scope_cases:
            raise ConfigError(
                f"algorithms.{name}.max_algorithm_errors must be between 0 and {scope_cases}"
            )
        if not isinstance(algorithm.get("environment", {}), dict):
            raise ConfigError(f"algorithms.{name}.environment must be an object")


def dataset_path(config: dict[str, Any], snapshot: str | Path) -> Path:
    return Path(snapshot) / config["dataset"].get("data_dir", ".")


def manifest_path(config: dict[str, Any], snapshot: str | Path, split: str) -> Path:
    try:
        relative = config["dataset"]["manifests"][split]
    except KeyError as exc:
        raise ConfigError(f"unknown dataset split: {split}") from exc
    return Path(snapshot) / relative


def read_manifest(path: str | Path) -> list[str]:
    cases = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    if len(cases) != len(set(cases)):
        raise ConfigError(f"manifest contains duplicate cases: {path}")
    return cases
