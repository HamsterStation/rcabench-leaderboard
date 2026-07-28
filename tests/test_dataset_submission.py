import hashlib
import json

import pytest

from rcabench_leaderboard.submission import (
    _validate_native,
    parse_manifest,
    validate_injection,
    validate_partition,
)


def test_manifest_partition_requires_disjoint_complete_splits():
    manifests = {
        "all": ["a", "b", "c"],
        "train": ["a", "b"],
        "test": ["b"],
    }
    with pytest.raises(ValueError, match="overlap"):
        validate_partition(manifests, {"all": 3, "train": 2, "test": 1})

    manifests["test"] = ["c"]
    assert validate_partition(manifests, {"all": 3, "train": 2, "test": 1}) == {
        "all": 3,
        "train": 2,
        "test": 1,
    }


def test_manifest_and_injection_reject_unsafe_or_missing_labels():
    with pytest.raises(ValueError, match="unsafe case"):
        parse_manifest(b"../secret\n", "all")
    with pytest.raises(ValueError, match="ground_truth.service"):
        validate_injection(json.dumps({"ground_truth": {"service": []}}).encode(), "case")
    validate_injection(
        json.dumps({"ground_truth": [{"service": "frontend"}, {"service": ["db"]}]}).encode(),
        "case",
    )


def test_native_submission_checks_digest_partition_and_sample_ground_truth():
    all_manifest = b"case-a\ncase-b\n"
    digest = hashlib.sha256(all_manifest).hexdigest()
    files = {
        "manifests/all.txt": all_manifest,
        "manifests/train.txt": b"case-a\n",
        "manifests/test.txt": b"case-b\n",
        "manifests/summary.json": json.dumps(
            {"manifest_sha256": digest, "total": 2, "train": 1, "test": 1}
        ).encode(),
        "case-a/converted/injection.json": b'{"ground_truth":{"service":"a"}}',
        "case-b/converted/injection.json": b'{"ground_truth":{"service":"b"}}',
    }
    config = {
        "dataset": {
            "repo_id": "example/native",
            "revision": "a" * 40,
            "manifest_sha256": digest,
            "data_dir": ".",
            "manifests": {
                "all": "manifests/all.txt",
                "train": "manifests/train.txt",
                "test": "manifests/test.txt",
            },
            "expected_cases": {"all": 2, "train": 1, "test": 1},
        }
    }
    report = _validate_native(config, files.__getitem__, sample_size=2)
    assert report["manifest_sha256"] == digest
    assert report["sampled_cases"] == ["case-a", "case-b"]
