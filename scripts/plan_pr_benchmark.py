#!/usr/bin/env python3
"""Plan only the algorithm/dataset pairs affected by a pull request."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from rcabench_leaderboard.config import load_config, load_dataset_registry
from rcabench_leaderboard.matrix import image_matrix


def _base_json(base: str, path: Path) -> dict[str, Any]:
    process = subprocess.run(
        ["git", "show", f"{base}:{path.as_posix()}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode:
        return {}
    return json.loads(process.stdout)


def _changed(base: str, path: Path) -> bool:
    return (
        subprocess.run(
            ["git", "diff", "--quiet", base, "--", path.as_posix()], check=False
        ).returncode
        != 0
    )


def _build_definition(definition: dict[str, Any] | None) -> tuple[Any, ...]:
    if definition is None:
        return ()
    return tuple(definition.get(key) for key in ("source", "commit", "image"))


def plan(base: str, root: Path) -> dict[str, Any]:
    algorithm_path = root / "config/algorithms.json"
    dataset_path = root / "config/datasets.json"
    current_raw = json.loads(algorithm_path.read_text())
    base_raw = _base_json(base, algorithm_path.relative_to(root))

    current_images = current_raw.get("images", {})
    base_images = base_raw.get("images", {})
    changed_images = {
        name
        for name, definition in current_images.items()
        if _build_definition(definition) != _build_definition(base_images.get(name))
    }
    current_algorithms = current_raw.get("algorithms", {})
    base_algorithms = base_raw.get("algorithms", {})
    changed_algorithms = {
        name
        for name, definition in current_algorithms.items()
        if definition != base_algorithms.get(name) or definition.get("image_ref") in changed_images
    }

    datasets = load_dataset_registry(dataset_path)["datasets"]
    base_datasets = _base_json(base, dataset_path.relative_to(root)).get("datasets", {})
    changed_datasets = {
        name
        for name, entry in datasets.items()
        if entry != base_datasets.get(name)
        or _changed(base, (dataset_path.parent / entry["config"]).relative_to(root))
    }

    configs = {
        name: load_config(dataset_path.parent / entry["config"]) for name, entry in datasets.items()
    }
    pairs = {(benchmark, algorithm) for algorithm in changed_algorithms for benchmark in datasets}
    pairs.update(
        (benchmark, algorithm)
        for benchmark in changed_datasets
        for algorithm in configs[benchmark]["algorithms"]
    )
    ordered = sorted(
        pairs,
        key=lambda pair: (
            int(configs[pair[0]]["algorithms"][pair[1]].get("schedule_priority", 100)),
            pair[1],
            pair[0],
        ),
    )
    matrix = [
        {
            "benchmark": benchmark,
            "config": (dataset_path.parent / datasets[benchmark]["config"])
            .relative_to(root)
            .as_posix(),
            "algorithm": algorithm,
            "prepare": bool(configs[benchmark]["algorithms"][algorithm].get("preparation")),
        }
        for benchmark, algorithm in ordered
    ]
    images = [row for row in image_matrix(algorithm_path) if row["name"] in changed_images]
    return {
        "matrix": matrix,
        "images": images,
        "changed_algorithms": sorted(changed_algorithms),
        "changed_datasets": sorted(changed_datasets),
        "has_work": bool(matrix),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(plan(args.base, args.root.resolve()), separators=(",", ":")))


if __name__ == "__main__":
    main()
