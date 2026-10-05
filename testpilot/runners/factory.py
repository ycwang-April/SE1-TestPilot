from pathlib import Path

from testpilot.config import ExecutionConfig
from testpilot.errors import DockerUnavailableError
from testpilot.runners.base import TestRunner
from testpilot.runners.docker_runner import DockerTestRunner
from testpilot.runners.local_runner import LocalTestRunner
from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest


class FallbackRunner(TestRunner):
    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.docker = DockerTestRunner(config)
        self.local = LocalTestRunner(config)

    def run(
        self,
        project: Path,
        repo: RepositoryInfo,
        tests: list[GeneratedTest],
        coverage_enabled: bool = True,
    ) -> ExecutionResult:
        if self.config.preferred_runner == "local":
            return self.local.run(project, repo, tests, coverage_enabled)
        try:
            return self.docker.run(project, repo, tests, coverage_enabled)
        except DockerUnavailableError as exc:
            if not self.config.allow_local_fallback:
                raise
            result = self.local.run(project, repo, tests, coverage_enabled)
            result.warnings.insert(0, f"Docker fallback: {exc}")
            return result
