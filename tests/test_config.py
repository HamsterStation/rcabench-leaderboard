import json
import shutil
from pathlib import Path

import pytest

from rcabench_leaderboard.config import (
    ConfigError,
    load_config,
    load_dataset_registry,
    load_registered_configs,
)

ROOT = Path(__file__).parents[1]


def test_repository_config_is_valid():
    config = load_config(ROOT / "config/benchmark.json")
    assert set(config["algorithms"]) == {
        "baro",
        "art",
        "eadro",
        "causalrca",
        "diagfusion",
        "microdig",
        "microhecl",
        "microrank",
        "microrca",
        "nezha",
        "shapleyiq",
        "simplerca",
    }
    assert config["dataset"]["expected_cases"]["all"] == 1422
    assert config["algorithms"]["microhecl"]["image"] != config["algorithms"]["shapleyiq"]["image"]
    assert config["algorithms"]["microhecl"]["image"].endswith("microhecl:ceac113d-r1")
    assert config["algorithms"]["microrank"]["image"] != config["algorithms"]["shapleyiq"]["image"]
    assert config["algorithms"]["microrank"]["image"].endswith("microrank:ceac113d-r1")
    assert config["algorithms"]["microrca"]["image"] != config["algorithms"]["shapleyiq"]["image"]
    assert config["algorithms"]["microrca"]["image"].endswith("microrca:ceac113d-r1")
    assert config["algorithms"]["nezha"]["image"].endswith("nezha:89907e09-r1")
    assert config["algorithms"]["shapleyiq"]["image"].endswith("shapleyiq:ceac113d-r1")
    assert config["algorithms"]["diagfusion"]["image"].endswith("diagfusion:04e91716-r1")
    assert config["algorithms"]["baro"]["image"].endswith("baro:0a18961e-r1")
    assert config["algorithms"]["art"]["image"].endswith("art:e67094a3-r1")
    assert config["algorithms"]["eadro"]["image"].endswith("eadro:d8df6d29-r1")
    assert config["algorithms"]["eadro"]["preparation_commit"] == (
        "0e6f4254900df7215a4a21b9fcc4b721f357a3ab"
    )


def test_ops_lite_config_is_valid():
    config = load_config(ROOT / "config/ops-lite.json")
    assert config["dataset"]["revision"] == "9ac09981c08ab02a0b923eab7830d778934851a8"
    assert config["dataset"]["expected_cases"] == {"all": 500, "train": 400, "test": 100}


def test_unknown_algorithm_override_is_rejected(tmp_path):
    config = json.loads((ROOT / "config/benchmark.json").read_text())
    shutil.copy(ROOT / "config/algorithms.json", tmp_path / "algorithms.json")
    config["algorithm_overrides"]["missing"] = {"workers": 1}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ConfigError, match="unknown algorithms"):
        load_config(path)


def test_dataset_registry_rejects_path_traversal_and_unknown_adapter(tmp_path):
    registry = tmp_path / "datasets.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "datasets": {
                    "unsafe": {"config": "../outside.json", "adapter": "native"}
                },
            }
        )
    )
    with pytest.raises(ConfigError, match="safe relative path"):
        load_dataset_registry(registry)

    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "datasets": {"unsafe": {"config": "data.json", "adapter": "shell"}},
            }
        )
    )
    with pytest.raises(ConfigError, match="adapter must be one of"):
        load_dataset_registry(registry)


def test_new_dataset_revision_must_be_an_immutable_commit(tmp_path):
    config = json.loads((ROOT / "config/ops-lite.json").read_text())
    shutil.copy(ROOT / "config/algorithms.json", tmp_path / "algorithms.json")
    config["dataset"]["revision"] = "main"
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ConfigError, match="40-character commit SHA"):
        load_config(path)


def test_registered_benchmark_ids_must_be_unique(tmp_path):
    shutil.copy(ROOT / "config/algorithms.json", tmp_path / "algorithms.json")
    config = json.loads((ROOT / "config/ops-lite.json").read_text())
    (tmp_path / "one.json").write_text(json.dumps(config))
    (tmp_path / "two.json").write_text(json.dumps(config))
    (tmp_path / "datasets.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "datasets": {
                    "one": {"config": "one.json", "adapter": "ops-lite"},
                    "two": {"config": "two.json", "adapter": "ops-lite"},
                },
            }
        )
    )
    with pytest.raises(ConfigError, match="duplicate benchmark.id"):
        load_registered_configs(tmp_path / "datasets.json")
