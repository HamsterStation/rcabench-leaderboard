from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_algorithm_registry, load_config, load_dataset_registry


def _selection(value: str, available: set[str], description: str) -> set[str]:
    if value.strip().lower() == "all":
        return available
    selected = {item.strip() for item in value.split(",") if item.strip()}
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown {description}: {', '.join(sorted(unknown))}")
    if not selected:
        raise ValueError(f"at least one {description} must be selected")
    return selected


def benchmark_matrix(
    registry_path: str | Path, *, benchmarks: str = "all", algorithms: str = "all"
) -> list[dict[str, Any]]:
    path = Path(registry_path)
    datasets = load_dataset_registry(path)["datasets"]
    selected_benchmarks = _selection(benchmarks, set(datasets), "benchmark")
    loaded = {
        name: load_config(path.parent / datasets[name]["config"])
        for name in sorted(selected_benchmarks)
    }
    available_algorithms = set.intersection(
        *(set(config["algorithms"]) for config in loaded.values())
    )
    selected_algorithms = _selection(algorithms, available_algorithms, "algorithm")
    ordered_algorithms = sorted(
        selected_algorithms,
        key=lambda item: (
            min(
                int(config["algorithms"][item].get("schedule_priority", 100))
                for config in loaded.values()
            ),
            item,
        ),
    )
    return [
        {
            "benchmark": benchmark,
            "config": (path.parent / datasets[benchmark]["config"]).as_posix(),
            "adapter": datasets[benchmark]["adapter"],
            "algorithm": algorithm,
            "prepare": bool(config["algorithms"][algorithm].get("preparation")),
        }
        for algorithm in ordered_algorithms
        for benchmark, config in loaded.items()
    ]


def image_matrix(registry_path: str | Path) -> list[dict[str, str]]:
    registry = load_algorithm_registry(registry_path)
    return [
        {
            "name": name,
            "source": image["source"],
            "commit": image["commit"],
            "tag": image["commit"][:8],
            "image": image["image"],
        }
        for name, image in sorted(registry["images"].items())
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    benchmarks = subparsers.add_parser("benchmarks")
    benchmarks.add_argument("--registry", type=Path, default=Path("config/datasets.json"))
    benchmarks.add_argument("--benchmarks", default="all")
    benchmarks.add_argument("--algorithms", default="all")
    images = subparsers.add_parser("images")
    images.add_argument("--registry", type=Path, default=Path("config/algorithms.json"))
    args = parser.parse_args()
    if args.command == "benchmarks":
        value = benchmark_matrix(
            args.registry, benchmarks=args.benchmarks, algorithms=args.algorithms
        )
    else:
        value = image_matrix(args.registry)
    print(json.dumps(value, separators=(",", ":")))


if __name__ == "__main__":
    main()
