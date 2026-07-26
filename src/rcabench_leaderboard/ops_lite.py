from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    names = [record.get("name") for record in records]
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError(f"manifest contains a record without a name: {path}")
    if len(names) != len(set(names)):
        raise ValueError(f"manifest contains duplicate case names: {path}")
    return records


def _labels(record: dict[str, Any]) -> set[str]:
    system = str(record.get("system", "unknown"))
    fault = str(record.get("primary_kind", "unknown"))
    services = {str(service) for service in record.get("root_services", []) if service}
    labels = {f"system:{system}", f"fault:{fault}", f"system_fault:{system}|{fault}"}
    for service in services:
        labels.add(f"service:{service}")
        labels.add(f"fault_service:{fault}|{service}")
    return labels


def iterative_train_test_split(
    records: list[dict[str, Any]], *, test_size: int, seed: int
) -> tuple[list[str], list[str]]:
    """Deterministically preserve multilabel marginals across an 80/20-style split."""
    if not 0 < test_size < len(records):
        raise ValueError("test_size must be between zero and the number of records")

    rng = random.Random(seed)
    case_labels = [_labels(record) for record in records]
    by_label: dict[str, set[int]] = defaultdict(set)
    for index, labels in enumerate(case_labels):
        for label in labels:
            by_label[label].add(index)

    test_ratio = test_size / len(records)
    desired = {
        label: [len(indices) * (1 - test_ratio), len(indices) * test_ratio]
        for label, indices in by_label.items()
    }
    capacity = [len(records) - test_size, test_size]
    assigned: list[list[int]] = [[], []]
    remaining = set(range(len(records)))
    random_rank = list(range(len(records)))
    rng.shuffle(random_rank)
    random_rank = {case: rank for rank, case in enumerate(random_rank)}

    while remaining:
        active_labels = [
            (len(indices & remaining), label)
            for label, indices in by_label.items()
            if indices & remaining
        ]
        _, rarest = min(active_labels, key=lambda item: (item[0], item[1]))
        candidates = sorted(by_label[rarest] & remaining, key=random_rank.__getitem__)
        for index in candidates:
            if index not in remaining:
                continue
            available_folds = [fold for fold in (0, 1) if capacity[fold] > 0]
            fold = max(
                available_folds,
                key=lambda item: (desired[rarest][item], capacity[item], -item),
            )
            assigned[fold].append(index)
            capacity[fold] -= 1
            remaining.remove(index)
            for label in case_labels[index]:
                desired[label][fold] -= 1

    train_indices, test_indices = _rebalance_indices(
        assigned[0], assigned[1], case_labels, by_label, test_ratio, rng
    )
    train = sorted(str(records[index]["name"]) for index in train_indices)
    test = sorted(str(records[index]["name"]) for index in test_indices)
    return train, test


def _rebalance_indices(
    train: list[int],
    test: list[int],
    case_labels: list[set[str]],
    by_label: dict[str, set[int]],
    test_ratio: float,
    rng: random.Random,
) -> tuple[list[int], list[int]]:
    """Improve service and fault marginals through deterministic pair swaps."""
    totals = {label: len(indices) for label, indices in by_label.items()}
    counts = Counter(label for index in test for label in case_labels[index])

    def cost(label: str, count: int) -> float:
        total = totals[label]
        target = total * test_ratio
        prefix = label.split(":", 1)[0]
        weight = {
            "system": 20.0,
            "fault": 6.0,
            "system_fault": 4.0,
            "service": 24.0,
            "fault_service": 2.0,
        }[prefix]
        value = weight * (count - target) ** 2 / max(target, 1.0)
        if prefix == "service" and total >= 3 and count == 0:
            value += 40.0
        return value

    current_cost = sum(cost(label, counts[label]) for label in by_label)
    best_cost = current_cost
    best_train, best_test = list(train), list(test)
    steps = max(100_000, len(case_labels) * 800)
    for step in range(steps):
        train_position = rng.randrange(len(train))
        test_position = rng.randrange(len(test))
        incoming = train[train_position]
        outgoing = test[test_position]
        affected = case_labels[incoming] | case_labels[outgoing]
        before = sum(cost(label, counts[label]) for label in affected)
        changes = {
            label: int(label in case_labels[incoming]) - int(label in case_labels[outgoing])
            for label in affected
        }
        after = sum(cost(label, counts[label] + changes[label]) for label in affected)
        delta = after - before
        temperature = max(0.01, 1.5 * (1 - step / steps))
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            train[train_position], test[test_position] = outgoing, incoming
            for label, change in changes.items():
                counts[label] += change
            current_cost += delta
            if current_cost < best_cost:
                best_cost = current_cost
                best_train, best_test = list(train), list(test)
    return best_train, best_test


def _merge_ground_truth(value: Any) -> dict[str, list[Any]]:
    if isinstance(value, dict):
        sources = [value]
    elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
        sources = value
    else:
        raise ValueError("injection ground_truth must be an object or a list of objects")

    merged: dict[str, list[Any]] = {}
    for source in sources:
        for key, raw_values in source.items():
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            target = merged.setdefault(key, [])
            for item in values:
                if item not in target:
                    target.append(item)
    if not merged.get("service"):
        raise ValueError("injection ground_truth contains no service")
    return merged


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _link_raw_files(raw_case: Path, converted: Path) -> None:
    excluded = {"injection.json", "env.json", "result.json"}
    for source in raw_case.iterdir():
        if source.name in excluded:
            continue
        target = converted / source.name
        if target.exists() and not target.is_symlink():
            source_stat = source.stat()
            target_stat = target.stat()
            if (source_stat.st_dev, source_stat.st_ino) == (
                target_stat.st_dev,
                target_stat.st_ino,
            ):
                continue
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise FileExistsError(f"refusing to replace unexpected normalized file: {target}")
        try:
            target.hardlink_to(source)
        except OSError as exc:
            raise OSError(
                f"cannot create a hard-linked compatibility view for {source}: {exc}"
            ) from exc


def _distribution(records: list[dict[str, Any]], cases: set[str]) -> dict[str, Any]:
    selected = [record for record in records if record["name"] in cases]
    services: Counter[str] = Counter()
    fault_services: Counter[str] = Counter()
    for record in selected:
        fault = str(record.get("primary_kind", "unknown"))
        for service in record.get("root_services", []):
            services[str(service)] += 1
            fault_services[f"{fault}|{service}"] += 1
    return {
        "cases": len(selected),
        "systems": dict(
            sorted(Counter(str(row.get("system", "unknown")) for row in selected).items())
        ),
        "faults": dict(
            sorted(Counter(str(row.get("primary_kind", "unknown")) for row in selected).items())
        ),
        "services": dict(sorted(services.items())),
        "fault_services": dict(sorted(fault_services.items())),
    }


def normalize_ops_lite(
    snapshot: str | Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_cases: int = 500,
    test_size: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    root = Path(snapshot).resolve()
    manifest_path = root / "manifest.jsonl"
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if expected_manifest_sha256 and digest != expected_manifest_sha256:
        raise ValueError(
            f"manifest digest mismatch: expected {expected_manifest_sha256}, found {digest}"
        )
    records = _read_jsonl(manifest_path)
    if len(records) != expected_cases:
        raise ValueError(f"manifest has {len(records)} cases; expected {expected_cases}")

    train, test = iterative_train_test_split(records, test_size=test_size, seed=seed)
    all_cases = sorted(str(record["name"]) for record in records)
    train_set, test_set = set(train), set(test)
    if train_set & test_set or train_set | test_set != set(all_cases):
        raise RuntimeError("generated split is overlapping or incomplete")

    for record in records:
        name = str(record["name"])
        raw_case = root / "cases" / name
        if not raw_case.is_dir():
            raise FileNotFoundError(raw_case)
        converted = root / name / "converted"
        converted.mkdir(parents=True, exist_ok=True)
        _link_raw_files(raw_case, converted)

        injection = json.loads((raw_case / "injection.json").read_text())
        injection["injection_name"] = (
            injection.get("injection_name") or injection.get("name") or name
        )
        injection["ground_truth"] = _merge_ground_truth(injection.get("ground_truth"))
        _write_json(converted / "injection.json", injection)

        environment = json.loads((raw_case / "env.json").read_text())
        environment["TIMEZONE"] = environment.get("TIMEZONE") or environment.get(
            "DB_TIMEZONE", "UTC"
        )
        _write_json(converted / "env.json", environment)

    manifests = root / "rcabench" / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    for name, cases in (("all", all_cases), ("train", train), ("test", test)):
        (manifests / f"{name}.txt").write_text("\n".join(cases) + "\n")

    metadata = {
        "schema_version": 1,
        "source_revision": "9ac09981c08ab02a0b923eab7830d778934851a8",
        "manifest_sha256": digest,
        "seed": seed,
        "strategy": "iterative multilabel stratification",
        "labels": ["system", "primary_kind", "service", "system_x_fault", "fault_x_service"],
        "training_label_policy": "first ground-truth service; evaluation accepts all root services",
        "splits": {
            "all": _distribution(records, set(all_cases)),
            "train": _distribution(records, train_set),
            "test": _distribution(records, test_set),
        },
    }
    _write_json(root / "rcabench" / "split-metadata.json", metadata)
    return metadata
