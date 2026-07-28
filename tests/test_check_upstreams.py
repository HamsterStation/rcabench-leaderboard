import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


def _load_script(name):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_upstreams = _load_script("check_upstreams")
plan_pr_benchmark = _load_script("plan_pr_benchmark")


def test_check_registry_skips_disabled_images_and_preserves_formatting(tmp_path, monkeypatch):
    registry = tmp_path / "algorithms.json"
    registry.write_text(
        '{"images": {\n'
        '  "tracked": {"source": "tracked.git", "commit": "old", '
        '"image": "ghcr.io/hamsterstation/rcabench-tracked:old", "tag_suffix": "-r1"},\n'
        '  "detached": {"source": "detached.git", "commit": "keep", '
        '"image": "ghcr.io/hamsterstation/rcabench-detached:keep", "watch": false}\n'
        "}}\n"
    )
    original = registry.read_text()

    calls = []

    def fake_remote_head(source):
        calls.append(source)
        return "1234567890abcdef1234567890abcdef12345678"

    monkeypatch.setattr(check_upstreams, "remote_head", fake_remote_head)
    report = check_upstreams.check_registry(registry, apply=True)

    assert calls == ["tracked.git"]
    assert report["skipped"] == [{"image": "detached", "reason": "upstream tracking disabled"}]
    assert report["updates"][0]["image"] == "tracked"
    assert registry.read_text().count("\n") == original.count("\n")
    updated = json.loads(registry.read_text())
    assert updated["images"]["tracked"]["commit"] == fake_remote_head("tracked.git")
    assert updated["images"]["tracked"]["image"].endswith(":12345678-r1")
    assert updated["images"]["detached"]["commit"] == "keep"


def test_build_definition_ignores_watcher_metadata():
    base = {"source": "repo.git", "commit": "abc", "image": "image:abc"}
    assert plan_pr_benchmark._build_definition(base) == plan_pr_benchmark._build_definition(
        {**base, "watch": False}
    )


def test_new_dataset_expands_to_every_registered_algorithm(tmp_path):
    root = Path(__file__).parents[1]
    shutil.copytree(root / "config", tmp_path / "config")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "config"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)

    config = json.loads((tmp_path / "config/ops-lite.json").read_text())
    config["benchmark"]["id"] = "candidate-seed42"
    config["benchmark"]["title"] = "Candidate"
    config["dataset"]["repo_id"] = "example/candidate"
    (tmp_path / "config/candidate.json").write_text(json.dumps(config))
    registry_path = tmp_path / "config/datasets.json"
    registry = json.loads(registry_path.read_text())
    registry["datasets"]["candidate"] = {
        "config": "candidate.json",
        "adapter": "ops-lite",
        "watch": False,
    }
    registry_path.write_text(json.dumps(registry))

    report = plan_pr_benchmark.plan("HEAD", tmp_path)
    assert report["changed_datasets"] == ["candidate"]
    assert len(report["matrix"]) == 12
    assert {row["benchmark"] for row in report["matrix"]} == {"candidate"}
    assert {row["adapter"] for row in report["matrix"]} == {"ops-lite"}
