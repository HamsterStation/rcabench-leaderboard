from __future__ import annotations

import os
import pickle
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(command: list[str], log_path: Path, *, allow_failure: bool = False) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    if process.returncode and not allow_failure:
        raise RuntimeError(f"command failed ({process.returncode}); see {log_path}")
    return process.returncode


def _dataset_links(
    *,
    root: Path,
    train_cases: list[str],
    test_cases: list[str],
    train_name: str,
    test_name: str,
) -> None:
    for folder_name, cases in ((train_name, train_cases), (test_name, test_cases)):
        folder = root / folder_name
        if folder.exists() or folder.is_symlink():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        for case in cases:
            os.symlink(f"/benchmark-data/{case}/converted", folder / case)


def _docker_base(image: str, data_root: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--volume",
        f"{data_root.resolve()}:/benchmark-data:ro",
        image,
    ]


def prepare_art(
    *,
    algorithm: dict[str, Any],
    data_root: Path,
    train_cases: list[str],
    test_cases: list[str],
    cache_root: Path,
    repository_root: Path,
    cache_key: str,
) -> Path:
    state = cache_root / "training" / "art" / cache_key
    assets = cache_root / "assets" / "art" / cache_key
    if all((assets / name).is_file() for name in ("model.pkl", "node_dict.pkl", "metric_dict.pkl")):
        return assets

    links = state / "datasets"
    art_data = state / "art-data"
    model = state / "model"
    logs = state / "logs"
    for folder in (links, art_data / "RCABENCH" / "samples", model, logs, assets):
        folder.mkdir(parents=True, exist_ok=True)
    _dataset_links(
        root=links,
        train_cases=train_cases,
        test_cases=test_cases,
        train_name="__dev__rcabench_train_r1",
        test_name="__dev__rcabench_test_r1",
    )

    samples = art_data / "RCABENCH" / "samples"
    if not (state / ".preprocess-complete").exists():
        command = _docker_base(algorithm["image"], data_root)
        command[3:3] = [
            "--entrypoint",
            "/.venv/bin/python",
            "--volume",
            f"{links.resolve()}:/dataset:ro",
            "--volume",
            f"{art_data.resolve()}:/art-data",
        ]
        command.extend(
            [
                "/client.py",
                "preprocess",
                "--data-root",
                "/dataset",
                "--output-dir",
                "/art-data/RCABENCH",
                "--dataset-type",
                "RCABENCH_r1",
            ]
        )
        _run(command, logs / "preprocess.log", allow_failure=True)
        if not (samples / "train_samples.pkl").is_file() or not (
            samples / "test_samples.pkl"
        ).is_file():
            raise RuntimeError(
                f"ART preprocessing did not produce samples; see {logs / 'preprocess.log'}"
            )

        command = _docker_base(algorithm["image"], data_root)
        command[3:3] = [
            "--entrypoint",
            "/.venv/bin/python",
            "--env",
            "PYTHONPATH=/",
            "--volume",
            f"{links.resolve()}:/dataset:ro",
            "--volume",
            f"{art_data.resolve()}:/art-data",
            "--volume",
            str((repository_root / "containers/finalize_art_preprocess.py").resolve())
            + ":/finalize.py:ro",
        ]
        command.append("/finalize.py")
        _run(command, logs / "finalize.log")
        (state / ".preprocess-complete").touch()

    node_dictionary = art_data / "RCABENCH" / "node_dict.pkl"
    with node_dictionary.open("rb") as handle:
        instance_dim = len(pickle.load(handle))
    config_template = (repository_root / "config/art-fse.yaml").read_text()
    generated_config = state / "art-fse.generated.yaml"
    generated_config.write_text(
        re.sub(
            r"(?m)^\s*instance_dim:\s*\d+\s*$",
            f"    instance_dim: {instance_dim}",
            config_template,
        )
    )

    if not (model / "model.pkl").is_file():
        command = _docker_base(algorithm["image"], data_root)
        command[3:3] = [
            "--entrypoint",
            "/.venv/bin/python",
            "--volume",
            f"{art_data.resolve()}:/data",
            "--volume",
            f"{generated_config.resolve()}:/config/RCABENCH.yaml:ro",
            "--volume",
            f"{model.resolve()}:/results",
        ]
        command.extend(
            [
                "/client.py",
                "train",
                "--dataset",
                "RCABENCH",
                "--config-dir",
                "/config",
                "--output-dir",
                "/results",
            ]
        )
        _run(command, logs / "train.log")

    for source, target in (
        (model / "model.pkl", assets / "model.pkl"),
        (art_data / "RCABENCH" / "node_dict.pkl", assets / "node_dict.pkl"),
        (art_data / "RCABENCH" / "metric_dict.pkl", assets / "metric_dict.pkl"),
    ):
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target)
    return assets


def prepare_eadro(
    *,
    algorithm: dict[str, Any],
    data_root: Path,
    train_cases: list[str],
    test_cases: list[str],
    cache_root: Path,
    repository_root: Path,
    cache_key: str,
) -> Path:
    revision = algorithm["commit"][:12]
    train_name = f"__leaderboard_train_{revision}"
    test_name = f"__leaderboard_test_{revision}"
    state = cache_root / "training" / "eadro" / cache_key
    assets = cache_root / "assets" / "eadro" / cache_key
    if all((assets / name).is_file() for name in ("best_model.ckpt", "metadata.pkl")):
        return assets

    links = state / "datasets"
    eadro_cache = state / "cache"
    storage = state / "experiment_storage" / "eadro"
    logs = state / "logs"
    for folder in (links, eadro_cache, storage, logs, assets):
        folder.mkdir(parents=True, exist_ok=True)
    _dataset_links(
        root=links,
        train_cases=train_cases,
        test_cases=test_cases,
        train_name=train_name,
        test_name=test_name,
    )

    def preprocessing_command(folder: str) -> list[str]:
        command = _docker_base(algorithm["image"], data_root)
        command[3:3] = [
            "--entrypoint",
            ".venv/bin/python",
            "--env",
            "PYTHONPATH=/app",
            "--volume",
            f"{links.resolve()}:/app/data/rcabench-platform-v2/data:ro",
            "--volume",
            f"{eadro_cache.resolve()}:/app/.cache",
            "--volume",
            f"{storage.resolve()}:/mnt/jfs/experiment_storage/eadro",
        ]
        command.extend(
            [
                "client.py",
                "create-dataset",
                "--config",
                "settings.toml",
                "--workers",
                "4",
                "--dataset-folder",
                folder,
                "--label",
                "train",
            ]
        )
        return command

    if not (state / ".preprocess-complete").exists():
        _run(preprocessing_command(train_name), logs / "preprocess-train.log")
        _run(preprocessing_command(test_name), logs / "preprocess-test.log")
        pattern = f"rcabench_{test_name}_train_samples_batch_*.pkl"
        test_batches = list(eadro_cache.glob(pattern))
        if not test_batches:
            raise RuntimeError(f"Eadro produced no test cache matching {pattern}")
        for source in test_batches:
            target = Path(str(source).replace("_train_samples_batch_", "_test_samples_batch_"))
            source.replace(target)
        (state / ".preprocess-complete").touch()

    checkpoints = list((storage / "checkpoints").rglob("best_model.ckpt"))
    if not checkpoints:
        command = _docker_base(algorithm["image"], data_root)
        command[3:3] = [
            "--entrypoint",
            ".venv/bin/python",
            "--env",
            "PYTHONPATH=/app",
            "--volume",
            f"{links.resolve()}:/app/data/rcabench-platform-v2/data:ro",
            "--volume",
            f"{eadro_cache.resolve()}:/app/.cache",
            "--volume",
            f"{storage.resolve()}:/mnt/jfs/experiment_storage/eadro",
            "--volume",
            str((repository_root / "containers/train_eadro_memory_efficient.py").resolve())
            + ":/train_eadro.py:ro",
        ]
        command.extend(
            [
                "/train_eadro.py",
                "--dataset-folder",
                train_name,
                "--test-dataset-folder",
                test_name,
                "--experiment-name",
                f"leaderboard_{revision}",
            ]
        )
        _run(command, logs / "train.log")
        checkpoints = list((storage / "checkpoints").rglob("best_model.ckpt"))

    metadata = storage / "metadata" / "rcabench_metadata.pkl"
    if not checkpoints or not metadata.is_file():
        raise RuntimeError(f"Eadro training assets are incomplete; see {logs}")
    checkpoint = max(checkpoints, key=lambda path: path.stat().st_mtime)
    shutil.copy2(checkpoint, assets / "best_model.ckpt")
    shutil.copy2(metadata, assets / "metadata.pkl")
    return assets


def prepare_assets(
    *,
    config: dict[str, Any],
    algorithm_name: str,
    data_root: str | Path,
    train_cases: list[str],
    test_cases: list[str],
    cache_root: str | Path,
    repository_root: str | Path,
) -> Path | None:
    if algorithm_name not in {"art", "eadro"}:
        return None
    function = prepare_art if algorithm_name == "art" else prepare_eadro
    dataset_revision = config["dataset"]["revision"]
    safe_revision = re.sub(r"[^A-Za-z0-9_.-]+", "-", dataset_revision)
    cache_key = f"{safe_revision}-{config['algorithms'][algorithm_name]['commit'][:12]}"
    return function(
        algorithm=config["algorithms"][algorithm_name],
        data_root=Path(data_root),
        train_cases=train_cases,
        test_cases=test_cases,
        cache_root=Path(cache_root),
        repository_root=Path(repository_root),
        cache_key=cache_key,
    )
