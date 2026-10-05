import subprocess
from types import SimpleNamespace

import pytest

from testpilot.config import ExecutionConfig
from testpilot.errors import DependencyError, DockerUnavailableError
from testpilot.runners.docker_runner import DockerTestRunner
from testpilot.runners.factory import FallbackRunner
from testpilot.runners.local_runner import LocalTestRunner
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.tools.coverage_analyzer import CoverageAnalyzer
from testpilot.tools.repository_scanner import RepositoryScanner


def test_real_local_execution_and_source_unchanged(project, good_tests):
    original = {p.name: p.read_bytes() for p in project.iterdir()}
    runner = LocalTestRunner(ExecutionConfig(preferred_runner="local"))
    result = runner.run(project, RepositoryScanner().scan(project), good_tests)
    assert result.returncode == 0 and result.passed == 1 and result.backend == "local"
    coverage = CoverageAnalyzer().analyze(result.coverage_data, ["sample.py"])
    assert coverage.line_coverage == coverage.branch_coverage == 100
    assert {p.name: p.read_bytes() for p in project.iterdir()} == original


@pytest.mark.parametrize(
    "content,expected",
    [
        (
            "from sample import absolute\ndef test_x(): assert absolute(-1) == -1\n",
            "AssertionError",
        ),
        ("from absent_xyz import f\ndef test_x(): assert f() == 1\n", "ModuleNotFoundError"),
        ("def test_x(:\n", "SyntaxError"),
    ],
)
def test_real_execution_failures(project, content, expected):
    result = LocalTestRunner(ExecutionConfig()).run(
        project,
        RepositoryScanner().scan(project),
        [GeneratedTest(path="test_bad.py", content=content)],
    )
    assert result.returncode != 0 and expected in result.traceback


def test_pytest_timeout(project):
    result = LocalTestRunner(ExecutionConfig(timeout_seconds=0.5)).run(
        project,
        RepositoryScanner().scan(project),
        [
            GeneratedTest(
                path="test_sleep.py", content="import time\ndef test_sleep(): time.sleep(30)\n"
            )
        ],
    )
    assert result.timed_out and "timeout" in result.traceback
    assert result.duration_seconds < 15


def test_runner_does_not_inherit_secrets(project, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-unit-sentinel")
    result = LocalTestRunner(ExecutionConfig()).run(
        project,
        RepositoryScanner().scan(project),
        [
            GeneratedTest(
                path="test_env.py",
                content="import os\ndef test_env(): assert 'DEEPSEEK_API_KEY' not in os.environ\n",
            )
        ],
        False,
    )
    assert result.returncode == 0


def test_local_never_installs_dependencies(project, good_tests):
    with pytest.raises(DependencyError, match="只允许在 Docker"):
        LocalTestRunner(ExecutionConfig(install_dependencies=True)).run(
            project, RepositoryScanner().scan(project), good_tests
        )


def test_docker_missing(monkeypatch):
    monkeypatch.setattr("testpilot.runners.docker_runner.shutil.which", lambda _: None)
    with pytest.raises(DockerUnavailableError, match="未安装"):
        DockerTestRunner(ExecutionConfig()).probe()


@pytest.mark.parametrize("outcome", ["failure", "timeout"])
def test_daemon_unavailable(monkeypatch, outcome):
    monkeypatch.setattr("testpilot.runners.docker_runner.shutil.which", lambda _: "docker")

    def run(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("docker", 10)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("testpilot.runners.docker_runner.subprocess.run", run)
    with pytest.raises(DockerUnavailableError):
        DockerTestRunner(ExecutionConfig()).probe()


def test_fallback_and_disabled_fallback(project, good_tests, monkeypatch):
    runner = FallbackRunner(ExecutionConfig())

    def unavailable(*args):
        raise DockerUnavailableError("daemon stopped")

    monkeypatch.setattr(runner.docker, "run", unavailable)
    result = runner.run(project, RepositoryScanner().scan(project), good_tests)
    assert result.backend == "local" and "fallback" in result.warnings[0]
    runner.config.allow_local_fallback = False
    with pytest.raises(DockerUnavailableError):
        runner.run(project, RepositoryScanner().scan(project), good_tests)


def test_docker_cleanup_and_isolation_command(project, good_tests, monkeypatch):
    runner = DockerTestRunner(ExecutionConfig())
    monkeypatch.setattr(runner, "probe", lambda: None)
    commands, removed = [], []

    def execute(args, *rest):
        commands.append(args)
        return (-9, "", "", True, 1.0)

    monkeypatch.setattr("testpilot.runners.docker_runner.run_process", execute)
    monkeypatch.setattr(runner, "_remove", removed.append)
    result = runner.run(project, RepositoryScanner().scan(project), good_tests)
    assert result.timed_out and result.backend == "docker"
    assert "--network=none" in commands[0] and "--cap-drop=ALL" in commands[0]
    assert len(removed) == 2 and removed[0].startswith("testpilot-")


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_docker_dependency_install_and_cleanup(project, good_tests, monkeypatch, outcome):
    (project / "requirements.txt").write_text("packaging>=24\n")
    runner = DockerTestRunner(ExecutionConfig(install_dependencies=True))
    monkeypatch.setattr(runner, "probe", lambda: None)
    commands, removed = [], []

    def execute(args, *rest):
        commands.append(args)
        if len(commands) == 1:
            return (0 if outcome == "success" else 1, "", "pip failed", outcome == "timeout", 0.1)
        return (0, "", "", False, 0.1)

    monkeypatch.setattr("testpilot.runners.docker_runner.run_process", execute)
    monkeypatch.setattr(runner, "_remove", removed.append)
    if outcome == "success":
        runner.run(project, RepositoryScanner().scan(project), good_tests)
        assert len(commands) == 2 and "--network=none" in commands[1]
    else:
        with pytest.raises(DependencyError, match="安装失败或超时"):
            runner.run(project, RepositoryScanner().scan(project), good_tests)
    assert "--target" in commands[0] and ".testpilot/deps" in commands[0]
    assert len(removed) == 2


def test_original_pytest_configuration_is_not_executed(project, good_tests):
    (project / "conftest.py").write_text("raise RuntimeError('original conftest loaded')\n")
    (project / "pytest.ini").write_text("[pytest]\naddopts = --invalid-original-option\n")
    result = LocalTestRunner(ExecutionConfig()).run(
        project, RepositoryScanner().scan(project), good_tests
    )
    assert result.returncode == 0
