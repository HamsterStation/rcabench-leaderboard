#!/usr/bin/env python3
"""Execute one upstream RCABench adapter and serialize its ranked answers."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import time
import traceback
from pathlib import Path

from rcabench_platform.v2.algorithms.spec import AlgorithmArgs

ALGORITHMS = {
    "baro": ("baro.baro", "Baro"),
    "causalrca": ("rcaeval_causalrca.causalrca", "CausalRCA"),
    "art": ("main", "ART"),
    "eadro": ("main", "Eadro"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("algorithm", choices=sorted(ALGORITHMS))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--datapack", required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    module_name, class_name = ALGORITHMS[args.algorithm]
    algorithm_class = getattr(importlib.import_module(module_name), class_name)
    started = time.perf_counter()
    try:
        answers = algorithm_class()(
            AlgorithmArgs(
                dataset="rcabench",
                datapack=args.datapack,
                input_folder=args.input,
                output_folder=args.output,
            )
        )
        status = "ok"
        error = None
    except Exception as exc:  # A per-case algorithm error is an auditable miss, not a lost batch.
        answers = []
        status = "algorithm_error"
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=20),
        }
    result = {
        "schema_version": 1,
        "algorithm": args.algorithm,
        "datapack": args.datapack,
        "duration_seconds": time.perf_counter() - started,
        "checkpoint_path": os.getenv("CHECKPOINT_PATH"),
        "status": status,
        "error": error,
        "answers": [
            {"level": answer.level, "name": answer.name, "rank": answer.rank}
            for answer in answers
        ],
    }
    temporary = args.output / "result.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.output / "result.json")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
