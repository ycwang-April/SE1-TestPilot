import io
import json
import stat
import zipfile

import pytest

from testpilot.agent.state import AgentState
from testpilot.errors import CoverageError, DependencyError, ProjectAnalysisError
from testpilot.tools.ast_analyzer import ASTAnalyzer
from testpilot.tools.context_selector import ContextSelector
from testpilot.tools.coverage_analyzer import CoverageAnalyzer
from testpilot.tools.dependencies import check_local_dependencies, requirements
from testpilot.tools.file_reader import FileReader
from testpilot.tools.repository_scanner import RepositoryScanner
from testpilot.tools.zip_project import extract_project


@pytest.mark.parametrize(
    "case,message", [("missing", "不存在"), ("empty", "空项目"), ("text", "没有 Python")]
)
def test_invalid_projects(tmp_path, case, message):
    root = tmp_path / case
    if case != "missing":
        root.mkdir()
    if case == "text":
        (root / "README.md").write_text("hello")
    with pytest.raises(ProjectAnalysisError, match=message):
        RepositoryScanner().scan(root)


def test_scan_filters_and_dependencies(project):
    for name in (".git", ".venv", "venv", "__pycache__", "build", "dist", "node_modules", "tests"):
        (project / name).mkdir()
        (project / name / "test_hidden.py").write_text("broken syntax")
    (project / "requirements.txt").write_text("# hello\npytest>=8\n")
    (project / "pyproject.toml").write_text('[project]\ndependencies=["coverage>=7"]\n')
    info = RepositoryScanner().scan(project)
    assert info.source_files == ["sample.py"]
    assert info.existing_tests == ["tests/test_hidden.py"]
    assert info.dependency_info == {
        "requirements.txt": ["pytest>=8"],
        "pyproject.toml": ["coverage>=7"],
    }


def test_syntax_error_names_file_and_line(project):
    (project / "sample.py").write_text("def broken(:\n")
    with pytest.raises(ProjectAnalysisError, match="SyntaxError: sample.py:1"):
        ASTAnalyzer().analyze(RepositoryScanner().scan(project))


def test_ast_classes_signatures_and_imports(project):
    (project / "sample.py").write_text('''"""Module docs."""
from other import inc
class Box:
    """A value box."""
    @staticmethod
    def value(x: int, /, *args, flag=True, **kwargs):
        """Return incremented positive inputs."""
        if x > 0:
            return inc(x)
        return 0
''')
    (project / "other.py").write_text("def inc(x):\n    return x+1\n")
    index = ASTAnalyzer().analyze(RepositoryScanner().scan(project))
    info = index["sample.py"]
    assert info.internal_dependencies == ["other.py"]
    method = info.classes[0].methods[0]
    assert method.decorators == ["staticmethod"]
    assert method.parameters == ["x", "flag", "args", "kwargs"]
    assert method.branches and method.docstring and info.docstring


def test_src_layout_relative_dependencies(project):
    package = project / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .other import inc\n")
    (package / "other.py").write_text("def inc(x): return x+1\n")
    (package / "main.py").write_text("from . import other\n")
    index = ASTAnalyzer().analyze(RepositoryScanner().scan(project))
    assert index["src/pkg/main.py"].module == "pkg.main"
    assert index["src/pkg/main.py"].internal_dependencies == [
        "src/pkg/__init__.py",
        "src/pkg/other.py",
    ]
    assert index["src/pkg/__init__.py"].internal_dependencies == ["src/pkg/other.py"]


def test_context_selection_and_budget(project):
    (project / "unrelated.py").write_text("PRIVATE_UNRELATED = 123\n")
    repo = RepositoryScanner().scan(project)
    state = AgentState(
        project_path=str(project),
        repository=repo,
        project_index=ASTAnalyzer().analyze(repo),
        target_modules=["sample.py"],
    )
    context = ContextSelector(60000).select(state, "PLAN", ["sample.py"])
    assert "PRIVATE_UNRELATED" not in context
    assert json.loads(context)["source"].keys() == {"sample.py"}
    with pytest.raises(ProjectAnalysisError, match="上下文"):
        ContextSelector(10).select(state, "PLAN", ["sample.py"])


def test_file_reader_blocks_traversal_and_size(project):
    with pytest.raises(ProjectAnalysisError, match="越界"):
        FileReader().read(project, "../secret.txt")
    with pytest.raises(ProjectAnalysisError, match="过大"):
        FileReader().read(project, "sample.py", 1)


def make_zip(names):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name in names:
            archive.writestr(name, "x = 1\n")
    return stream.getvalue()


@pytest.mark.parametrize(
    "name",
    ["../escape.py", "/root.py", "C:/root.py", "a\\..\\x.py", "NUL.py", "a /x.py", "a:stream.py"],
)
def test_zip_rejects_traversal(tmp_path, name):
    with pytest.raises(ProjectAnalysisError, match="不安全路径"):
        extract_project(make_zip(["safe.py", name]), tmp_path)
    assert not (tmp_path / "safe.py").exists()  # Validate everything before any writes.


def test_zip_valid_and_corrupt(tmp_path):
    root = extract_project(make_zip(["project/a.py"]), tmp_path)
    assert root == tmp_path / "project"
    with pytest.raises(ProjectAnalysisError, match="ZIP 损坏"):
        extract_project(b"broken", tmp_path)


def test_zip_symlink(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../outside")
    with pytest.raises(ProjectAnalysisError):
        extract_project(stream.getvalue(), tmp_path)


def test_zip_size_and_case_collision(tmp_path):
    with pytest.raises(ProjectAnalysisError, match="重复"):
        extract_project(make_zip(["A.py", "a.py"]), tmp_path)
    with pytest.raises(ProjectAnalysisError, match="限额"):
        extract_project(make_zip([f"{i}.py" for i in range(5001)]), tmp_path)


@pytest.mark.parametrize("data", [None, {}, {"files": {}}, {"files": {"sample.py": {}}}])
def test_coverage_bad_data(data):
    with pytest.raises(CoverageError):
        CoverageAnalyzer().analyze(data, ["sample.py"])


def test_weighted_coverage_and_no_branch():
    data = {
        "files": {
            "a.py": {
                "summary": {
                    "num_statements": 10,
                    "covered_lines": 5,
                    "num_branches": 0,
                    "covered_branches": 0,
                },
                "missing_lines": [1, 2, 3, 4, 5],
                "missing_branches": [],
            }
        }
    }
    result = CoverageAnalyzer().analyze(data, ["a.py"])
    assert result.line_coverage == 50 and result.branch_coverage == 100


def test_missing_dependency_is_explicit(project):
    (project / "requirements.txt").write_text("testpilot-nonexistent-dependency-394234>=1\n")
    with pytest.raises(DependencyError, match="缺失"):
        check_local_dependencies(RepositoryScanner().scan(project))


@pytest.mark.parametrize("entry", ["-r other.txt", "x @ https://example.com/x.whl", "-e ."])
def test_unsupported_dependency_directives(project, entry):
    (project / "requirements.txt").write_text(entry)
    with pytest.raises(DependencyError):
        requirements(RepositoryScanner().scan(project))


def test_malformed_pyproject(project):
    (project / "pyproject.toml").write_text("broken = [")
    with pytest.raises(ProjectAnalysisError, match="格式无效"):
        RepositoryScanner().scan(project)
