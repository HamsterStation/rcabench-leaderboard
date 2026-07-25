import json

import pytest

from rcabench_leaderboard.evaluation import evaluate


def write_case(root, case, truth):
    converted = root / case / "converted"
    converted.mkdir(parents=True)
    (converted / "injection.json").write_text(
        json.dumps({"ground_truth": {"service": truth}})
    )


def write_result(root, case, names, status="ok"):
    folder = root / case
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(
        json.dumps(
            {
                "status": status,
                "duration_seconds": 2,
                "answers": [
                    {"level": "service", "name": name, "rank": index + 1}
                    for index, name in enumerate(names)
                ],
            }
        )
    )


def test_missing_cases_stay_in_denominator_and_services_are_deduplicated(tmp_path):
    data = tmp_path / "data"
    results = tmp_path / "results"
    write_case(data, "case-a", ["target"])
    write_case(data, "case-b", ["target"])
    write_result(results, "case-a", ["other", "other", "target"])

    metrics = evaluate(
        cases=["case-a", "case-b"],
        data_root=data,
        results_root=results,
        deduplicate_services=True,
    )

    assert metrics["top@1"] == 0
    assert metrics["top@3"] == pytest.approx(0.5)
    assert metrics["mrr"] == pytest.approx(0.25)
    assert metrics["missing_cases"] == 1
    assert metrics["duplicate_ranking_cases"] == 1


def test_algorithm_error_is_a_valid_miss(tmp_path):
    data = tmp_path / "data"
    results = tmp_path / "results"
    write_case(data, "case-a", ["target"])
    write_result(results, "case-a", [], status="algorithm_error")
    metrics = evaluate(cases=["case-a"], data_root=data, results_root=results)
    assert metrics["successful_result_files"] == 1
    assert metrics["algorithm_error_cases"] == 1
    assert metrics["mrr"] == 0

