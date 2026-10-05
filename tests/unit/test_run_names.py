"""Readable, safe, collision-resistant run naming without changing artifacts."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from testpilot import service
from testpilot.reporting import runs

START = datetime(2026, 10, 4, 12, 41, 26, tzinfo=timezone.utc)


@pytest.mark.parametrize("demo,mode", [(True, "demo"), (False, "deepseek")])
@pytest.mark.parametrize("backend", ["docker", "local"])
def test_run_directory_name(tmp_path, demo, mode, backend, monkeypatch):
    monkeypatch.setattr(runs, "uuid4", lambda: SimpleNamespace(hex="69d3b56a" + "0" * 24))
    directory = runs.create_run_directory(
        tmp_path, "advanced_project", demo, backend, started_at=START
    )
    assert directory.name == f"advanced_project-{mode}-{backend}-20261004-204126-69d3b56a"
    assert directory.parent == tmp_path.resolve()
    assert directory.is_dir()


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "..\\evil",
        "/root",
        "C:\\work:ADS",
        "CON",
        "NUL.txt",
        "项目名称",
        "",
        "...",
        "a" * 300,
        "A Café / Project",
        "foo\x00bar",
        " trailing. ",
    ],
)
def test_slug_is_a_safe_bounded_component(tmp_path, name):
    slug = runs.project_slug(name)
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", slug)
    assert slug not in ("con", "prn", "aux", "nul")
    directory = runs.create_run_directory(tmp_path, name, True, "local", started_at=START)
    assert directory.parent == tmp_path.resolve()
    assert (tmp_path / f"{slug}-final-report.md").parent == tmp_path


def test_slug_preserves_readable_names():
    assert runs.project_slug("advanced_project") == "advanced_project"
    assert runs.project_slug("A Café Project") == "a-cafe-project"
    assert runs.project_slug("中文") == "project"
    assert runs.project_slug("LPT1") == "project"


def test_same_time_concurrent_runs_never_share_a_directory(tmp_path):
    def create(_):
        return runs.create_run_directory(tmp_path, "basic", True, "local", started_at=START)

    with ThreadPoolExecutor(max_workers=8) as executor:
        directories = list(executor.map(create, range(32)))
    assert len(set(directories)) == 32
    assert all(d.is_dir() and "-20261004-204126-" in d.name for d in directories)


def test_random_collision_does_not_reuse_existing_run(tmp_path, monkeypatch):
    ids = iter(["a" * 32, "a" * 32, "b" * 32])
    monkeypatch.setattr(runs, "uuid4", lambda: SimpleNamespace(hex=next(ids)))
    first = runs.create_run_directory(tmp_path, "basic", True, "local", started_at=START)
    (first / "trace.json").write_bytes(b"original")
    second = runs.create_run_directory(tmp_path, "basic", True, "local", started_at=START)
    assert first != second
    assert (first / "trace.json").read_bytes() == b"original"


def test_backend_relabel_preserves_artifacts_and_avoids_existing_run(tmp_path, monkeypatch):
    ids = iter(["a" * 32, "a" * 32, "b" * 32])
    monkeypatch.setattr(runs, "uuid4", lambda: SimpleNamespace(hex=next(ids)))
    source = runs.create_run_directory(tmp_path, "basic", True, "docker", started_at=START)
    occupied = runs.create_run_directory(tmp_path, "basic", True, "local", started_at=START)
    (occupied / "trace.json").write_bytes(b"other run")
    (source / "trace.json").write_bytes(b"this run")
    (source / "rounds/01").mkdir(parents=True)
    (source / "rounds/01/execution_result.json").write_bytes(b"execution")
    target = runs.finalize_backend(source, "local")
    assert target != occupied and target.parent == source.parent
    assert "-demo-local-20261004-204126-" in target.name
    assert (target / "trace.json").read_bytes() == b"this run"
    assert (target / "rounds/01/execution_result.json").read_bytes() == b"execution"
    assert (occupied / "trace.json").read_bytes() == b"other run"
    assert not source.exists()


@pytest.mark.parametrize(
    "name",
    [
        "advanced_project-deepseek-docker-20261004-204126-69d3b56a",
        "20261004T124126Z-69d3b56a",
    ],
)
def test_display_time_supports_new_and_legacy_names(name):
    assert runs.run_time_and_id(Path(name)) == ("2026-10-04 20:41:26 UTC+08:00", "69d3b56a")


@pytest.mark.parametrize("name", ["basic", "basic-demo-local-20269999-999999-aaaaaaaa"])
def test_unknown_time_is_not_inferred(name):
    assert runs.run_time_and_id(Path(name)) == ("Unknown", "—")


def test_service_run_dir_and_state_snapshot_stay_consistent(example_root, local_config, tmp_path):
    state = service.run_project(
        example_root / "basic", config=local_config, demo=True, output=tmp_path
    )
    directory = Path(state.run_dir)
    assert runs.RUN_PATTERN.fullmatch(directory.name)
    assert directory.name.startswith("basic-demo-local-")
    snapshot = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert snapshot["run_dir"] == state.run_dir
    assert {
        "final_report.md",
        "final_report.json",
        "test_plan.json",
        "trace.json",
        "state.json",
        "generated_tests",
        "rounds",
        "execution_result.json",
        "coverage_result.json",
    } == {p.name for p in directory.iterdir()}


def test_early_failure_preserves_requested_backend(example_root, tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    state = service.run_project(example_root / "basic", output=tmp_path)
    directory = Path(state.run_dir)
    assert directory.name.startswith("basic-deepseek-docker-")
    report = json.loads((directory / "final_report.json").read_text(encoding="utf-8"))
    assert report["execution_backend"] == "not executed"
