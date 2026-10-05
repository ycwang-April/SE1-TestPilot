from types import SimpleNamespace

import pytest

from testpilot.agent.state import Status
from testpilot.config import AppConfig, load_config, load_config_with_source
from testpilot.errors import ConfigurationError
from testpilot.ui.cli import main


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def capture_run(monkeypatch, tmp_path):
    calls = []

    def run(project, **kwargs):
        calls.append((project, kwargs["config"]))
        return SimpleNamespace(
            run_dir=str(tmp_path / "runs"), warnings=[], error=None, status=Status.COMPLETED
        )

    monkeypatch.setattr("testpilot.ui.cli.run_project", run)
    return calls


def test_explicit_cli_config_wins_over_invalid_cwd(isolated_cwd, capture_run, capsys):
    (isolated_cwd / "config.yaml").write_text("agent: [invalid")
    chosen = isolated_cwd / "custom.yaml"
    chosen.write_text("agent:\n  context_max_chars: 90000\n")
    assert main(["project", "--config", str(chosen)]) == 0
    assert capture_run[0][1].agent.context_max_chars == 90000
    assert f"Config: {chosen}" in capsys.readouterr().out


def test_auto_cwd_config_and_effective_cli_overrides(
    isolated_cwd, capture_run, capsys, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-sentinel-never-print")
    source = isolated_cwd / "config.yaml"
    source.write_text(
        "agent:\n  context_max_chars: 80000\nexecution:\n  preferred_runner: local\nllm:\n  model: configured-model\n"
    )
    assert load_config().agent.context_max_chars == 80000
    assert main(["project", "--runner", "docker"]) == 0
    config = capture_run[0][1]
    assert config.agent.context_max_chars == 80000
    assert config.execution.preferred_runner == "docker"
    output = capsys.readouterr().out
    assert f"Config: {source}" in output
    assert "model=configured-model; runner=docker; context_max_chars=80000" in output
    assert "secret-sentinel" not in output and "DEEPSEEK_API_KEY" not in output


def test_missing_cwd_config_uses_defaults_not_project_or_parent(isolated_cwd, capture_run, capsys):
    project = isolated_cwd / "target"
    project.mkdir()
    (project / "config.yaml").write_text("agent:\n  context_max_chars: 120000\n")
    (isolated_cwd.parent / "config.yaml").write_text("invalid: true\n")
    config, source = load_config_with_source()
    assert config == AppConfig() and source is None
    assert main([str(project)]) == 0
    assert capture_run[0][1] == AppConfig()
    assert "Config: built-in defaults" in capsys.readouterr().out


@pytest.mark.parametrize(
    "contents",
    [
        b"agent: [broken",
        b"agent:\n  unexpected: 1\n",
        b"agent:\n  context_max_chars: 1\n",
        b"- not-a-mapping\n",
        b"\xff",
    ],
)
def test_invalid_auto_config_fails_without_starting_agent(
    isolated_cwd, capture_run, capsys, contents
):
    (isolated_cwd / "config.yaml").write_bytes(contents)
    with pytest.raises(ConfigurationError):
        load_config()
    assert main(["project"]) == 2
    assert not capture_run
    assert "ConfigurationError" in capsys.readouterr().err


def test_missing_explicit_config_does_not_fall_back(isolated_cwd, capture_run, capsys):
    (isolated_cwd / "config.yaml").write_text("agent:\n  context_max_chars: 80000\n")
    assert main(["project", "--config", "missing.yaml"]) == 2
    assert not capture_run
    assert "ConfigurationError" in capsys.readouterr().err


def test_directory_named_config_is_an_error(isolated_cwd):
    (isolated_cwd / "config.yaml").mkdir()
    with pytest.raises(ConfigurationError):
        load_config()


def test_empty_config_preserves_defaults_and_reports_file(isolated_cwd):
    source = isolated_cwd / "config.yaml"
    source.write_text("")
    config, actual_source = load_config_with_source()
    assert config == AppConfig() and actual_source == source
