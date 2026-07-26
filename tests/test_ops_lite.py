import json

from rcabench_leaderboard.ops_lite import _merge_ground_truth, iterative_train_test_split


def test_ground_truth_list_is_merged_without_duplicates():
    assert _merge_ground_truth(
        [
            {"service": ["profile"], "container": ["profile-0"]},
            {"service": ["geo", "profile"], "container": ["geo-0"]},
        ]
    ) == {
        "service": ["profile", "geo"],
        "container": ["profile-0", "geo-0"],
    }


def test_multilabel_split_is_deterministic_and_complete():
    records = [
        {
            "name": f"case-{index}",
            "system": "ts" if index < 8 else "hs",
            "primary_kind": "PodFailure" if index % 2 else "NetworkDelay",
            "root_services": [f"svc-{index % 3}"],
        }
        for index in range(10)
    ]
    first = iterative_train_test_split(records, test_size=2, seed=42)
    second = iterative_train_test_split(json.loads(json.dumps(records)), test_size=2, seed=42)
    assert first == second
    train, test = first
    assert len(train) == 8
    assert len(test) == 2
    assert set(train).isdisjoint(test)
    assert set(train) | set(test) == {record["name"] for record in records}
