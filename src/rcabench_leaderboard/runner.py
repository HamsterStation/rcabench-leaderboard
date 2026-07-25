from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CaseResult:
    case: str
    status: str
    duration_seconds: float


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _require_asset(path: Path, description: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"missing {description}: {path}")
    return path.resolve()


def build_docker_command(
    *,
    name: str,
    algorithm: dict[str, Any],
    data_root: Path,
    case: str,
    case_output: Path,
    container_runner: Path,
    assets: Path | None,
) -> list[str]:
    converted = (data_root / case / "converted").resolve()
    if not converted.is_dir():
        raise FileNotFoundError(f"case has no converted input: {converted}")

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        str(algorithm.get("cpus_per_worker", 1)),
        "--entrypoint",
        algorithm["python"],
        "--workdir",
        algorithm.get("workdir", "/app"),
        "--env",
        "PYTHONPATH=/app",
        "--env",
        f"OMP_NUM_THREADS={max(1, int(algorithm.get('cpus_per_worker', 1)))}",
        "--env",
        f"MKL_NUM_THREADS={max(1, int(algorithm.get('cpus_per_worker', 1)))}",
        "--env",
        f"OPENBLAS_NUM_THREADS={max(1, int(algorithm.get('cpus_per_worker', 1)))}",
        "--volume",
        f"{converted}:/input:ro",
        "--volume",
        f"{case_output.resolve()}:/output",
        "--volume",
        f"{container_runner.resolve()}:/benchmark_runner.py:ro",
    ]

    if name == "art":
        if assets is None:
            raise ValueError("ART requires --assets")
        model = _require_asset(assets / "model.pkl", "ART model")
        nodes = _require_asset(assets / "node_dict.pkl", "ART node dictionary")
        metrics = _require_asset(assets / "metric_dict.pkl", "ART metric dictionary")
        command.extend(
            [
                "--volume",
                f"{model}:/model.pkl:ro",
                "--volume",
                f"{nodes}:/data/RCABENCH/node_dict.pkl:ro",
                "--volume",
                f"{metrics}:/data/RCABENCH/metric_dict.pkl:ro",
            ]
        )
    elif name == "eadro":
        if assets is None:
            raise ValueError("Eadro requires --assets")
        checkpoint = _require_asset(assets / "best_model.ckpt", "Eadro checkpoint")
        metadata = _require_asset(assets / "metadata.pkl", "Eadro metadata")
        command.extend(
            [
                "--env",
                "CHECKPOINT_PATH=/checkpoint.ckpt",
                "--volume",
                f"{checkpoint}:/checkpoint.ckpt:ro",
                "--volume",
                f"{metadata}:/mnt/jfs/experiment_storage/eadro/metadata/rcabench_metadata.pkl:ro",
            ]
        )

    command.extend(
        [
            algorithm["image"],
            "/benchmark_runner.py",
            name,
            "--input",
            "/input",
            "--output",
            "/output",
            "--datapack",
            case,
        ]
    )
    return command


def run_benchmark(
    *,
    config: dict[str, Any],
    algorithm_name: str,
    cases: list[str],
    data_root: str | Path,
    output_root: str | Path,
    container_runner: str | Path,
    assets: str | Path | None = None,
    workers: int | None = None,
) -> dict[str, Any]:
    if algorithm_name not in config["algorithms"]:
        raise ValueError(f"unknown algorithm: {algorithm_name}")
    algorithm = config["algorithms"][algorithm_name]
    data_path = Path(data_root).resolve()
    output_path = Path(output_root).resolve()
    runner_path = Path(container_runner).resolve()
    assets_path = Path(assets).resolve() if assets else None
    output_path.mkdir(parents=True, exist_ok=True)
    progress_path = output_path / "progress.json"
    worker_count = workers or int(algorithm["workers"])
    timeout = int(algorithm.get("timeout_seconds", 1800))

    existing = {case for case in cases if (output_path / case / "result.json").is_file()}
    pending = [case for case in cases if case not in existing]
    state: dict[str, Any] = {
        "schema_version": 1,
        "algorithm": algorithm_name,
        "total": len(cases),
        "completed": 0,
        "failed": 0,
        "skipped": len(existing),
        "processed": len(existing),
        "workers": worker_count,
        "status": "running",
        "updated_at_epoch": time.time(),
    }
    lock = threading.Lock()
    _write_json(progress_path, state)

    def run_case(case: str) -> CaseResult:
        case_output = output_path / case
        case_output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            command = build_docker_command(
                name=algorithm_name,
                algorithm=algorithm,
                data_root=data_path,
                case=case,
                case_output=case_output,
                container_runner=runner_path,
                assets=assets_path,
            )
            environment = os.environ.copy()
            with (case_output / "run.log").open("w") as log:
                process = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                    env=environment,
                )
            status = (
                "completed"
                if process.returncode == 0 and (case_output / "result.json").is_file()
                else "failed"
            )
        except subprocess.TimeoutExpired:
            status = "timeout"
        except Exception as exc:  # Preserve the batch and surface per-case setup failures.
            (case_output / "run.log").write_text(f"{type(exc).__name__}: {exc}\n")
            status = "failed"
        return CaseResult(case, status, time.monotonic() - started)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(run_case, case) for case in pending]
        for future in as_completed(futures):
            result = future.result()
            with lock:
                key = "completed" if result.status == "completed" else "failed"
                state[key] += 1
                state["processed"] += 1
                state.update(
                    {
                        "current_case": result.case,
                        "last_status": result.status,
                        "last_wall_seconds": result.duration_seconds,
                        "updated_at_epoch": time.time(),
                    }
                )
                _write_json(progress_path, state)

    state["status"] = "completed" if state["failed"] == 0 else "completed_with_failures"
    state["updated_at_epoch"] = time.time()
    _write_json(progress_path, state)
    return state
