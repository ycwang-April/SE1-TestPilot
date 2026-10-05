import ast
from pathlib import Path

from testpilot.errors import ProjectAnalysisError
from testpilot.schemas.project import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ModuleInfo,
    RepositoryInfo,
)
from testpilot.tools.file_reader import FileReader

BRANCHES = (ast.If, ast.For, ast.While, ast.Try, ast.Match, ast.IfExp)


def module_name(path: str) -> str:
    parts = list(Path(path).with_suffix("").parts)
    if parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    return FunctionInfo(
        name=node.name,
        signature=f"{node.name}({ast.unparse(node.args)})",
        parameters=[a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
        + ([node.args.vararg.arg] if node.args.vararg else [])
        + ([node.args.kwarg.arg] if node.args.kwarg else []),
        decorators=[ast.unparse(d) for d in node.decorator_list],
        docstring=ast.get_docstring(node),
        lineno=node.lineno,
        branches=[n.lineno for n in ast.walk(node) if isinstance(n, BRANCHES)],
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


class ASTAnalyzer:
    def analyze(self, repo: RepositoryInfo) -> dict[str, ModuleInfo]:
        index = {}
        for path in repo.source_files:
            try:
                tree = ast.parse(FileReader().read(Path(repo.project_path), path), filename=path)
            except SyntaxError as exc:
                raise ProjectAnalysisError(f"SyntaxError: {path}:{exc.lineno}: {exc.msg}") from exc
            mod = ModuleInfo(path=path, module=module_name(path), docstring=ast.get_docstring(tree))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mod.functions.append(function_info(node))
                elif isinstance(node, ast.ClassDef):
                    mod.classes.append(
                        ClassInfo(
                            name=node.name,
                            bases=[ast.unparse(b) for b in node.bases],
                            decorators=[ast.unparse(d) for d in node.decorator_list],
                            docstring=ast.get_docstring(node),
                            methods=[
                                function_info(n)
                                for n in node.body
                                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                            ],
                        )
                    )
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mod.imports.extend(
                        ImportInfo(module=a.name, names=[a.asname or a.name]) for a in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    mod.imports.append(
                        ImportInfo(
                            module=node.module or "",
                            level=node.level,
                            names=[a.name for a in node.names],
                        )
                    )
                if isinstance(node, BRANCHES):
                    mod.branches.append(node.lineno)
            index[path] = mod
        for mod in index.values():
            dependencies = set()
            package = (
                mod.module.split(".")
                if mod.path.endswith("__init__.py")
                else mod.module.split(".")[:-1]
            )
            for imp in mod.imports:
                prefix = package[: len(package) - imp.level + 1] if imp.level else []
                base = ".".join(prefix + ([imp.module] if imp.module else []))
                names = [base] + [f"{base}.{n}".strip(".") for n in imp.names]
                for candidate in index.values():
                    if candidate.path != mod.path and candidate.module in names:
                        dependencies.add(candidate.path)
            mod.internal_dependencies = sorted(dependencies)
        return index
