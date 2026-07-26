import json
from pathlib import Path

import pytest

from rcabench_leaderboard.config import ConfigError, load_config

ROOT = Path(__file__).parents[1]


def test_repository_config_is_valid():
    config = load_config(ROOT / "config/benchmark.json")
    assert set(config["algorithms"]) == {"baro", "art", "eadro", "causalrca"}
    assert config["dataset"]["expected_cases"]["all"] == 1422


def test_ops_lite_config_is_valid():
    config = load_config(ROOT / "config/ops-lite.json")
    assert config["dataset"]["revision"] == "9ac09981c08ab02a0b923eab7830d778934851a8"
    assert config["dataset"]["expected_cases"] == {"all": 500, "train": 400, "test": 100}


def test_missing_algorithm_is_rejected(tmp_path):
    config = json.loads((ROOT / "config/benchmark.json").read_text())
    del config["algorithms"]["baro"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ConfigError, match="baro"):
        load_config(path)
