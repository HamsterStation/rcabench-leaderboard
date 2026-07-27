import json
from pathlib import Path

import pytest

from rcabench_leaderboard.config import ConfigError, load_config

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
    assert config["algorithms"]["microhecl"]["image"] == config["algorithms"]["shapleyiq"]["image"]


def test_ops_lite_config_is_valid():
    config = load_config(ROOT / "config/ops-lite.json")
    assert config["dataset"]["revision"] == "9ac09981c08ab02a0b923eab7830d778934851a8"
    assert config["dataset"]["expected_cases"] == {"all": 500, "train": 400, "test": 100}


def test_unknown_algorithm_override_is_rejected(tmp_path):
    config = json.loads((ROOT / "config/benchmark.json").read_text())
    config["algorithm_registry"] = str(ROOT / "config/algorithms.json")
    config["algorithm_overrides"]["missing"] = {"workers": 1}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ConfigError, match="unknown algorithms"):
        load_config(path)
