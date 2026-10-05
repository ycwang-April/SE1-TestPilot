from abc import ABC, abstractmethod
from pathlib import Path

from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest


class TestRunner(ABC):
    @abstractmethod
    def run(
        self,
        project: Path,
        repo: RepositoryInfo,
        tests: list[GeneratedTest],
        coverage_enabled: bool = True,
    ) -> ExecutionResult:
        """Execute tests in a disposable copy, leaving the input project untouched."""
