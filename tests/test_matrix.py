from pathlib import Path

import pytest

from rcabench_leaderboard.matrix import benchmark_matrix, image_matrix

ROOT = Path(__file__).parents[1]


def test_benchmark_matrix_contains_twelve_algorithms_for_each_dataset():
    matrix = benchmark_matrix(ROOT / "config/datasets.json")
    assert len(matrix) == 24
    assert {row["benchmark"] for row in matrix} == {"fse", "ops-lite"}
    assert sum(row["prepare"] for row in matrix) == 4


def test_benchmark_matrix_filters_and_rejects_unknown_names():
    matrix = benchmark_matrix(
        ROOT / "config/datasets.json", benchmarks="ops-lite", algorithms="baro,microrca"
    )
    assert [(row["benchmark"], row["algorithm"]) for row in matrix] == [
        ("ops-lite", "baro"),
        ("ops-lite", "microrca"),
    ]
    with pytest.raises(ValueError, match="unknown algorithm"):
        benchmark_matrix(ROOT / "config/datasets.json", algorithms="missing")


def test_image_matrix_keeps_microhecl_independent_from_shapleyiq():
    matrix = image_matrix(ROOT / "config/algorithms.json")
    assert len(matrix) == 10
    assert [row["name"] for row in matrix].count("microhecl") == 1
    assert [row["name"] for row in matrix].count("shapleyiq") == 1
