import sys
import tempfile
from pathlib import Path

from testpilot.config import ExecutionConfig
from testpilot.errors import DependencyError, TestExecutionError
from testpilot.runners.base import TestRunner
from testpilot.runners.process import execution_env, run_process
from testpilot.runners.workspace import collect_result, prepare_workspace, pytest_args
from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.tools.dependencies import check_local_dependencies


class LocalTestRunner(TestRunner):
    def __init__(self, config: ExecutionConfig):
        self.config = config

    def run(
        self,
        project: Path,
        repo: RepositoryInfo,
        tests: list[GeneratedTest],
        coverage_enabled: bool = True,
    ) -> ExecutionResult:
        if self.config.install_dependencies:
            raise DependencyError("依赖自动安装只允许在 Docker；LocalRunner 不会安装或更改宿主依赖")
        check_local_dependencies(repo)
        try:
            with tempfile.TemporaryDirectory(prefix="testpilot-run-") as directory:
                work = Path(directory)
                prepare_workspace(project, work, repo, tests)
                process = run_process(
                    [sys.executable, *pytest_args(coverage_enabled)],
                    work,
                    execution_env(work),
                    self.config.timeout_seconds,
                )
                result = collect_result(work, process, "local")
                result.warnings.append("host isolation disabled: LocalRunner 只适用于可信代码")
                return result
        except (OSError, ValueError) as exc:
            raise TestExecutionError(f"本地执行环境失败: {type(exc).__name__}: {exc}") from exc
