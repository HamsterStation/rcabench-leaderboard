from pathlib import Path

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
