import ast
from pathlib import Path

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


def test_all_paper_algorithms_have_container_adapters():
    source = (Path(__file__).parents[1] / "containers/run_algorithm.py").read_text()
    module = ast.parse(source)
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "ALGORITHMS"
    )
    algorithms = ast.literal_eval(assignment.value)
    assert set(algorithms) == {
        "baro",
        "art",
        "eadro",
        "causalrca",
        "diagfusion",
        "microdig",
        "microhecl",
        "microrank",
        "microrca",
        "nezha",
        "shapleyiq",
        "simplerca",
    }


def test_algorithm_environment_is_forwarded_to_container(tmp_path):
    data = tmp_path / "data"
    output = tmp_path / "output"
    runner = tmp_path / "runner.py"
    (data / "case" / "converted").mkdir(parents=True)
    output.mkdir()
    runner.write_text("")
    command = build_docker_command(
        name="diagfusion",
        algorithm={
            "image": "example/diagfusion:sha",
            "python": ".venv/bin/python",
            "environment": {"CHECKPOINT_PATH": "/app/checkpoint.pt"},
        },
        data_root=data,
        case="case",
        case_output=output,
        container_runner=runner,
        assets=None,
    )
    assert "CHECKPOINT_PATH=/app/checkpoint.pt" in command
