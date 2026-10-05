import logging
from pathlib import Path

from testpilot.agent.controller import decide
from testpilot.agent.state import Action, AgentState, Status, TraceEvent
from testpilot.config import AppConfig
from testpilot.errors import (
    LLMOutputValidationError,
    ProjectAnalysisError,
    TestExecutionError,
    TestPilotError,
)
from testpilot.llm.client import DeepSeekClient, LLMClient
from testpilot.reporting.artifacts import ArtifactWriter, redact
from testpilot.runners.base import TestRunner
from testpilot.tools.ast_analyzer import ASTAnalyzer
from testpilot.tools.context_selector import ContextSelector
from testpilot.tools.coverage_analyzer import CoverageAnalyzer
from testpilot.tools.plan_optimizer import optimize_plan
from testpilot.tools.repair_scope import repair_paths
from testpilot.tools.repository_scanner import RepositoryScanner
from testpilot.tools.test_deduplicator import deduplicate_tests
from testpilot.tools.test_validator import retain_tests, validate_tests

LOGGER = logging.getLogger(__name__)


class AgentNodes:
    def __init__(
        self,
        config: AppConfig,
        runner: TestRunner,
        artifacts: ArtifactWriter,
        client: LLMClient | None = None,
        observer=None,
    ):
        self.config, self.runner, self.artifacts = config, runner, artifacts
        self.client, self.observer = client, observer
        self.selector = ContextSelector(config.agent.context_max_chars)

    def llm(self) -> LLMClient:
        if self.client is None:
            self.client = DeepSeekClient(self.config.llm)
        return self.client

    def controller(self, state: AgentState) -> dict:
        return {"current_action": decide(state, self.config)}

    def perform(self, action: Action):
        def node(original: AgentState) -> dict:
            state = original.model_copy(deep=True)
            state.current_action = action
            try:
                getattr(self, action.value.lower())(state)
                observation = f"{action.value}: {state.status.value}"
                if action == Action.EXECUTE and state.execution_result:
                    result = state.execution_result
                    observation += f"; rc={result.returncode}, passed={result.passed}, failed={result.failed}, errors={result.errors}"
                    if state.coverage:
                        observation += f"; line={state.coverage.line_coverage:.2f}, branch={state.coverage.branch_coverage:.2f}"
            except Exception as exc:
                # The graph boundary turns expected and unexpected failures into durable reports.
                state.error = (
                    redact(f"{type(exc).__name__}: {exc}")
                    if isinstance(exc, TestPilotError)
                    else f"Internal {type(exc).__name__}; 请检查输入或提交问题报告"
                )
                state.failure_stage = action.value
                observation = state.error
                LOGGER.warning("%s failed: %s", action.value, state.error)
            events = getattr(self.client, "events", [])
            state.warnings = list(dict.fromkeys(state.warnings + events))
            diagnostics = getattr(self.client, "diagnostics", None)
            if diagnostics:
                self.artifacts.json("llm_calls.json", diagnostics)
            state.history.append(
                TraceEvent(
                    step=len(state.history) + 1,
                    action=action,
                    observation=observation,
                    repair_count=state.repair_count,
                    coverage_round=state.coverage_round,
                )
            )
            self.artifacts.snapshot(state)
            if self.observer:
                self.observer(state.model_copy(deep=True))
            return state.model_dump()

        return node

    def analyze(self, state: AgentState) -> None:
        state.status = Status.ANALYZING
        state.repository = RepositoryScanner().scan(state.project_path)
        state.project_index = ASTAnalyzer().analyze(state.repository)
        if state.requested_target:
            target = state.requested_target.replace("\\", "/").removeprefix("./")
            if target not in state.project_index:
                raise ProjectAnalysisError(f"目标不在项目源码中: {target}")
            state.target_modules = [target]
        else:
            state.target_modules = list(state.project_index)

    def plan(self, state: AgentState) -> None:
        state.status = Status.PLANNING
        state.test_plan = []
        for target in state.target_modules:
            state.selected_context = self.selector.select(state, "PLAN", [target])
            plan, notes = optimize_plan(self.llm().plan(state.selected_context))
            state.test_plan.append(plan)
            state.warnings.extend(notes)

    def generate(self, state: AgentState) -> None:
        state.status = Status.GENERATING
        tests = []
        for target, plan in zip(state.target_modules, state.test_plan, strict=True):
            state.generated_tests = tests
            state.selected_context = self.selector.select(state, "GENERATE", [target])
            tests.extend(self.llm().generate(state.selected_context, plan).files)
        tests, notes = deduplicate_tests(tests)
        state.warnings.extend(notes)
        validate_tests(tests)
        state.generated_tests = tests

    def execute(self, state: AgentState) -> None:
        state.status = Status.EXECUTING
        state.coverage = None
        result = self.runner.run(
            Path(state.project_path),
            state.repository,
            state.generated_tests,
            self.config.coverage.enabled,
        )
        state.execution_result = result
        state.execution_history.append(result)
        state.warnings.extend(result.warnings)
        if result.returncode == 0 and result.passed == 0:
            raise TestExecutionError(
                "pytest 未报告任何实际通过的用例；拒绝将空/全部跳过的测试视为成功"
            )
        if result.returncode == 0 and self.config.coverage.enabled:
            state.coverage = CoverageAnalyzer().analyze(result.coverage_data, state.target_modules)

    def repair(self, state: AgentState) -> None:
        state.status = Status.REPAIRING
        state.repair_count += 1
        replacements = {}
        paths = repair_paths(state.generated_tests, state.execution_result)
        originals = {test.path: test for test in state.generated_tests}
        for path in paths:
            feedback = None
            for attempt in range(self.config.llm.max_retries + 1):
                state.selected_context = self.selector.select(
                    state,
                    "REPAIR",
                    state.target_modules,
                    repair_file=path,
                    validation_feedback=feedback,
                )
                artifact = f"repairs/{state.repair_count:02d}/{path}/attempt-{attempt + 1:02d}.json"
                evidence = {
                    "requested_file": path,
                    "files": [],
                    "accepted": False,
                    "validation_error": None,
                }
                try:
                    candidates = self.llm().repair(state.selected_context).files
                except TestPilotError as exc:
                    evidence["validation_error"] = f"{type(exc).__name__}: {exc}"
                    self.artifacts.json(artifact, evidence)
                    raise
                evidence["files"] = [test.model_dump() for test in candidates]
                # Save rejected candidates as evidence without replacing the working tests.
                self.artifacts.json(artifact, evidence)
                try:
                    if [test.path for test in candidates] != [path]:
                        raise LLMOutputValidationError(
                            f"本次仅允许返回 {path}；实际返回: "
                            + ", ".join(test.path for test in candidates)
                        )
                    validate_tests(candidates)
                    retain_tests([originals[path]], candidates)
                except LLMOutputValidationError as exc:
                    feedback = str(exc)
                    evidence["validation_error"] = feedback
                    self.artifacts.json(artifact, evidence)
                    state.warnings.append(
                        f"REPAIR {path}: candidate {attempt + 1} rejected: {redact(feedback)}"
                    )
                    if attempt == self.config.llm.max_retries:
                        raise
                else:
                    evidence["accepted"] = True
                    self.artifacts.json(artifact, evidence)
                    replacements[path] = candidates[0]
                    break
        # Commit only when every selected file validates; retain all other bytes verbatim.
        tests = [replacements.get(test.path, test) for test in state.generated_tests]
        validate_tests(tests)
        retain_tests(state.generated_tests, tests)
        state.generated_tests = tests
        state.execution_result = None

    def improve_coverage(self, state: AgentState) -> None:
        state.status = Status.IMPROVING_COVERAGE
        state.coverage_round += 1
        state.selected_context = self.selector.select(
            state, "IMPROVE_COVERAGE", state.target_modules
        )
        additions, notes = deduplicate_tests(self.llm().improve(state.selected_context).files)
        state.warnings.extend(notes)
        tests = state.generated_tests + additions
        validate_tests(tests)
        state.generated_tests = tests
        state.execution_result = None

    def finish(self, state: AgentState) -> None:
        state.status = Status.COMPLETED

    def fail(self, state: AgentState) -> None:
        state.status = Status.FAILED
        if not state.error:
            result = state.execution_result
            if result and (result.returncode or result.timed_out):
                state.error = "Repair 已达到最大次数；测试仍失败，请检查报告中的真实 traceback"
                state.failure_stage = "REPAIR"
            else:
                state.error = "Coverage 补测达到最大轮次或缺少有效数据；目标覆盖率未达标"
                state.failure_stage = "IMPROVE_COVERAGE"
