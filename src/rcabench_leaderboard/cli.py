from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import dataset_path, load_config, manifest_path, read_manifest
from .download import download_dataset
from .evaluation import evaluate, write_metrics
from .ops_lite import normalize_ops_lite
from .prepare import prepare_assets
from .records import build_site, record_metrics
from .runner import run_benchmark


def _common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=Path("config/benchmark.json"))


def _snapshot_cases(config, snapshot: Path, split: str, limit: int | None = None) -> list[str]:
    cases = read_manifest(manifest_path(config, snapshot, split))
    expected = int(config["dataset"]["expected_cases"][split])
    if len(cases) != expected:
        raise ValueError(f"{split} manifest has {len(cases)} cases; expected {expected}")
    return cases[:limit] if limit else cases


def command_validate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    print(
        json.dumps(
            {
                "status": "valid",
                "benchmark": config["benchmark"]["id"],
                "dataset": config["dataset"]["repo_id"],
                "algorithms": sorted(config["algorithms"]),
            },
            indent=2,
        )
    )


def command_doctor(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    checks = {
        "docker_cli": shutil.which("docker") is not None,
        "docker_daemon": False,
        "config": True,
        "hf_token": bool(__import__("os").getenv("HF_TOKEN")),
    }
    if checks["docker_cli"]:
        checks["docker_daemon"] = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    checks["algorithms"] = sorted(config["algorithms"])
    print(json.dumps(checks, indent=2))
    if not checks["docker_daemon"]:
        raise SystemExit(2)


def command_download(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    print(download_dataset(config, args.output))


def command_normalize_ops_lite(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    dataset = config["dataset"]
    pinned = dataset.get("pinned_split_manifests", {})
    config_root = args.config.resolve().parent
    metadata = normalize_ops_lite(
        args.snapshot,
        expected_manifest_sha256=dataset.get("manifest_sha256"),
        expected_cases=int(dataset["expected_cases"]["all"]),
        test_size=int(dataset["expected_cases"]["test"]),
        seed=int(dataset.get("split_seed", 42)),
        pinned_train_manifest=config_root / pinned["train"] if pinned else None,
        pinned_test_manifest=config_root / pinned["test"] if pinned else None,
    )
    print(json.dumps(metadata, indent=2))


def command_prepare(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    snapshot = args.snapshot.resolve()
    train_cases = _snapshot_cases(config, snapshot, "train")
    test_cases = _snapshot_cases(config, snapshot, "test")
    assets = prepare_assets(
        config=config,
        algorithm_name=args.algorithm,
        data_root=dataset_path(config, snapshot),
        train_cases=train_cases,
        test_cases=test_cases,
        cache_root=args.cache_root,
        repository_root=args.repository_root,
    )
    print(assets or "none")


def command_run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    algorithm = config["algorithms"][args.algorithm]
    snapshot = args.snapshot.resolve()
    split = args.split or algorithm["scope"]
    cases = _snapshot_cases(config, snapshot, split, args.limit)
    state = run_benchmark(
        config=config,
        algorithm_name=args.algorithm,
        cases=cases,
        data_root=dataset_path(config, snapshot),
        output_root=args.output,
        container_runner=args.container_runner,
        assets=args.assets,
        workers=args.workers,
    )
    print(json.dumps(state, indent=2))
    if state["failed"]:
        raise SystemExit(2)


def command_evaluate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    algorithm = config["algorithms"][args.algorithm]
    snapshot = args.snapshot.resolve()
    split = args.split or algorithm["scope"]
    cases = _snapshot_cases(config, snapshot, split, args.limit)
    deduplicate = config["benchmark"].get("deduplicate_services", True)
    if args.keep_duplicate_services:
        deduplicate = False
    metrics = evaluate(
        cases=cases,
        data_root=dataset_path(config, snapshot),
        results_root=args.results,
        deduplicate_services=deduplicate,
    )
    write_metrics(args.output, metrics)
    print(json.dumps(metrics, indent=2))
    max_algorithm_errors = int(algorithm.get("max_algorithm_errors", 0))
    incomplete = metrics["missing_cases"] or metrics["invalid_cases"]
    too_many_errors = metrics["algorithm_error_cases"] > max_algorithm_errors
    if args.require_complete and (incomplete or too_many_errors):
        raise SystemExit(2)


def command_record(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    entry = record_metrics(
        leaderboard_path=args.leaderboard,
        metrics_path=args.metrics,
        config=config,
        algorithm_name=args.algorithm,
        run_id=args.run_id,
    )
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        args.archive.write_text(json.dumps(entry, indent=2) + "\n")
    print(json.dumps(entry, indent=2))


def command_build_site(args: argparse.Namespace) -> None:
    print(build_site(leaderboard_path=args.leaderboard, site_dir=args.site_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rcabench-leaderboard")
    subparsers = parser.add_subparsers(required=True)

    validate = subparsers.add_parser("validate", help="validate benchmark configuration")
    _common_config(validate)
    validate.set_defaults(function=command_validate)

    doctor = subparsers.add_parser("doctor", help="check the local execution environment")
    _common_config(doctor)
    doctor.set_defaults(function=command_doctor)

    download = subparsers.add_parser("download", help="download the pinned Hugging Face data")
    _common_config(download)
    download.add_argument("--output", type=Path, required=True)
    download.set_defaults(function=command_download)

    normalize = subparsers.add_parser(
        "normalize-ops-lite", help="create an RCABench-compatible view and deterministic split"
    )
    _common_config(normalize)
    normalize.add_argument("--snapshot", type=Path, required=True)
    normalize.set_defaults(function=command_normalize_ops_lite)

    prepare = subparsers.add_parser("prepare", help="train/cache ART or Eadro assets")
    _common_config(prepare)
    prepare.add_argument("algorithm", choices=("art", "eadro"))
    prepare.add_argument("--snapshot", type=Path, required=True)
    prepare.add_argument("--cache-root", type=Path, default=Path(".cache"))
    prepare.add_argument("--repository-root", type=Path, default=Path.cwd())
    prepare.set_defaults(function=command_prepare)

    run = subparsers.add_parser("run", help="run an algorithm over a manifest")
    _common_config(run)
    run.add_argument("algorithm", choices=("baro", "art", "eadro", "causalrca"))
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--container-runner", type=Path, default=Path("containers/run_algorithm.py"))
    run.add_argument("--assets", type=Path)
    run.add_argument("--split", choices=("all", "train", "test"))
    run.add_argument("--limit", type=int)
    run.add_argument("--workers", type=int)
    run.set_defaults(function=command_run)

    evaluation = subparsers.add_parser("evaluate", help="calculate canonical ranking metrics")
    _common_config(evaluation)
    evaluation.add_argument("algorithm", choices=("baro", "art", "eadro", "causalrca"))
    evaluation.add_argument("--snapshot", type=Path, required=True)
    evaluation.add_argument("--results", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--split", choices=("all", "train", "test"))
    evaluation.add_argument("--limit", type=int)
    evaluation.add_argument("--keep-duplicate-services", action="store_true")
    evaluation.add_argument("--require-complete", action="store_true")
    evaluation.set_defaults(function=command_evaluate)

    record = subparsers.add_parser("record", help="promote metrics to the leaderboard")
    _common_config(record)
    record.add_argument("algorithm", choices=("baro", "art", "eadro", "causalrca"))
    record.add_argument("--metrics", type=Path, required=True)
    record.add_argument("--leaderboard", type=Path, default=Path("results/leaderboard.json"))
    record.add_argument("--run-id", required=True)
    record.add_argument("--archive", type=Path)
    record.set_defaults(function=command_record)

    site = subparsers.add_parser("build-site", help="copy validated data into the static site")
    site.add_argument("--leaderboard", type=Path, default=Path("results/leaderboard.json"))
    site.add_argument("--site-dir", type=Path, default=Path("site"))
    site.set_defaults(function=command_build_site)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.function(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
