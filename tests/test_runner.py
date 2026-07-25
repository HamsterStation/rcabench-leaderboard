from rcabench_leaderboard.runner import build_docker_command


def test_baro_command_is_network_isolated(tmp_path):
    data = tmp_path / "data"
    output = tmp_path / "output"
    runner = tmp_path / "runner.py"
    (data / "case" / "converted").mkdir(parents=True)
    output.mkdir()
    runner.write_text("")
    command = build_docker_command(
        name="baro",
        algorithm={
            "image": "example/baro:sha",
            "python": ".venv/bin/python",
            "cpus_per_worker": 2,
        },
        data_root=data,
        case="case",
        case_output=output,
        container_runner=runner,
        assets=None,
    )
    assert command[:3] == ["docker", "run", "--rm"]
    assert "none" in command
    assert command[-7:] == [
        "baro",
        "--input",
        "/input",
        "--output",
        "/output",
        "--datapack",
        "case",
    ]
    assert "example/baro:sha" in command
