#!/usr/bin/env python3
"""Finish ART ground-truth export after the upstream indexing failure."""

import pickle
from pathlib import Path

from src.preprocess import build_groundtruth

data_root = Path("/dataset")
output = Path("/art-data/RCABENCH")
test_cases = list((data_root / "__dev__rcabench_test_r1").iterdir())

with (output / "samples/test_samples.pkl").open("rb") as handle:
    test_samples = pickle.load(handle)
with (output / "samples/train_samples.pkl").open("rb") as handle:
    train_samples = pickle.load(handle)

ground_truth = build_groundtruth(test_cases)
sample_timestamps = {item[0].item() for item in test_samples}
filtered = ground_truth[ground_truth.iloc[:, 0].isin(sample_timestamps)]
filtered.to_csv(output / "cases.csv", index=False)

print(
    f"train_samples={len(train_samples)} test_samples={len(test_samples)} "
    f"ground_truth_rows={len(filtered)}"
)

