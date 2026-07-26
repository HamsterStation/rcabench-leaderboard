#!/usr/bin/env python3
"""Run ART preprocessing with consistent service-name extraction."""

from pathlib import Path

import pandas as pd

from src import preprocess


def collect_services_and_metrics(
    case_dirs: list[Path], metric_file_name: str
) -> tuple[list[str], list[str]]:
    """Build ART dictionaries with the same fallback used during preprocessing."""
    services: set[str] = set()
    metrics: set[str] = set()
    for case_dir in case_dirs:
        metric_path = case_dir / metric_file_name
        if not metric_path.exists():
            continue
        frame = pd.read_parquet(metric_path)
        metrics.update(str(value) for value in frame["metric"].dropna().unique())
        extracted = frame.apply(preprocess.DataPreprocessor.extract_service_name, axis=1)
        services.update(str(value) for value in extracted if pd.notna(value) and value != "")
    return sorted(services), sorted(metrics)


preprocess.collect_all_metrics_services = collect_services_and_metrics
preprocess.run_preprocess(
    data_root="/dataset",
    output_dir="/art-data/RCABENCH",
    ds="RCABENCH_r1",
)
