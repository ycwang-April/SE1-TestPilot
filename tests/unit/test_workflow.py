import json
from pathlib import Path

import pytest

from testpilot.agent.controller import decide
from testpilot.agent.state import Action, AgentState, Status
from testpilot.config import AppConfig
from testpilot.errors import CoverageError, LLMOutputValidationError
from testpilot.llm.fake import bundle
from testpilot.reporting.artifacts import ArtifactWriter
from testpilot.schemas.execution import CoverageResult, ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import TestCasePlan as CasePlan
from testpilot.schemas.test_plan import TestPlan as Plan
from testpilot.service import run_project
from testpilot.ui.cli import main

GOOD = "from sample import absolute\ndef test_absolute():\n    assert absolute(-2) == 2\n    assert absolute(3) == 3\n"
BAD = GOOD.replace("== 2", "== -2")
LOW = "from sample import absolute\ndef test_absolute(): assert absolute(2) == 2\n"


class ScriptedClient:
    def __init__(self, initial=GOOD, repair=GOOD):
        self.initial, self.repaired = initial, repair
        self.contexts = []
        self.improvements = 0

    def plan(self, context):
        return Plan(
            target="sample.py",
            cases=[
                CasePlan(
                    category="normal",
                    description="absolute",
                    target_symbol="absolute",
                    input_strategy="signed integers",
                    expected_behavior="nonnegative",
                )
            ],
        )

    def generate(self, context, plan):
        return bundle("test_sample.py", self.initial)

    def repair(self, context):
        self.contexts.append(json.loads(context))
        return bundle("test_sample.py", self.repaired)

    def improve(self, context):
        self.contexts.append(json.loads(context))
        self.improvements += 1
        return bundle(f"test_extra_{self.improvements}.py", LOW)


def assert_artifacts(state):
    directory = Path(state.run_dir)
    for filename in (
        "test_plan.json",
        "execution_result.json",
        "coverage_result.json",
        "final_report.json",
        "final_report.md",
        "trace.json",
        "state.json",
    ):
        assert (directory / filename).is_file()
    return json.loads((directory / "final_report.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("example", ["basic", "multi_module", "edge_cases"])
def test_all_examples_real_execution(example_root, example, tmp_path, local_config):
    state = run_project(
        example_root / example, demo=True, config=local_config, output=tmp_path / "runs"
    )
    assert state.status == Status.COMPLETED, state.error
    assert state.coverage.line_coverage == state.coverage.branch_coverage == 100
    report = assert_artifacts(state)
    assert report["demo"] and report["final_failed"] == 0
    if example == "multi_module":
        assert report["modules"] == 3 and state.project_index["order.py"].internal_dependencies == [
            "discount.py",
            "models.py",
        ]
    if example == "edge_cases":
        assert state.repair_count == state.coverage_round == 1
        assert [s.action for s in state.history] == [
            Action.ANALYZE,
            Action.PLAN,
            Action.GENERATE,
            Action.EXECUTE,
            Action.REPAIR,
            Action.EXECUTE,
            Action.IMPROVE_COVERAGE,
            Action.EXECUTE,
            Action.FINISH,
        ]
        assert report["initial_failed"] == 1 and report["final_passed"] == 9
        rounds = Path(state.run_dir) / "rounds"
        assert len(list(rounds.glob("*/execution_result.json"))) == 3
        assert (
            json.loads((rounds / "02" / "coverage_result.json").read_text())["line_coverage"] < 80
        )


@pytest.mark.parametrize(
    "initial",
    [
        BAD,
        "def test_absolute(:\n",
        "from missing_module import absolute\ndef test_absolute(): assert absolute(2) == 2\n",
    ],
)
def test_actual_feedback_repair(project, local_config, tmp_path, initial):
    client = ScriptedClient(initial)
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert state.repair_count == 1
    assert client.contexts[0]["execution"]["returncode"] != 0
    assert client.contexts[0]["execution"]["traceback"]
    assert client.contexts[0]["existing_tests"][0]["content"] == initial


def test_repair_exhaustion_real_runner(project, local_config, tmp_path):
    state = run_project(
        project, config=local_config, client=ScriptedClient(BAD, BAD), output=tmp_path / "runs"
    )
    assert state.status == Status.FAILED and state.repair_count == 2
    assert len(state.execution_history) == 3
    assert "最大次数" in assert_artifacts(state)["error"]


def test_coverage_exhaustion_preserves_tests(project, local_config, tmp_path):
    client = ScriptedClient(LOW)
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.FAILED and state.coverage_round == 2
    assert state.repair_count == 0 and state.execution_result.returncode == 0
    assert len(state.generated_tests) == 3
    assert client.contexts[0]["coverage"]["missing_lines"]["sample.py"]
    assert "Coverage" in assert_artifacts(state)["error"]


def test_zero_retries_stops_immediately(project, local_config, tmp_path):
    local_config.agent.max_repair_rounds = 0
    state = run_project(
        project, config=local_config, client=ScriptedClient(BAD), output=tmp_path / "runs"
    )
    assert state.status == Status.FAILED and len(state.execution_history) == 1


def test_coverage_disabled_is_valid_mode(project, local_config, tmp_path):
    local_config.coverage.enabled = False
    state = run_project(
        project, config=local_config, client=ScriptedClient(LOW), output=tmp_path / "runs"
    )
    assert state.status == Status.COMPLETED and state.coverage is None


def test_target_scope(example_root, local_config, tmp_path):
    state = run_project(
        example_root / "multi_module",
        target="order.py",
        demo=True,
        config=local_config,
        output=tmp_path / "runs",
    )
    assert state.status == Status.COMPLETED
    assert state.target_modules == ["order.py"] and len(state.test_plan) == 1
    assert list(state.coverage.missing_lines) == ["order.py"]


@pytest.mark.parametrize("case", ["missing", "syntax", "key", "target", "dependency", "demo"])
def test_failure_report_for_boundaries(project, local_config, tmp_path, monkeypatch, case):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    target, demo, client = None, False, ScriptedClient()
    if case == "missing":
        project = project / "not-found"
    elif case == "syntax":
        (project / "sample.py").write_text("def x(:")
    elif case == "key":
        client = None
    elif case == "target":
        target = "../sample.py"
    elif case == "dependency":
        (project / "requirements.txt").write_text("absent-testpilot-package-394234>=1")
    elif case == "demo":
        client, demo = None, True
    state = run_project(
        project,
        config=local_config,
        target=target,
        demo=demo,
        client=client,
        output=tmp_path / "runs",
    )
    assert state.status == Status.FAILED and state.failure_stage and state.error
    assert assert_artifacts(state)["status"] == "FAILED"


def test_coverage_collection_failure_is_not_success(project, local_config, tmp_path, monkeypatch):
    def broken(*args):
        raise CoverageError("coverage unavailable")

    monkeypatch.setattr("testpilot.agent.nodes.CoverageAnalyzer.analyze", broken)
    state = run_project(
        project, config=local_config, client=ScriptedClient(), output=tmp_path / "runs"
    )
    assert state.status == Status.FAILED and "CoverageError" in state.error
    assert state.execution_result.passed == 1


def test_all_skipped_tests_are_not_success(project, local_config, tmp_path):
    local_config.coverage.enabled = False
    skipped = (
        "import pytest\n@pytest.mark.skip(reason='bad test')\ndef test_absolute(): assert 1 == 2\n"
    )
    state = run_project(
        project, config=local_config, client=ScriptedClient(skipped), output=tmp_path / "runs"
    )
    assert state.status == Status.FAILED
    assert "未报告任何实际通过" in state.error


def test_invalid_llm_output_generates_report(project, local_config, tmp_path, monkeypatch):
    client = ScriptedClient()

    def invalid(*args):
        raise LLMOutputValidationError("empty tests")

    monkeypatch.setattr(client, "generate", invalid)
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert assert_artifacts(state)["failure_stage"] == "GENERATE"


def test_router_decisions():
    config = AppConfig()
    state = AgentState(project_path=".")
    assert decide(state, config) == Action.ANALYZE
    state.repository = RepositoryInfo(project_path=".")
    assert decide(state, config) == Action.PLAN
    state.test_plan = [ScriptedClient().plan("")]
    assert decide(state, config) == Action.GENERATE
    state.generated_tests = bundle("test_sample.py", GOOD).files
    assert decide(state, config) == Action.EXECUTE
    state.execution_result = ExecutionResult(returncode=1)
    assert decide(state, config) == Action.REPAIR
    state.repair_count = 2
    assert decide(state, config) == Action.FAIL
    state.execution_result.returncode = 0
    state.coverage = CoverageResult(line_coverage=50, branch_coverage=50)
    assert decide(state, config) == Action.IMPROVE_COVERAGE
    state.coverage_round = 2
    assert decide(state, config) == Action.FAIL
    state.coverage = CoverageResult(line_coverage=100, branch_coverage=100)
    assert decide(state, config) == Action.FINISH
    state.error = "fatal"
    assert decide(state, config) == Action.FAIL


def test_artifact_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-secret-123456")
    writer = ArtifactWriter(tmp_path / "evidence")
    writer.json("result.json", {"error": "unit-secret-123456"})
    assert "unit-secret-123456" not in (writer.directory / "result.json").read_text()


def test_cli_success_and_failure(example_root, tmp_path, capsys, monkeypatch):
    assert (
        main(
            [str(example_root / "basic"), "--demo", "--runner", "local", "--output", str(tmp_path)]
        )
        == 0
    )
    assert "DEMO MODE" in capsys.readouterr().out
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main([str(example_root / "basic"), "--output", str(tmp_path)]) == 1
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err
    assert main([str(example_root / "basic"), "--config", str(tmp_path / "missing.yaml")]) == 2


def test_web_entrypoint_and_live_demo(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    path = Path(__file__).resolve().parents[2] / "testpilot" / "ui" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    app.selectbox(key="runner").select("local")
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "9"
