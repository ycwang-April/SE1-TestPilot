"""Remove only static duplicate parameter rows within one uncomplicated module.

Never merge different constants/expected values, fixtures, markers, classes, setups,
multiple assertions, pytest.param IDs, stacked/indirect parametrization or separate files.
Keep explicit boundary functions in preference to identical parametrized rows.
"""

import ast
import copy

from testpilot.schemas.test_plan import GeneratedTest


def _literal(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError):
        return False


def _assertion_key(node: ast.FunctionDef, bindings: dict[str, ast.AST]) -> str | None:
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Assert):
        return None
    assertion = copy.deepcopy(node.body[0])

    class Substitute(ast.NodeTransformer):
        def visit_Name(self, value):
            return copy.deepcopy(bindings.get(value.id, value))

    assertion = Substitute().visit(assertion)
    expr = assertion.test
    if assertion.msg is not None or not isinstance(expr, ast.Compare) or len(expr.ops) != 1:
        return None
    call = expr.left
    if (
        not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or not all(_literal(arg) for arg in call.args)
        or not all(kw.arg is not None and _literal(kw.value) for kw in call.keywords)
        or not all(_literal(arg) for arg in expr.comparators)
    ):
        return None
    return ast.dump(assertion, include_attributes=False)


def deduplicate_tests(tests: list[GeneratedTest]) -> tuple[list[GeneratedTest], list[str]]:
    output, notes = [], []
    for test in tests:
        try:
            tree = ast.parse(test.content)
        except SyntaxError:
            output.append(test)  # Preserve the real pytest SyntaxError -> repair path.
            continue
        # Module-level mutable state, fixtures, classes or helper setup may change semantics.
        if any(not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef)) for n in tree.body):
            output.append(test)
            continue
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        if any(not n.name.startswith("test_") for n in functions):
            output.append(test)
            continue
        explicit = set()
        candidates = []
        for fn in functions:
            if (
                fn.args.defaults
                or fn.args.kwonlyargs
                or fn.args.posonlyargs
                or fn.args.vararg
                or fn.args.kwarg
            ):
                continue
            if not fn.decorator_list and not fn.args.args:
                key = _assertion_key(fn, {})
                if key:
                    explicit.add(key)
            if len(fn.decorator_list) != 1:
                continue
            dec = fn.decorator_list[0]
            if (
                not isinstance(dec, ast.Call)
                or ast.unparse(dec.func) != "pytest.mark.parametrize"
                or len(dec.args) != 2
                or dec.keywords
                or not isinstance(dec.args[0], ast.Constant)
                or not isinstance(dec.args[0].value, str)
                or not isinstance(dec.args[1], (ast.List, ast.Tuple))
            ):
                continue
            names = [name.strip() for name in dec.args[0].value.split(",")]
            if set(names) != {a.arg for a in fn.args.args} or len(set(names)) != len(names):
                continue
            rows = dec.args[1].elts
            if len(rows) > 256:
                continue
            keyed = []
            for row in rows:
                values = (
                    [row]
                    if len(names) == 1
                    else row.elts
                    if isinstance(row, (ast.Tuple, ast.List))
                    else []
                )
                if len(values) != len(names) or not all(_literal(value) for value in values):
                    break
                key = _assertion_key(fn, dict(zip(names, values, strict=True)))
                if key is None:
                    break
                keyed.append((row, key))
            else:
                candidates.append((fn, dec, keyed))
        seen = set(explicit)
        edits = []
        lines = test.content.splitlines(keepends=True)

        # AST columns are UTF-8 byte offsets. Convert to character positions for safe splicing.
        def offset(line, column):
            return sum(len(s) for s in lines[: line - 1]) + len(
                lines[line - 1].encode()[:column].decode()
            )

        for fn, dec, rows in candidates:
            kept = []
            for row, key in rows:
                if key not in seen:
                    kept.append(row)
                    seen.add(key)
            if len(kept) == len(rows):
                continue
            notes.append(f"Test rows deduplicated: {test.path}::{fn.name}: {len(rows) - len(kept)}")
            if kept:
                arg = dec.args[1]
                edits.append(
                    (
                        offset(arg.lineno, arg.col_offset),
                        offset(arg.end_lineno, arg.end_col_offset),
                        "[" + ", ".join(ast.unparse(row) for row in kept) + "]",
                    )
                )
            else:
                edits.append((offset(dec.lineno, 0), offset(fn.end_lineno, fn.end_col_offset), ""))
        content = test.content
        for start, end, replacement in sorted(edits, reverse=True):
            content = content[:start] + replacement + content[end:]
        output.append(test.model_copy(update={"content": content}))
    return output, notes
