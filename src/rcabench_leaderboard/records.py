from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def record_metrics(
    *,
    leaderboard_path: str | Path,
    metrics_path: str | Path,
    config: dict[str, Any],
    algorithm_name: str,
    run_id: str,
) -> dict[str, Any]:
    path = Path(leaderboard_path)
    leaderboard = json.loads(path.read_text())
    metrics = json.loads(Path(metrics_path).read_text())
    algorithm = config["algorithms"][algorithm_name]
    entry = {
        "algorithm": algorithm_name,
        "display_name": algorithm["display_name"],
        "algorithm_commit": algorithm["commit"],
        "scope": algorithm["scope"],
        "cases": metrics["requested_cases"],
        "run_id": run_id,
        "metrics": metrics,
    }
    # The leaderboard stores the latest run per algorithm; CI archives every run separately.
    entries = [
        item for item in leaderboard.get("entries", []) if item["algorithm"] != algorithm_name
    ]
    entries.append(entry)
    entries.sort(key=lambda item: (-float(item["metrics"].get("mrr", 0)), item["algorithm"]))
    leaderboard["entries"] = entries
    leaderboard["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(leaderboard, indent=2, sort_keys=False) + "\n")
    temporary.replace(path)
    return entry


def build_site(*, leaderboard_path: str | Path, site_dir: str | Path) -> Path:
    source = Path(leaderboard_path)
    destination = Path(site_dir) / "data.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text())
    return destination
