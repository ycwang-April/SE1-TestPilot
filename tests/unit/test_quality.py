import ast
import json
from pathlib import Path

import pytest

from testpilot.agent.state import AgentState, Status
from testpilot.config import ExecutionConfig
from testpilot.llm.fake import bundle
from testpilot.runners.local_runner import LocalTestRunner
from testpilot.runners.workspace import collect_result
from testpilot.schemas.test_plan import TestCasePlan as Case
from testpilot.schemas.test_plan import TestPlan as Plan
from testpilot.service import run_project
from testpilot.tools.ast_analyzer import ASTAnalyzer
from testpilot.tools.context_selector import ContextSelector
from testpilot.tools.plan_optimizer import optimize_plan
from testpilot.tools.repository_scanner import RepositoryScanner
from testpilot.tools.test_deduplicator import deduplicate_tests
from testpilot.tools.test_validator import count_test_functions


def case(**changes):
    values = dict(
        category="normal",
        description="absolute",
        target_symbol="absolute",
        input_strategy="zero",
        expected_behavior="returns zero",
    )
    return Case(**(values | changes))


def test_plan_merges_duplicate_categories_without_mutating_input():
    original = Plan(
        target="sample.py",
        cases=[
            case(),
            case(category="boundary", description="same boundary, differently phrased"),
        ],
    )
    optimized, notes = optimize_plan(original)
    assert len(optimized.cases) == 1 and notes
    assert optimized.cases[0].additional_categories == ["boundary"]
    assert len(original.cases) == 2 and original.cases[0].additional_categories == []


@pytest.mark.parametrize(
    "change",
    [
        dict(input_strategy="negative"),
        dict(setup="stock depleted"),
        dict(expected_behavior="raises ValueError"),
        dict(target_symbol="other"),
    ],
)
def test_plan_preserves_distinct_behavior(change):
    result, notes = optimize_plan(Plan(target="sample.py", cases=[case(), case(**change)]))
    assert len(result.cases) == 2 and not notes


@pytest.mark.parametrize("count", [13, 21, 40])
def test_complex_plan_has_no_count_limit(count):
    plan = Plan(
        target="service.py",
        cases=[
            case(
                target_symbol=f"Service.operation_{i}",
                setup=f"state {i}",
                expected_behavior=f"transition from state {i} to state {i + 1}",
            )
            for i in range(count)
        ],
    )
    result, notes = optimize_plan(plan)
    assert result == plan and len(result.cases) == count and not notes


@pytest.mark.parametrize(
    "first,second",
    [
        (dict(input_strategy="subtotal < 100"), dict(input_strategy="subtotal >= 100")),
        (
            dict(expected_behavior="raises OutOfStockError"),
            dict(expected_behavior="raises InvalidCouponError"),
        ),
        (
            dict(setup="pending order", expected_behavior="pending -> paid"),
            dict(setup="cancelled order", expected_behavior="cancelled unchanged"),
        ),
        (
            dict(category="interaction", expected_behavior="clock called once"),
            dict(category="interaction", expected_behavior="reserve called after quote"),
        ),
    ],
)
def test_semantic_boundaries_exceptions_states_and_interactions_survive(first, second):
    plan = Plan(target="service.py", cases=[case(**first), case(**second)])
    result, notes = optimize_plan(plan)
    assert result == plan and len(result.cases) == 2 and not notes


def test_large_plan_completes_workflow(project, local_config, tmp_path):
    # A module with 25 independent public contracts needs no count-based exemption.
    source = "\n".join(f"def operation_{i}(): return {i}" for i in range(25))
    (project / "sample.py").write_text(source)

    class Client:
        def plan(self, context):
            return Plan(
                target="sample.py",
                cases=[
                    case(target_symbol=f"operation_{i}", expected_behavior=f"returns {i}")
                    for i in range(25)
                ],
            )

        def generate(self, context, plan):
            assert len(plan.cases) == 25
            tests = "import sample\n" + "\n".join(
                f"def test_operation_{i}(): assert sample.operation_{i}() == {i}" for i in range(25)
            )
            return bundle("test_sample.py", tests)

    state = run_project(project, config=local_config, client=Client(), output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert state.execution_result.passed == 25
    assert state.repair_count == state.coverage_round == 0
    assert all("host isolation disabled" in warning for warning in state.warnings)


SOURCE = """import pytest
from sample import absolute
def test_zero():
    assert absolute(0) == 0
@pytest.mark.parametrize("x,expected", [(0, 0), (-2, 2), (-2, 2), (3, 3)])
def test_family(x, expected):
    assert absolute(x) == expected
"""


def test_explicit_boundary_wins_and_distinct_rows_survive_real_execution(project):
    original = bundle("test_sample.py", SOURCE).files
    files, notes = deduplicate_tests(original)
    tree = ast.parse(files[0].content)
    rows = ast.literal_eval(tree.body[-1].decorator_list[0].args[1])
    assert rows == [(-2, 2), (3, 3)] and notes
    assert original[0].content == SOURCE
    result = LocalTestRunner(ExecutionConfig()).run(
        project, RepositoryScanner().scan(project), files
    )
    assert count_test_functions(files[0].content) == 2
    assert result.collected_test_cases == result.passed == 3
    assert result.failed == result.errors == 0


def test_all_duplicate_rows_remove_only_parameter_function():
    source = SOURCE.replace("[(0, 0), (-2, 2), (-2, 2), (3, 3)]", "[(0, 0)]")
    files, _ = deduplicate_tests(bundle("test_sample.py", source).files)
    assert count_test_functions(files[0].content) == 1
    assert "def test_zero" in files[0].content
    ast.parse(files[0].content)


@pytest.mark.parametrize(
    "source",
    [
        SOURCE.replace("(0, 0), (-2, 2), (-2, 2), (3, 3)", "(0, 1), (-2, 2), (3, 3)"),
        SOURCE.replace(
            "def test_family(x, expected):", "def test_family(x, expected, monkeypatch):"
        ),
        SOURCE.replace("])\ndef test_family", "], ids=str)\ndef test_family"),
        SOURCE.replace("    assert absolute(x)", "    x = int(x)\n    assert absolute(x)"),
        SOURCE + "\ndef helper(): return 1\n",
        "def test_broken(:\n",
    ],
)
def test_uncertain_or_different_assertions_are_not_deleted(source):
    files, notes = deduplicate_tests(bundle("test_sample.py", source).files)
    assert files[0].content == source and not notes


def test_function_count_includes_classes_but_not_nested_helpers():
    source = """def test_one():
    def test_nested(): pass
class TestA:
    def test_same(self): pass
class TestB:
    def test_same(self): pass
class Helper:
    def test_not_collected(self): pass
"""
    assert count_test_functions(source) == 3
    assert count_test_functions("def broken(:") == 0


def test_workflow_applies_plan_and_code_dedup_before_execution(project, local_config, tmp_path):
    class Client:
        def plan(self, context):
            assert json.loads(context)["quality_policy"] == {
                "goal": "distinct behavior, not number of tests"
            }
            return Plan(target="sample.py", cases=[case(), case(category="boundary")])

        def generate(self, context, plan):
            assert len(plan.cases) == 1
            assert plan.cases[0].additional_categories == ["boundary"]
            return bundle("test_sample.py", SOURCE)

    state = run_project(project, config=local_config, client=Client(), output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert state.execution_result.collected_test_cases == 3
    assert any(w.startswith("Plan deduplicated:") for w in state.warnings)
    assert any(w.startswith("Test rows deduplicated:") for w in state.warnings)


@pytest.mark.parametrize("value", [None, True, -1, "3"])
def test_missing_or_invalid_collection_count_is_unknown(tmp_path, value):
    directory = tmp_path / ".testpilot"
    directory.mkdir()
    if value is not None:
        (directory / "collection.json").write_text(json.dumps({"collected_test_cases": value}))
    result = collect_result(tmp_path, (1, "", "", False, 0.1), "local")
    assert result.collected_test_cases is None
    assert any("collected_test_cases=null" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "source,collected,passed,failed,errors,skipped",
    [
        ("from missing_xyz import x\ndef test_x(): assert x\n", 0, 0, 0, 1, 0),
        ("def test_x(:\n", 0, 0, 0, 1, 0),
        (
            "import pytest\n@pytest.mark.skip(reason='example')\ndef test_x(): assert False\n",
            1,
            0,
            0,
            0,
            1,
        ),
        (
            "import pytest\n@pytest.fixture\ndef broken(): raise ValueError('setup')\ndef test_x(broken): assert broken\n",
            1,
            0,
            0,
            1,
            0,
        ),
        ("def test_x(): assert False\n", 1, 0, 1, 0, 0),
    ],
)
def test_collection_count_is_not_junit_pseudo_case_count(
    project, source, collected, passed, failed, errors, skipped
):
    result = LocalTestRunner(ExecutionConfig()).run(
        project, RepositoryScanner().scan(project), bundle("test_sample.py", source).files, False
    )
    assert (
        result.collected_test_cases,
        result.passed,
        result.failed,
        result.errors,
        result.skipped,
    ) == (collected, passed, failed, errors, skipped)


DEPENDENCIES = {
    "errors.py": [],
    "models.py": ["errors.py"],
    "inventory.py": ["errors.py", "models.py"],
    "coupon.py": ["errors.py", "models.py"],
    "pricing.py": ["coupon.py", "errors.py", "inventory.py", "models.py"],
    "order_service.py": ["coupon.py", "inventory.py", "models.py", "pricing.py"],
}


def test_advanced_index_and_dependency_context(example_root):
    project = example_root / "advanced_project"
    repo = RepositoryScanner().scan(project)
    index = ASTAnalyzer().analyze(repo)
    assert set(repo.source_files) == set(DEPENDENCIES)
    assert {name: module.internal_dependencies for name, module in index.items()} == DEPENDENCIES
    assert {c.name for c in index["models.py"].classes} == {
        "Product",
        "OrderLine",
        "CustomerLevel",
        "CouponType",
    }
    state = AgentState(project_path=str(project), repository=repo, project_index=index)
    context = json.loads(ContextSelector(60000).select(state, "PLAN", ["order_service.py"]))
    assert set(context["related_source"]) == set(DEPENDENCIES["order_service.py"])
    assert "class OrderLine" in context["related_source"]["models.py"]
    assert context["quality_policy"] == {"goal": "distinct behavior, not number of tests"}
    state.test_plan = [Plan(target="models.py", cases=[case()])]
    state.generated_tests = bundle("test_previous.py", SOURCE).files
    generating = json.loads(ContextSelector(60000).select(state, "GENERATE", ["order_service.py"]))
    assert generating["existing_plans"][0]["target"] == "models.py"
    assert generating["existing_tests"][0]["content"] == SOURCE


def test_advanced_offline_workflow_and_report(example_root, local_config, tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    project = example_root / "advanced_project"
    before = {p.name: p.read_bytes() for p in project.glob("*.py")}
    state = run_project(project, demo=True, config=local_config, output=tmp_path / "runs")
    assert state.status == Status.COMPLETED, state.error
    assert state.execution_result.backend == "local"
    assert state.coverage.line_coverage >= 80 and state.coverage.branch_coverage >= 70
    assert state.repair_count == state.coverage_round == 0
    report = json.loads((Path(state.run_dir) / "final_report.json").read_text(encoding="utf-8"))
    assert report["generated_test_functions"] == sum(
        count_test_functions(t.content) for t in state.generated_tests
    )
    assert report["generated_tests"] == report["generated_test_functions"]
    assert report["collected_test_cases"] == report["passed"] == state.execution_result.passed
    assert report["collected_test_cases"] > report["generated_test_functions"]
    assert report["failed"] == report["errors"] == 0
    assert {p.name: p.read_bytes() for p in project.glob("*.py")} == before
