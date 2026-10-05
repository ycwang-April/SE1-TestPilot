import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from testpilot.config import ExecutionConfig
from testpilot.errors import DependencyError, DockerUnavailableError
from testpilot.runners.base import TestRunner
from testpilot.runners.process import run_process
from testpilot.runners.workspace import collect_result, prepare_workspace, pytest_args
from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.tools.dependencies import requirements


class DockerTestRunner(TestRunner):
    def __init__(self, config: ExecutionConfig):
        self.config = config

    def probe(self) -> None:
        if not shutil.which("docker"):
            raise DockerUnavailableError("Docker 未安装或不在 PATH")
        try:
            for args in (
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                ["docker", "image", "inspect", self.config.docker_image],
            ):
                result = subprocess.run(args, capture_output=True, timeout=10, check=False)
                if result.returncode:
                    raise DockerUnavailableError(
                        "Docker daemon 不可用或 runner image 未构建；运行 docker build -t testpilot-runner:latest ."
                    )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DockerUnavailableError("Docker 初始化超时或不可用") from exc

    def _remove(self, name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def run(
        self,
        project: Path,
        repo: RepositoryInfo,
        tests: list[GeneratedTest],
        coverage_enabled: bool = True,
    ) -> ExecutionResult:
        self.probe()
        with tempfile.TemporaryDirectory(prefix="testpilot-docker-") as directory:
            work = Path(directory)
            prepare_workspace(project, work, repo, tests)
            name = "testpilot-" + uuid.uuid4().hex
            mount = ["--mount", f"type=bind,source={work},target=/work", "-w", "/work"]
            try:
                if self.config.install_dependencies:
                    deps = [str(r) for r in requirements(repo)]
                    if deps:
                        (work / ".testpilot" / "dependencies.txt").write_text(
                            "\n".join(deps), encoding="utf-8"
                        )
                        install = [
                            "docker",
                            "run",
                            "--name",
                            name + "-install",
                            "--rm",
                            *mount,
                            self.config.docker_image,
                            "python",
                            "-m",
                            "pip",
                            "install",
                            "--target",
                            ".testpilot/deps",
                            "-r",
                            ".testpilot/dependencies.txt",
                        ]
                        outcome = run_process(
                            install, work, dict(os.environ), self.config.install_timeout_seconds
                        )
                        if outcome[0] or outcome[3]:
                            raise DependencyError(
                                "Docker 依赖安装失败或超时: " + outcome[2][-1000:]
                            )
                command = [
                    "docker",
                    "run",
                    "--name",
                    name,
                    "--rm",
                    "--network=none",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=128",
                    "--memory=512m",
                    "--cpus=1",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,size=128m",
                    *mount,
                    "-e",
                    "PYTHONPATH=/work:/work/src:/work/.testpilot/deps",
                    "-e",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                    "-e",
                    "PYTHONDONTWRITEBYTECODE=1",
                    self.config.docker_image,
                    "python",
                    *pytest_args(coverage_enabled),
                ]
                outcome = run_process(command, work, dict(os.environ), self.config.timeout_seconds)
                if outcome[0] in (125, 126, 127) and not outcome[3]:
                    raise DockerUnavailableError("Docker 容器启动失败: " + outcome[2][-500:])
                return collect_result(work, outcome, "docker")
            finally:
                self._remove(name)
                self._remove(name + "-install")
