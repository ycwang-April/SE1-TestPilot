from testpilot.agent.state import Action, AgentState
from testpilot.config import AppConfig


def decide(state: AgentState, config: AppConfig) -> Action:
    """A pure decision policy over observations; loops are bounded by state counters."""
    if state.error:
        return Action.FAIL
    if state.repository is None:
        return Action.ANALYZE
    if not state.test_plan:
        return Action.PLAN
    if not state.generated_tests:
        return Action.GENERATE
    if state.execution_result is None:
        return Action.EXECUTE
    if state.execution_result.returncode or state.execution_result.timed_out:
        return Action.REPAIR if state.repair_count < config.agent.max_repair_rounds else Action.FAIL
    if config.coverage.enabled:
        if state.coverage is None:
            return Action.FAIL
        if (
            state.coverage.line_coverage < config.coverage.line_threshold
            or state.coverage.branch_coverage < config.coverage.branch_threshold
        ):
            return (
                Action.IMPROVE_COVERAGE
                if state.coverage_round < config.coverage.max_improvement_rounds
                else Action.FAIL
            )
    return Action.FINISH
