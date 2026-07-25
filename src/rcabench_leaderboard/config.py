from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_ALGORITHMS = {"baro", "art", "eadro", "causalrca"}


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read benchmark config {config_path}: {exc}") from exc
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    for section in ("benchmark", "dataset", "algorithms"):
        if not isinstance(config.get(section), dict):
            raise ConfigError(f"missing object: {section}")

    dataset = config["dataset"]
    for key in ("repo_id", "revision", "manifests", "expected_cases"):
        if key not in dataset:
            raise ConfigError(f"dataset.{key} is required")
    for split in ("all", "train", "test"):
        if split not in dataset["manifests"]:
            raise ConfigError(f"dataset.manifests.{split} is required")
        if int(dataset["expected_cases"].get(split, 0)) <= 0:
            raise ConfigError(f"dataset.expected_cases.{split} must be positive")

    algorithms = config["algorithms"]
    missing = REQUIRED_ALGORITHMS - set(algorithms)
    if missing:
        raise ConfigError(f"missing required algorithms: {', '.join(sorted(missing))}")
    for name, algorithm in algorithms.items():
        for key in ("display_name", "source", "commit", "image", "scope", "python"):
            if not algorithm.get(key):
                raise ConfigError(f"algorithms.{name}.{key} is required")
        if algorithm["scope"] not in dataset["manifests"]:
            raise ConfigError(f"algorithms.{name}.scope is not a configured manifest")
        if int(algorithm.get("workers", 0)) <= 0:
            raise ConfigError(f"algorithms.{name}.workers must be positive")


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

