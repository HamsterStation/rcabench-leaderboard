from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _truth_services(injection: dict[str, Any]) -> set[str]:
    value = injection.get("ground_truth", {}).get("service", [])
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _ranked_services(result: dict[str, Any], deduplicate: bool) -> tuple[list[str], bool]:
    answers = [item for item in result.get("answers", []) if item.get("level") == "service"]
    answers.sort(key=lambda item: (int(item.get("rank", 10**9)), str(item.get("name", ""))))
    names = [str(item["name"]) for item in answers if item.get("name")]
    has_duplicates = len(names) != len(set(names))
    if deduplicate:
        names = list(dict.fromkeys(names))
    return names, has_duplicates


def evaluate(
    *,
    cases: list[str],
    data_root: str | Path,
    results_root: str | Path,
    deduplicate_services: bool = True,
) -> dict[str, Any]:
    data_path = Path(data_root)
    results_path = Path(results_root)
    hits = {rank: 0 for rank in range(1, 6)}
    reciprocal_rank = 0.0
    durations: list[float] = []
    missing: list[str] = []
    invalid: list[str] = []
    duplicate_ranking_cases = 0
    algorithm_error_names: list[str] = []

    for case in cases:
        result_file = results_path / case / "result.json"
        injection_file = data_path / case / "converted" / "injection.json"
        if not result_file.is_file():
            missing.append(case)
            continue
        try:
            result = json.loads(result_file.read_text())
            if result.get("status") == "algorithm_error":
                algorithm_error_names.append(case)
            injection = json.loads(injection_file.read_text())
            truth = _truth_services(injection)
            if not truth:
                raise ValueError("empty ground-truth service")
            ranking, had_duplicates = _ranked_services(result, deduplicate_services)
            duplicate_ranking_cases += int(had_duplicates)
            first_hit = next(
                (position for position, name in enumerate(ranking, start=1) if name in truth),
                None,
            )
            if first_hit is not None:
                reciprocal_rank += 1.0 / first_hit
                for rank in hits:
                    hits[rank] += int(first_hit <= rank)
            if result.get("duration_seconds") is not None:
                durations.append(float(result["duration_seconds"]))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid.append(case)

    denominator = len(cases)
    top = {rank: hits[rank] / denominator if denominator else 0.0 for rank in hits}
    return {
        "schema_version": 1,
        "requested_cases": denominator,
        "successful_result_files": denominator - len(missing) - len(invalid),
        "missing_cases": len(missing),
        "invalid_cases": len(invalid),
        "missing_case_names": missing,
        "invalid_case_names": invalid,
        "deduplicate_services": deduplicate_services,
        "duplicate_ranking_cases": duplicate_ranking_cases,
        "algorithm_error_cases": len(algorithm_error_names),
        "algorithm_error_case_names": algorithm_error_names,
        "top@1": top[1],
        "top@3": top[3],
        "top@5": top[5],
        "avg@3": sum(top[rank] for rank in range(1, 4)) / 3,
        "avg@5": sum(top[rank] for rank in range(1, 6)) / 5,
        "mrr": reciprocal_rank / denominator if denominator else 0.0,
        "average_algorithm_seconds": sum(durations) / len(durations) if durations else None,
    }


def write_metrics(path: str | Path, metrics: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
