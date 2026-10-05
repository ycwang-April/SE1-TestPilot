from pathlib import Path

from testpilot.agent.graph import build_graph
from testpilot.agent.nodes import AgentNodes
from testpilot.agent.state import AgentState, Status
from testpilot.config import AppConfig
from testpilot.llm.client import LLMClient
from testpilot.reporting.artifacts import ArtifactWriter
from testpilot.reporting.runs import create_run_directory, finalize_backend
from testpilot.runners.base import TestRunner
from testpilot.runners.factory import FallbackRunner


def run_project(
    project: str | Path,
    *,
    config: AppConfig | None = None,
    target: str | None = None,
    demo: bool = False,
    output: str | Path = "runs",
    client: LLMClient | None = None,
    runner: TestRunner | None = None,
    observer=None,
) -> AgentState:
    config = config or AppConfig()
    project_path = Path(project).resolve()
    directory = create_run_directory(
        Path(output), project_path.name, demo, config.execution.preferred_runner
    )
    artifacts = ArtifactWriter(directory)
    state = AgentState(
        project_path=str(project_path),
        requested_target=target,
        demo=demo,
        run_dir=str(artifacts.directory),
    )
    if demo and client is None:
        from testpilot.llm.fake import DemoLLM

        client = DemoLLM()
    nodes = AgentNodes(
        config, runner or FallbackRunner(config.execution), artifacts, client, observer
    )
    try:
        # Every tool visit also visits the controller. Retry limits determine the recursion bound.
        limit = 20 + 6 * (config.agent.max_repair_rounds + config.coverage.max_improvement_rounds)
        last = state.model_dump()
        for value in build_graph(nodes).stream(
            last, {"recursion_limit": limit}, stream_mode="values"
        ):
            last = value
        state = AgentState.model_validate(last)
    except Exception as exc:
        state = AgentState.model_validate(last)
        state.status = Status.FAILED
        state.error = f"WorkflowError: {type(exc).__name__}；流程安全终止"
        state.failure_stage = "GRAPH"
    if state.execution_result:
        artifacts.directory = finalize_backend(artifacts.directory, state.execution_result.backend)
        state.run_dir = str(artifacts.directory)
    artifacts.finish(state)
    return state
