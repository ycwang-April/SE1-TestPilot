import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from testpilot.schemas.execution import ExecutionResult
from testpilot.schemas.project import RepositoryInfo
from testpilot.schemas.test_plan import GeneratedTest


def prepare_workspace(
    project: Path, work: Path, repo: RepositoryInfo, tests: list[GeneratedTest]
) -> None:
    # Copy the scanner's bounded inventory. Hidden files and symlinks never enter this list.
    total = 0
    for relative in repo.project_structure:
        source = project / relative
        if source.is_symlink() or not source.resolve().is_relative_to(project.resolve()):
            raise ValueError(f"Unsafe source path: {relative}")
        total += source.stat().st_size
        if total > 50_000_000:
            raise ValueError("项目复制大小超过 50 MB")
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    generated = work / ".testpilot" / "generated_tests"
    generated.mkdir(parents=True)
    # Collection count is not JUnit element count: collection failures can create pseudo-cases.
    (generated / "conftest.py").write_text(
        "import json\nfrom pathlib import Path\n\n"
        "def pytest_collection_finish(session):\n"
        "    destination = Path(__file__).parents[1] / 'collection.json'\n"
        "    destination.write_text(json.dumps({'collected_test_cases': len(session.items)}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    for test in tests:
        (generated / test.path).write_text(test.content, encoding="utf-8")
    (work / ".testpilot" / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (work / ".testpilot" / "coverage.ini").write_text(
        "[run]\nbranch = True\nrelative_files = True\n"
        "omit =\n    .testpilot/*\n    tests/*\n    */tests/*\n    */test_*.py\n"
        "    test_*.py\n    conftest.py\n    */conftest.py\n",
        encoding="utf-8",
    )


def pytest_args(coverage_enabled: bool) -> list[str]:
    args = [
        "-m",
        "pytest",
        "-q",
        "-c",
        ".testpilot/pytest.ini",
        "--rootdir=.",
        "--confcutdir=.testpilot/generated_tests",
        "--import-mode=importlib",
        "-o",
        "cache_dir=.testpilot/cache",
        "--junitxml=.testpilot/junit.xml",
        ".testpilot/generated_tests",
    ]
    if coverage_enabled:
        args += [
            "-p",
            "pytest_cov",
            "--cov=.",
            "--cov-branch",
            "--cov-config=.testpilot/coverage.ini",
            "--cov-report=json:.testpilot/coverage.json",
        ]
    return args


def collect_result(work: Path, process: tuple, backend: str) -> ExecutionResult:
    code, stdout, stderr, timed_out, duration = process
    result = ExecutionResult(
        returncode=code,
        stdout=stdout,
        stderr=stderr,
        traceback=(stdout + "\n" + stderr)[-16000:] if code else "",
        timed_out=timed_out,
        backend=backend,
        duration_seconds=duration,
    )
    if timed_out:
        result.traceback = "pytest timeout: 执行超过配置时限\n" + result.traceback
    try:
        collected = json.loads(
            (work / ".testpilot" / "collection.json").read_text(encoding="utf-8")
        )["collected_test_cases"]
        if type(collected) is not int or collected < 0:
            raise ValueError("invalid collection count")
        result.collected_test_cases = collected
    except (OSError, ValueError, KeyError, TypeError):
        result.warnings.append(
            "pytest collection 统计不可用；collected_test_cases=null，不从 passed 推测"
        )
    try:
        root = ET.parse(work / ".testpilot" / "junit.xml").getroot()
        for case in root.iter("testcase"):
            if case.find("failure") is not None:
                result.failed += 1
            elif case.find("error") is not None:
                result.errors += 1
            elif case.find("skipped") is not None:
                result.skipped += 1
            else:
                result.passed += 1
    except (OSError, ET.ParseError):
        result.warnings.append("pytest JUnit 结果缺失；保留原始 returncode/stdout/stderr")
    try:
        result.coverage_data = json.loads(
            (work / ".testpilot" / "coverage.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        pass
    return result
