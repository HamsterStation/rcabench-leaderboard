from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download


def download_dataset(config: dict[str, Any], output: str | Path) -> Path:
    dataset = config["dataset"]
    output_path = Path(output).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=dataset["repo_id"],
        repo_type=dataset.get("repo_type", "dataset"),
        revision=dataset["revision"],
        local_dir=output_path,
        token=os.getenv("HF_TOKEN"),
        allow_patterns=dataset.get("allow_patterns"),
        max_workers=int(dataset.get("download_workers", 8)),
    )
    return output_path
