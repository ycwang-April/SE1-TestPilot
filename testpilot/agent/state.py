from enum import StrEnum

from pydantic import BaseModel, Field

from testpilot.schemas.execution import CoverageResult, ExecutionResult
from testpilot.schemas.project import ModuleInfo, RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest, TestPlan


class Status(StrEnum):
    INITIALIZED = "INITIALIZED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    EXECUTING = "EXECUTING"
    REPAIRING = "REPAIRING"
    IMPROVING_COVERAGE = "IMPROVING_COVERAGE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Action(StrEnum):
    ANALYZE = "ANALYZE"
    PLAN = "PLAN"
    GENERATE = "GENERATE"
    EXECUTE = "EXECUTE"
    REPAIR = "REPAIR"
    IMPROVE_COVERAGE = "IMPROVE_COVERAGE"
    FINISH = "FINISH"
    FAIL = "FAIL"


class TraceEvent(BaseModel):
    step: int
    action: Action
    observation: str
    repair_count: int
    coverage_round: int


class AgentState(BaseModel):
    project_path: str
    requested_target: str | None = None
    repository: RepositoryInfo | None = None
    project_index: dict[str, ModuleInfo] = Field(default_factory=dict)
    target_modules: list[str] = Field(default_factory=list)
    selected_context: str = ""
    test_plan: list[TestPlan] = Field(default_factory=list)
    generated_tests: list[GeneratedTest] = Field(default_factory=list)
    execution_result: ExecutionResult | None = None
    execution_history: list[ExecutionResult] = Field(default_factory=list)
    coverage: CoverageResult | None = None
    repair_count: int = 0
    coverage_round: int = 0
    status: Status = Status.INITIALIZED
    history: list[TraceEvent] = Field(default_factory=list)
    current_action: Action = Action.ANALYZE
    error: str | None = None
    failure_stage: str | None = None
    warnings: list[str] = Field(default_factory=list)
    run_dir: str = ""
    demo: bool = False
