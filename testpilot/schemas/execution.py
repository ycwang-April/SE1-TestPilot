from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    returncode: int
    stdout: str = ""
    stderr: str = ""
    traceback: str = ""
    backend: str = "local"
    timed_out: bool = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    collected_test_cases: int | None = Field(default=None, ge=0)
    duration_seconds: float = 0
    coverage_data: dict | None = None
    warnings: list[str] = Field(default_factory=list)


class CoverageResult(BaseModel):
    line_coverage: float
    branch_coverage: float
    missing_lines: dict[str, list[int]] = Field(default_factory=dict)
    missing_branches: dict[str, list[list[int]]] = Field(default_factory=dict)
