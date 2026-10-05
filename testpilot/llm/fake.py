"""Explicit demo fixtures. These never claim to infer arbitrary project behavior."""

import hashlib
import json

from testpilot.errors import ConfigurationError
from testpilot.llm import advanced_demo
from testpilot.llm.advanced_hashes import ADVANCED_HASHES
from testpilot.llm.demo_hashes import DEMO_HASHES
from testpilot.schemas.test_plan import GeneratedTest, TestBundle, TestCasePlan, TestPlan

BASIC = """import pytest
from calculator import divide, clamp

def test_divide():
    assert divide(6, 3) == 2
    assert divide(0, 3) == 0
    assert divide(-6, 3) == -2
    with pytest.raises(ValueError, match="zero"):
        divide(1, 0)
    with pytest.raises(TypeError):
        divide("bad", 2)

@pytest.mark.parametrize("value,expected", [(-1, 0), (0, 0), (3, 3), (5, 5), (6, 5)])
def test_clamp(value, expected):
    assert clamp(value, 0, 5) == expected

def test_invalid_bounds():
    with pytest.raises(ValueError, match="lower"):
        clamp(1, 5, 0)
"""

MODELS = """import pytest
from models import Item

def test_subtotal():
    assert Item(10, 2).subtotal() == 20
    assert Item(3).subtotal() == 3
    assert Item(0, 0).subtotal() == 0

@pytest.mark.parametrize("price,quantity", [(-1, 2), (2, -1)])
def test_invalid_item(price, quantity):
    with pytest.raises(ValueError):
        Item(price, quantity).subtotal()
"""

DISCOUNT = """import pytest
from discount import discount_rate

@pytest.mark.parametrize("total,member,expected", [(0, False, 0), (99.99, False, 0), (100, False, .1), (101, False, .1), (0, True, .2)])
def test_rates(total, member, expected):
    assert discount_rate(total, member) == expected

def test_negative_total():
    with pytest.raises(ValueError):
        discount_rate(-1)
"""

ORDER = """import pytest
from models import Item
from order import order_total

def test_interaction():
    assert order_total([Item(50, 2)]) == 90
    assert order_total([Item(30)], member=True) == 24
    assert order_total([]) == 0
    assert order_total([Item(1.23, 3)]) == 3.69

def test_invalid_order():
    with pytest.raises(ValueError):
        order_total([Item(-1)])
"""

EDGE_INITIAL = """from shipping import shipping_fee

def test_regular_small():
    assert shipping_fee(1) == 99
"""
EDGE_REPAIRED = EDGE_INITIAL.replace("== 99", "== 5")
EDGE_EXTRA = """import pytest
from shipping import shipping_fee

@pytest.mark.parametrize("weight,express,expected", [(0.1, False, 5), (1, True, 13), (1.01, False, 10), (5, True, 18), (5.01, False, 20), (10, True, 28)])
def test_other_paths(weight, express, expected):
    assert shipping_fee(weight, express) == expected

@pytest.mark.parametrize("weight", [0, -1])
def test_invalid_weight(weight):
    with pytest.raises(ValueError, match="positive"):
        shipping_fee(weight)
"""

DEMO_TESTS = {
    "calculator.py": BASIC,
    "models.py": MODELS,
    "discount.py": DISCOUNT,
    "order.py": ORDER,
    "shipping.py": EDGE_INITIAL,
}


def bundle(filename: str, content: str) -> TestBundle:
    return TestBundle(files=[GeneratedTest(path=filename, content=content)])


class DemoLLM:
    """Deterministic scripted model limited to the unmodified bundled examples."""

    def _target(self, context: str) -> str:
        data = json.loads(context)
        target = data["targets"][0]
        digest = hashlib.sha256(data["source"][target].encode()).hexdigest()
        if DEMO_HASHES.get(target) != digest and ADVANCED_HASHES.get(target) != digest:
            raise ConfigurationError(
                "Demo 只支持未修改的内置示例；任意项目请配置 DeepSeek Key 并移除 --demo"
            )
        return target

    def plan(self, context: str) -> TestPlan:
        target = self._target(context)
        if self._advanced(context, target):
            return advanced_demo.plan_for(target)
        return TestPlan(
            target=target,
            cases=[
                TestCasePlan(
                    category=category,
                    description=f"Demo fixture: {category} behavior for {target}",
                    target_symbol=target.removesuffix(".py"),
                    input_strategy="Use deterministic example inputs",
                    expected_behavior="Match the example's documented contract",
                    priority=1,
                )
                for category in (
                    "normal",
                    "boundary",
                    "exception",
                    "invalid",
                    "branch",
                    "interaction",
                )
            ],
        )

    def generate(self, context: str, plan: TestPlan) -> TestBundle:
        target = self._target(context)
        if self._advanced(context, target):
            return bundle("test_advanced_" + target, advanced_demo.TESTS[target])
        return bundle("test_" + target, DEMO_TESTS[target])

    @staticmethod
    def _advanced(context: str, target: str) -> bool:
        source = json.loads(context)["source"][target]
        return ADVANCED_HASHES.get(target) == hashlib.sha256(source.encode()).hexdigest()

    def repair(self, context: str) -> TestBundle:
        data = json.loads(context)
        if (
            self._target(context) != "shipping.py"
            or "AssertionError" not in data["execution"]["traceback"]
        ):
            raise ConfigurationError("Demo 无对应修复脚本；请使用真实模型")
        return bundle("test_shipping.py", EDGE_REPAIRED)

    def improve(self, context: str) -> TestBundle:
        data = json.loads(context)
        if self._target(context) != "shipping.py" or not data["coverage"]["missing_lines"]:
            raise ConfigurationError("Demo 无对应补测脚本；请使用真实模型")
        return bundle("test_shipping_extra.py", EDGE_EXTRA)
