import ast

from testpilot.errors import LLMOutputValidationError
from testpilot.schemas.test_plan import GeneratedTest


def test_names(content: str) -> set[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()  # Execute malformed output to collect the real pytest traceback for repair.
    return set(_test_definitions(tree))


def _test_definitions(tree: ast.Module) -> dict:
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    result = {}
    for node in tree.body:
        if isinstance(node, functions) and node.name.startswith("test_"):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for method in node.body:
                if isinstance(method, functions) and method.name.startswith("test_"):
                    result[f"{node.name}.{method.name}"] = method
    return result


def _parameter_rows(content: str) -> dict[str, list[int]]:
    try:
        definitions = _test_definitions(ast.parse(content))
    except SyntaxError:
        return {}
    return {
        name: [
            len(decorator.args[1].elts)
            for decorator in function.decorator_list
            if isinstance(decorator, ast.Call)
            and ast.unparse(decorator.func) == "pytest.mark.parametrize"
            and len(decorator.args) >= 2
            and isinstance(decorator.args[1], (ast.List, ast.Tuple))
        ]
        for name, function in definitions.items()
    }


def count_test_functions(content: str) -> int:
    """Count definitions, including identically named methods in different test classes."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    return sum(
        1
        if isinstance(node, functions) and node.name.startswith("test_")
        else sum(
            isinstance(method, functions) and method.name.startswith("test_")
            for method in node.body
        )
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test")
        else 0
        for node in tree.body
    )


def _obviously_true(expression: ast.expr) -> bool:
    """Reject only literal truths; identical syntax does not establish runtime equality.

    Calls may construct separate objects or consume state. Even x == x can be a
    meaningful check for NaN or overloaded equality, so unknown values go to pytest.
    """
    if isinstance(expression, ast.Constant):
        return bool(expression.value)
    if isinstance(expression, ast.BoolOp):
        values = [_obviously_true(value) for value in expression.values]
        return any(values) if isinstance(expression.op, ast.Or) else all(values)
    return (
        isinstance(expression, ast.Compare)
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.Eq)
        and isinstance(expression.left, ast.Constant)
        and isinstance(expression.comparators[0], ast.Constant)
        and expression.left.value == expression.comparators[0].value
    )


def validate_tests(tests: list[GeneratedTest]) -> None:
    if not tests:
        raise LLMOutputValidationError("LLM 返回空测试")
    names = [t.path.casefold() for t in tests]
    if len(names) != len(set(names)):
        raise LLMOutputValidationError("测试文件名冲突")
    for test in tests:
        try:
            tree = ast.parse(test.content)
        except SyntaxError:
            continue
        if not test_names(test.content):
            raise LLMOutputValidationError(f"{test.path} 没有 pytest 测试函数")
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and _obviously_true(node.test):
                raise LLMOutputValidationError(
                    f"{test.path}:{node.lineno}: 拒绝恒真断言；请生成有意义的行为验证"
                )
            if isinstance(node, ast.Call) and ast.unparse(node.func) in (
                "pytest.skip",
                "pytest.xfail",
            ):
                raise LLMOutputValidationError("生成的测试不允许主动 skip/xfail")


def retain_tests(previous: list[GeneratedTest], repaired: list[GeneratedTest]) -> None:
    current = {t.path: t for t in repaired}
    missing = []
    for old in previous:
        if old.path not in current:
            missing.append(f"缺少文件 {old.path}")
            continue
        removed = sorted(test_names(old.content) - test_names(current[old.path].content))
        if removed:
            missing.append(f"{old.path} 缺少函数: {', '.join(removed)}")
        new_rows = _parameter_rows(current[old.path].content)
        for name, counts in _parameter_rows(old.content).items():
            current_counts = new_rows.get(name, [])
            if counts and (
                len(counts) != len(current_counts)
                or any(new < before for before, new in zip(counts, current_counts))
            ):
                missing.append(f"{old.path}::{name} 不得减少已有参数化用例")
    if missing:
        raise LLMOutputValidationError("修复不得删除已有测试文件/测试函数；" + "; ".join(missing))
