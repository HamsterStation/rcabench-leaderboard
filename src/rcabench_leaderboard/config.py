from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


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


def load_dataset_registry(path: str | Path) -> dict[str, Any]:
    registry = _read_json(Path(path), "dataset registry")
    if registry.get("schema_version") != 1 or not isinstance(registry.get("datasets"), dict):
        raise ConfigError("dataset registry requires schema_version 1 and a datasets object")
    return registry


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    config = _read_json(config_path, "benchmark config")
    registry_name = config.get("algorithm_registry")
    if registry_name:
        registry = load_algorithm_registry(config_path.parent / registry_name)
        algorithms = registry["algorithms"]
        overrides = config.get("algorithm_overrides", {})
        unknown = set(overrides) - set(algorithms)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ConfigError(f"overrides reference unknown algorithms: {names}")
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
    for key in ("repo_id", "revision", "manifests", "expected_cases"):
        if key not in dataset:
            raise ConfigError(f"dataset.{key} is required")
    for split in ("all", "train", "test"):
        if split not in dataset["manifests"]:
            raise ConfigError(f"dataset.manifests.{split} is required")
        if int(dataset["expected_cases"].get(split, 0)) <= 0:
            raise ConfigError(f"dataset.expected_cases.{split} must be positive")

    algorithms = config["algorithms"]
    if not algorithms:
        raise ConfigError("algorithms must not be empty")
    for name, algorithm in algorithms.items():
        for key in ("display_name", "source", "commit", "image", "scope", "python"):
            if not algorithm.get(key):
                raise ConfigError(f"algorithms.{name}.{key} is required")
        if algorithm["scope"] not in dataset["manifests"]:
            raise ConfigError(f"algorithms.{name}.scope is not a configured manifest")
        if int(algorithm.get("workers", 0)) <= 0:
            raise ConfigError(f"algorithms.{name}.workers must be positive")
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
