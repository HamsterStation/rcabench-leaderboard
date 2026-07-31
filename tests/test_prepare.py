from pathlib import Path

import pytest

from rcabench_leaderboard import prepare
from rcabench_leaderboard.prepare import _docker_base


def test_docker_base_mounts_absolute_symlink_targets_read_only(tmp_path: Path):
    source_root = tmp_path / "source"
    case = source_root / "case-1"
    case.mkdir(parents=True)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / case.name).symlink_to(case)

    command = _docker_base("example/image:fixed", snapshot)

    assert f"{snapshot.resolve()}:/benchmark-data:ro" in command
    assert f"{source_root.resolve()}:{source_root.resolve()}:ro" in command
    assert command[-1] == "example/image:fixed"


def test_art_preparation_resumes_at_finalize_when_samples_exist(tmp_path: Path, monkeypatch):
    cache_root = tmp_path / "cache"
    samples = cache_root / "training/art/revision-commit/art-data/RCABENCH/samples"
    samples.mkdir(parents=True)
    (samples / "train_samples.pkl").write_bytes(b"preserved train")
    (samples / "test_samples.pkl").write_bytes(b"preserved test")
    data_root = tmp_path / "dataset"
    data_root.mkdir()
    commands: list[list[str]] = []

    def stop_after_first_command(command, _log_path, *, allow_failure=False):
        commands.append(command)
        raise RuntimeError("stop after command inspection")

    monkeypatch.setattr(prepare, "_run", stop_after_first_command)

    with pytest.raises(RuntimeError, match="command inspection"):
        prepare.prepare_art(
            algorithm={"image": "example/image:fixed"},
            data_root=data_root,
            train_cases=[],
            test_cases=[],
            cache_root=cache_root,
            repository_root=tmp_path,
            cache_key="revision-commit",
        )

    assert len(commands) == 1
    assert commands[0][-1] == "/finalize.py"
