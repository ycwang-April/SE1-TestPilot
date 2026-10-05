import os
import tomllib
from pathlib import Path

from testpilot.errors import ProjectAnalysisError
from testpilot.schemas.project import RepositoryInfo
from testpilot.tools.file_reader import FileReader

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "runs",
    ".testpilot",
    "htmlcov",
    "submission",
}


class RepositoryScanner:
    def scan(self, path: str | Path) -> RepositoryInfo:
        root = Path(path).resolve()
        if not root.is_dir():
            raise ProjectAnalysisError(f"项目目录不存在或不是目录: {root}")
        info = RepositoryInfo(project_path=str(root))
        for parent, dirs, files in os.walk(root):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in EXCLUDED
                and not d.startswith(".")
                and not (Path(parent) / d).is_symlink()
            )
            for name in sorted(files):
                item = Path(parent) / name
                if item.is_symlink() or name.startswith("."):
                    continue
                relative = item.relative_to(root).as_posix()
                if len(info.project_structure) >= 5000:
                    raise ProjectAnalysisError("项目超过 5000 个文件，请缩小输入目录")
                info.project_structure.append(relative)
                if item.suffix == ".py":
                    is_test = (
                        "tests" in item.relative_to(root).parts
                        or name.startswith("test_")
                        or name.endswith("_test.py")
                        or name == "conftest.py"
                    )
                    (info.existing_tests if is_test else info.source_files).append(relative)
        if not info.project_structure:
            raise ProjectAnalysisError("空项目：目录没有可分析文件")
        if not info.source_files:
            raise ProjectAnalysisError("项目中没有 Python 源文件（已有测试不计为源码）")
        reader = FileReader()
        if "requirements.txt" in info.project_structure:
            text = reader.read(root, "requirements.txt")
            info.dependency_info["requirements.txt"] = [
                s.strip() for s in text.splitlines() if s.strip() and not s.lstrip().startswith("#")
            ]
        if "pyproject.toml" in info.project_structure:
            try:
                raw = tomllib.loads(reader.read(root, "pyproject.toml"))
                deps = raw.get("project", {}).get("dependencies", [])
                if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
                    raise ValueError("project.dependencies must be a list of strings")
                info.dependency_info["pyproject.toml"] = deps
            except (tomllib.TOMLDecodeError, ValueError, AttributeError) as exc:
                raise ProjectAnalysisError("pyproject.toml 格式无效") from exc
        return info
