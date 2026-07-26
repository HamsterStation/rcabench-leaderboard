import json

import pytest

from rcabench_leaderboard.ops_lite import (
    _link_raw_files,
    _merge_ground_truth,
    _read_case_manifest,
    iterative_train_test_split,
)


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


def test_compatibility_view_uses_hardlinks_visible_in_case_mount(tmp_path):
    raw = tmp_path / "cases" / "case-a"
    converted = tmp_path / "case-a" / "converted"
    raw.mkdir(parents=True)
    converted.mkdir(parents=True)
    source = raw / "normal_metrics.parquet"
    source.write_bytes(b"parquet-placeholder")

    _link_raw_files(raw, converted)

    target = converted / source.name
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_ino == source.stat().st_ino


def test_pinned_manifest_is_sorted_and_rejects_duplicates(tmp_path):
    manifest = tmp_path / "split.txt"
    manifest.write_text("case-b\ncase-a\n")
    assert _read_case_manifest(manifest) == ["case-a", "case-b"]

    manifest.write_text("case-a\ncase-a\n")
    with pytest.raises(ValueError, match="duplicate"):
        _read_case_manifest(manifest)
