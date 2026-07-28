import importlib.util
import json
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
