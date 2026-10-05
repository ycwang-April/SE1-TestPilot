"""Scoped repair, retention, candidate evidence and bounded validation retries."""

import json
from pathlib import Path

import pytest

from testpilot.agent.state import Status
from testpilot.errors import LLMOutputTruncatedError, LLMOutputValidationError
from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.schemas.test_plan import TestBundle as Bundle
from testpilot.schemas.test_plan import TestCasePlan as Case
from testpilot.schemas.test_plan import TestPlan as Plan
from testpilot.service import run_project
from testpilot.tools.repair_scope import repair_paths
from testpilot.tools.test_validator import retain_tests

BAD = "from sample import absolute\ndef test_negative(): assert absolute(-2) == -2\ndef test_zero(): assert absolute(0) == 0\n"
FIXED = BAD.replace("== -2", "== 2")
PASSING = "from sample import absolute\ndef test_positive(): assert absolute(3) == 3\n"


def generated(path, content):
    return GeneratedTest(path=path, content=content)


class RepairClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    def plan(self, context):
        return Plan(
            target="sample.py",
            cases=[
                Case(
                    category="normal",
                    description="absolute",
                    target_symbol="absolute",
                    input_strategy="signed values",
                    expected_behavior="nonnegative",
                )
            ],
        )

    def generate(self, context, plan):
        return Bundle(files=[generated("test_bad.py", BAD), generated("test_good.py", PASSING)])

    def repair(self, context):
        self.contexts.append(json.loads(context))
        return Bundle(files=next(self.responses))

    def improve(self, context):
        raise AssertionError("Coverage is disabled for repair tests")


@pytest.mark.parametrize(
    "output",
    [
        "test_good.py:10: stack frame\nFAILED .testpilot/generated_tests/test_bad.py::test_negative - AssertionError",
        "ERROR C:\\work\\.testpilot\\generated_tests\\test_bad.py::test_negative - ImportError",
        'File "/work/.testpilot/generated_tests/test_bad.py", line 2\nSyntaxError',
    ],
)
def test_selects_real_failed_file_only(output):
    tests = [generated("test_bad.py", BAD), generated("test_good.py", PASSING)]
    result = ExecutionResult(returncode=1, traceback=output)
    assert repair_paths(tests, result) == ["test_bad.py"]


def test_unattributable_timeout_falls_back_to_each_file():
    tests = [generated("test_bad.py", BAD), generated("test_good.py", PASSING)]
    result = ExecutionResult(returncode=1, timed_out=True, traceback="pytest timeout")
    assert repair_paths(tests, result) == ["test_bad.py", "test_good.py"]


def test_repair_preserves_unrequested_files_and_reexecutes(project, local_config, tmp_path):
    local_config.coverage.enabled = False
    client = RepairClient([[generated("test_bad.py", FIXED)]])
    original_source = (project / "sample.py").read_bytes()
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert [r.failed for r in state.execution_history] == [1, 0]
    assert state.execution_result.passed == 3
    assert state.repair_count == 1
    assert [t.content for t in state.generated_tests] == [FIXED, PASSING]
    assert (project / "sample.py").read_bytes() == original_source
    context = client.contexts[0]
    assert context["repair_files"] == ["test_bad.py"]
    assert [t["path"] for t in context["existing_tests"]] == ["test_bad.py"]
    assert context["preserved_files"] == ["test_good.py"]
    assert context["execution"]["failed"] == 1
    assert "sample.py" in context["source"]


def test_missing_test_is_reported_retried_and_saved(project, local_config, tmp_path, monkeypatch):
    local_config.coverage.enabled = False
    local_config.llm.max_retries = 1
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-private-secret")
    incomplete = "# unit-private-secret\nfrom sample import absolute\ndef test_negative(): assert absolute(-2) == 2\n"
    client = RepairClient(
        [[generated("test_bad.py", incomplete)], [generated("test_bad.py", FIXED)]]
    )
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert len(client.contexts) == 2
    assert "test_bad.py" in client.contexts[1]["validation_feedback"]
    assert "test_zero" in client.contexts[1]["validation_feedback"]
    evidence = Path(state.run_dir) / "repairs/01/test_bad.py"
    rejected_text = (evidence / "attempt-01.json").read_text(encoding="utf-8")
    rejected = json.loads(rejected_text)
    assert not rejected["accepted"] and "test_zero" in rejected["validation_error"]
    assert "unit-private-secret" not in rejected_text and "[REDACTED]" in rejected_text
    assert json.loads((evidence / "attempt-02.json").read_text())["accepted"]
    assert state.generated_tests[0].content == FIXED


@pytest.mark.parametrize(
    "response,error",
    [
        ([generated("test_other.py", FIXED)], "test_other.py"),
        ([generated("test_bad.py", FIXED), generated("test_good.py", PASSING)], "仅允许"),
        (
            [
                generated(
                    "test_bad.py",
                    "from sample import absolute\ndef test_negative(): assert absolute(-2) == 2",
                )
            ],
            "test_zero",
        ),
    ],
)
def test_invalid_repair_stops_at_budget_and_preserves_originals(
    project, local_config, tmp_path, response, error
):
    local_config.coverage.enabled = False
    local_config.llm.max_retries = 1
    client = RepairClient([response, response])
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.FAILED and state.failure_stage == "REPAIR"
    assert len(client.contexts) == 2
    assert error in state.error
    assert [t.content for t in state.generated_tests] == [BAD, PASSING]
    assert len(state.execution_history) == 1


def test_retention_error_names_missing_file_and_function():
    previous = [generated("test_a.py", BAD), generated("test_b.py", PASSING)]
    repaired = [generated("test_a.py", "def test_zero(): assert False")]
    with pytest.raises(LLMOutputValidationError) as caught:
        retain_tests(previous, repaired)
    assert "test_a.py" in str(caught.value) and "test_negative" in str(caught.value)
    assert "test_b.py" in str(caught.value)


class TwoFileClient(RepairClient):
    def generate(self, context, plan):
        return Bundle(files=[generated("test_bad.py", BAD), generated("test_good.py", BAD)])


def test_multiple_failed_files_are_repaired_individually(project, local_config, tmp_path):
    local_config.coverage.enabled = False
    client = TwoFileClient([[generated("test_bad.py", FIXED)], [generated("test_good.py", FIXED)]])
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert [context["repair_files"] for context in client.contexts] == [
        ["test_bad.py"],
        ["test_good.py"],
    ]
    assert [result.failed for result in state.execution_history] == [2, 0]
    assert state.execution_result.passed == 4 and state.repair_count == 1


def test_multi_file_repair_is_not_partially_committed(project, local_config, tmp_path):
    local_config.coverage.enabled = False
    local_config.llm.max_retries = 0
    client = TwoFileClient(
        [
            [generated("test_bad.py", FIXED)],
            [generated("test_good.py", "def test_renamed(): assert False")],
        ]
    )
    state = run_project(project, config=local_config, client=client, output=tmp_path / "runs")
    assert state.status == Status.FAILED
    assert [test.content for test in state.generated_tests] == [BAD, BAD]
    assert len(state.execution_history) == 1
    saved = Path(state.run_dir) / "generated_tests/test_bad.py"
    assert saved.read_text(encoding="utf-8") == BAD


def test_model_failure_saves_diagnostics_and_preserves_execution(project, local_config, tmp_path):
    class FailingClient(RepairClient):
        diagnostics = [{"task": "REPAIR_PATCH", "finish_reason": "length", "status": "failed"}]

        def repair(self, context):
            raise LLMOutputTruncatedError("输出达到长度上限 llm.max_tokens")

    local_config.coverage.enabled = False
    state = run_project(
        project, config=local_config, client=FailingClient([]), output=tmp_path / "runs"
    )
    assert state.status == Status.FAILED and state.failure_stage == "REPAIR"
    assert state.execution_result.failed == 1 and state.execution_result.passed == 2
    assert [test.content for test in state.generated_tests] == [BAD, PASSING]
    root = Path(state.run_dir)
    diagnostics = json.loads((root / "llm_calls.json").read_text())
    assert diagnostics[0]["finish_reason"] == "length"
    evidence = json.loads(
        (root / "repairs/01/test_bad.py/attempt-01.json").read_text(encoding="utf-8")
    )
    assert not evidence["accepted"] and evidence["files"] == []
    assert "LLMOutputTruncatedError" in evidence["validation_error"]
