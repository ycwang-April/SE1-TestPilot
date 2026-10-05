"""Regression coverage for false positives in generated assertion validation."""

import pytest

from testpilot.config import ExecutionConfig
from testpilot.errors import LLMOutputValidationError
from testpilot.runners.local_runner import LocalTestRunner
from testpilot.schemas.test_plan import GeneratedTest
from testpilot.tools.repository_scanner import RepositoryScanner
from testpilot.tools.test_validator import validate_tests


@pytest.mark.parametrize(
    "expression", ["True", "1", "'nonempty'", "1 == 1", "1 == True", "None == None"]
)
def test_literal_truth_is_still_rejected_with_location(expression):
    test = GeneratedTest(
        path="test_example.py", content=f"def test_example():\n    assert {expression}\n"
    )
    with pytest.raises(LLMOutputValidationError, match=r"test_example.py:2:.*恒真"):
        validate_tests([test])


@pytest.mark.parametrize(
    "expression",
    [
        'Product("A", Decimal("1.00")) == Product("A", Decimal("1.00"))',
        'OrderLine("A", 2) == OrderLine("A", 2)',
        "next(values) != next(values)",
        "clock() < clock()",
        "obj.value == obj.value",
        "items[0] == items[0]",
        "value == value",
        "value != value",
        "value < value",
        "False",
        "1 != 1",
        "1 < 1",
        "1 > 1",
    ],
)
def test_runtime_comparisons_and_false_assertions_reach_pytest(expression):
    validate_tests(
        [
            GeneratedTest(
                path="test_example.py", content=f"def test_example():\n    assert {expression}\n"
            )
        ]
    )


def test_dataclass_value_semantics_and_stateful_calls_execute(example_root):
    project = example_root / "advanced_project"
    tests = [
        GeneratedTest(
            path="test_value_semantics.py",
            content="""
from decimal import Decimal
from models import Product, OrderLine


def test_product_value_semantics():
    assert Product("A", Decimal("1.00")) == Product("A", Decimal("1.00"))
    assert Product("A", Decimal("1.00")) != Product("A", Decimal("2.00"))


def test_orderline_value_semantics():
    assert OrderLine("A", 2) == OrderLine("A", 2)
    assert OrderLine("A", 2) != OrderLine("A", 3)


def test_stateful_calls():
    values = iter([1, 2])
    assert next(values) < next(values)


def test_non_reflexive_equality():
    value = float("nan")
    assert value != value
""",
        )
    ]
    validate_tests(tests)
    result = LocalTestRunner(ExecutionConfig()).run(
        project, RepositoryScanner().scan(project), tests, coverage_enabled=False
    )
    assert result.returncode == 0, result.traceback
    assert result.passed == 4


def test_false_literal_comparison_preserves_real_failure(project):
    tests = [GeneratedTest(path="test_failure.py", content="def test_failure(): assert 1 != 1")]
    validate_tests(tests)
    result = LocalTestRunner(ExecutionConfig()).run(
        project, RepositoryScanner().scan(project), tests, coverage_enabled=False
    )
    assert result.returncode != 0
    assert result.failed == 1
    assert "AssertionError" in result.traceback
