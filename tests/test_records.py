import json

from rcabench_leaderboard.records import record_metrics


def test_record_migrates_single_benchmark_file_and_adds_second_board(tmp_path):
    leaderboard = tmp_path / "leaderboard.json"
    leaderboard.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-01-01T00:00:00Z",
                "benchmark": {"id": "fse", "title": "FSE"},
                "entries": [{"algorithm": "baro", "metrics": {"mrr": 0.5}}],
                "paper_reference": {"metrics": {"baro": {"mrr": 0.6}}},
            }
        )
    )
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"requested_cases": 100, "mrr": 0.3}))
    config = {
        "benchmark": {"id": "ops-lite", "title": "OPS-Lite"},
        "dataset": {
            "revision": "sha",
            "expected_cases": {"all": 500, "train": 400, "test": 100},
        },
        "algorithms": {
            "baro": {
                "display_name": "BARO",
                "commit": "abc",
                "scope": "all",
            }
        },
    }

    record_metrics(
        leaderboard_path=leaderboard,
        metrics_path=metrics,
        config=config,
        algorithm_name="baro",
        run_id="test",
    )

    result = json.loads(leaderboard.read_text())
    assert result["schema_version"] == 2
    assert {board["benchmark"]["id"] for board in result["benchmarks"]} == {
        "fse",
        "ops-lite",
    }
    assert all("paper_reference" not in board for board in result["benchmarks"])
