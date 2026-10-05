"""Offline responses for advanced_project only, selected by source fingerprints.

Expected outcomes belong to this explicit Demo fixture, never to the agent/controller.
Unlike edge_cases, this fixture does not manufacture a failure to force a repair round.
"""

from testpilot.schemas.test_plan import TestCasePlan, TestPlan

# Each row is one distinct behavior family; values within a family are parametrized in tests.
CASES = {
    "errors.py": [
        (
            "exception",
            "OrderError",
            "domain exception subclasses",
            "preserve message and common base",
        ),
    ],
    "models.py": [
        ("normal", "Product/OrderLine", "valid immutable inputs and enum values", "retain fields"),
        (
            "invalid",
            "Product",
            "empty SKU; negative, nonfinite or non-Decimal price",
            "InvalidOrderError",
        ),
        (
            "invalid",
            "OrderLine",
            "empty SKU; zero, negative, boolean or noninteger quantity",
            "InvalidOrderError",
        ),
    ],
    "inventory.py": [
        (
            "normal",
            "Inventory",
            "missing stock entry and copied snapshot",
            "zero default and isolated copy",
        ),
        (
            "invalid",
            "Inventory",
            "duplicate or unknown SKU and invalid stock amounts",
            "InvalidOrderError",
        ),
        (
            "interaction",
            "Inventory.reserve",
            "repeated SKU totaling exact stock",
            "aggregate and reduce to zero",
        ),
        (
            "exception",
            "Inventory.reserve",
            "second SKU insufficient or duplicate lines exceed stock",
            "OutOfStockError; no partial deduction",
        ),
        (
            "invalid",
            "Inventory.reserve",
            "empty order or unknown SKU",
            "InvalidOrderError; no mutation",
        ),
    ],
    "coupon.py": [
        (
            "boundary",
            "Coupon.discount",
            "subtotal at/below minimum",
            "inclusive threshold or InvalidCouponError",
        ),
        (
            "boundary",
            "Coupon.discount",
            "before/at expiration",
            "valid before; expired at timestamp",
        ),
        (
            "normal",
            "Coupon.discount",
            "fixed and percentage coupon",
            "fixed value or fractional subtotal",
        ),
        ("invalid", "Coupon.discount", "unknown kind and invalid amounts", "InvalidCouponError"),
        ("invalid", "Coupon.discount", "naive or None timestamps", "InvalidCouponError"),
    ],
    "pricing.py": [
        (
            "normal",
            "quote",
            "regular/VIP customer without coupon",
            "full price or ten percent reduction",
        ),
        ("interaction", "quote", "VIP plus coupon", "coupon replaces membership discount"),
        (
            "boundary",
            "quote",
            "large coupon and half-cent price",
            "zero floor; half-up cent rounding",
        ),
        ("invalid", "quote", "empty order or invalid customer level", "InvalidOrderError"),
    ],
    "order_service.py": [
        (
            "interaction",
            "OrderService.checkout",
            "successful order with injected clock",
            "correct charge and stock decrement; clock called once",
        ),
        (
            "exception",
            "OrderService.checkout",
            "expired coupon, low stock, invalid level or unknown SKU",
            "domain error propagates; no stock change",
        ),
        (
            "exception",
            "OrderService.checkout",
            "clock raises",
            "propagate clock error; no stock change",
        ),
        (
            "boundary",
            "OrderService.checkout",
            "clock advances to exact expiry",
            "same coupon transitions from valid to expired",
        ),
        (
            "interaction",
            "OrderService",
            "monkeypatched default clock",
            "runtime dependency injection honored",
        ),
    ],
}


def plan_for(target: str) -> TestPlan:
    return TestPlan(
        target=target,
        cases=[
            TestCasePlan(
                category=category,
                description=expected,
                target_symbol=symbol,
                input_strategy=inputs,
                expected_behavior=expected,
                behavior_id=f"{target}:{number}",
            )
            for number, (category, symbol, inputs, expected) in enumerate(CASES[target])
        ],
    )


TESTS = {
    "errors.py": """import pytest
from errors import OrderError, InvalidOrderError, OutOfStockError, InvalidCouponError

@pytest.mark.parametrize("error", [InvalidOrderError, OutOfStockError, InvalidCouponError])
def test_domain_error_contract(error):
    with pytest.raises(OrderError, match="details"):
        raise error("details")
""",
    "models.py": """from dataclasses import FrozenInstanceError
from decimal import Decimal as D
import pytest
from models import Product, OrderLine, CustomerLevel, CouponType
from errors import InvalidOrderError

def test_immutable_inputs_and_enums():
    product = Product("A", D("0"))
    line = OrderLine("A", 1)
    assert product.price == D("0") and line.quantity == 1
    assert CustomerLevel.VIP.value == "vip" and CouponType.FIXED.value == "fixed"
    with pytest.raises(FrozenInstanceError):
        product.price = D("5")

@pytest.mark.parametrize("sku,price", [("", D("1")), (None, D("1")), ("A", D("-1")), ("A", D("NaN")), ("A", 1)])
def test_invalid_product(sku, price):
    with pytest.raises(InvalidOrderError):
        Product(sku, price)

@pytest.mark.parametrize("sku,quantity", [(" ", 1), (None, 1), ("A", 0), ("A", -1), ("A", True), ("A", 1.5)])
def test_invalid_line(sku, quantity):
    with pytest.raises(InvalidOrderError):
        OrderLine(sku, quantity)
""",
    "inventory.py": """from decimal import Decimal as D
import pytest
from models import Product, OrderLine
from inventory import Inventory
from errors import InvalidOrderError, OutOfStockError

def test_stock_defaults_and_snapshot_copy():
    inventory = Inventory([Product("A", D("1"))], {})
    copy = inventory.snapshot()
    copy["A"] = 99
    assert inventory.snapshot() == {"A": 0}
    assert inventory.product("A").price == D("1")

@pytest.mark.parametrize("products,stock", [([Product("A", D("1"))]*2, {}), ([Product("A", D("1"))], {"B": 1}), ([Product("A", D("1"))], {"A": -1}), ([Product("A", D("1"))], {"A": True})])
def test_invalid_inventory(products, stock):
    with pytest.raises(InvalidOrderError):
        Inventory(products, stock)

def test_repeated_sku_exact_stock():
    inventory = Inventory([Product("A", D("1"))], {"A": 3})
    inventory.reserve([OrderLine("A", 1), OrderLine("A", 2)])
    assert inventory.snapshot() == {"A": 0}

@pytest.mark.parametrize("lines,error", [([], InvalidOrderError), ([OrderLine("X", 1)], InvalidOrderError), ([OrderLine("A", 1), OrderLine("B", 2)], OutOfStockError), ([OrderLine("A", 2), OrderLine("A", 2)], OutOfStockError)])
def test_reservation_failure_is_atomic(lines, error):
    inventory = Inventory([Product("A", D("1")), Product("B", D("2"))], {"A": 3, "B": 1})
    before = inventory.snapshot()
    with pytest.raises(error):
        inventory.reserve(lines)
    assert inventory.snapshot() == before
""",
    "coupon.py": """from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from coupon import Coupon
from models import CouponType as K
from errors import InvalidCouponError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

def test_minimum_is_inclusive():
    coupon = Coupon(K.FIXED, D("5"), D("100"), NOW + timedelta(days=1))
    assert coupon.discount(D("100"), NOW) == D("5")
    with pytest.raises(InvalidCouponError, match="minimum"):
        coupon.discount(D("99.99"), NOW)

def test_expiry_is_exclusive():
    coupon = Coupon(K.PERCENT, D("1"), D("0"), NOW)
    assert coupon.discount(D("10"), NOW - timedelta(microseconds=1)) == D("10")
    with pytest.raises(InvalidCouponError, match="expired"):
        coupon.discount(D("10"), NOW)

@pytest.mark.parametrize("kind,value,minimum", [("unknown", D("1"), D("0")), (K.FIXED, D("0"), D("0")), (K.FIXED, D("NaN"), D("0")), (K.FIXED, None, D("0")), (K.FIXED, D("1"), D("-1")), (K.FIXED, D("1"), D("NaN")), (K.FIXED, D("1"), None), (K.PERCENT, D("1.01"), D("0"))])
def test_invalid_coupon(kind, value, minimum):
    coupon = Coupon(kind, value, minimum, NOW + timedelta(days=1))
    with pytest.raises(InvalidCouponError):
        coupon.discount(D("100"), NOW)

@pytest.mark.parametrize("expiry,now", [(None, NOW), (NOW, None), (NOW.replace(tzinfo=None), NOW), (NOW, NOW.replace(tzinfo=None))])
def test_invalid_timestamp(expiry, now):
    with pytest.raises(InvalidCouponError, match="timezone"):
        Coupon(K.FIXED, D("1"), D("0"), expiry).discount(D("10"), now)
""",
    "pricing.py": """from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from models import Product, OrderLine, CustomerLevel as L, CouponType as K
from inventory import Inventory
from coupon import Coupon
from pricing import quote
from errors import InvalidOrderError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

@pytest.mark.parametrize("level,coupon,expected", [(L.REGULAR, None, "100.00"), (L.VIP, None, "90.00"), (L.VIP, Coupon(K.FIXED, D("5"), D("100"), NOW + timedelta(days=1)), "95.00"), (L.REGULAR, Coupon(K.PERCENT, D("0.20"), D("100"), NOW + timedelta(days=1)), "80.00")])
def test_discount_policy(level, coupon, expected):
    inventory = Inventory([Product("A", D("100"))], {"A": 2})
    assert quote([OrderLine("A", 1)], inventory, level, coupon, NOW) == D(expected)
    assert inventory.snapshot() == {"A": 2}

def test_floor_at_zero():
    inventory = Inventory([Product("A", D("1"))], {"A": 1})
    coupon = Coupon(K.FIXED, D("5"), D("0"), NOW + timedelta(days=1))
    assert quote([OrderLine("A", 1)], inventory, L.VIP, coupon, NOW) == D("0.00")

def test_round_half_up_once():
    inventory = Inventory([Product("A", D("1.005"))], {"A": 3})
    assert quote([OrderLine("A", 1)], inventory, L.REGULAR, None, NOW) == D("1.01")
    assert quote([OrderLine("A", 3)], inventory, L.REGULAR, None, NOW) == D("3.02")

@pytest.mark.parametrize("lines,level", [([], L.REGULAR), ([OrderLine("A", 1)], None)])
def test_invalid_quote(lines, level):
    inventory = Inventory([Product("A", D("1"))], {"A": 1})
    with pytest.raises(InvalidOrderError):
        quote(lines, inventory, level, None, NOW)
""",
    "order_service.py": """from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import Mock
import pytest
import order_service
from order_service import OrderService
from inventory import Inventory
from models import Product, OrderLine, CustomerLevel as L, CouponType as K
from coupon import Coupon
from errors import InvalidOrderError, InvalidCouponError, OutOfStockError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

def make_inventory():
    return Inventory([Product("A", D("50")), Product("B", D("10"))], {"A": 3, "B": 1})

def test_checkout_success_and_clock_called_once():
    inventory = make_inventory()
    clock = Mock(return_value=NOW)
    service = OrderService(inventory, clock)
    assert service.checkout([OrderLine("A", 2)], L.VIP) == D("90.00")
    assert inventory.snapshot() == {"A": 1, "B": 1}
    clock.assert_called_once_with()

@pytest.mark.parametrize("lines,level,coupon,error", [([], L.REGULAR, None, InvalidOrderError), ([OrderLine("A", 1)], None, None, InvalidOrderError), ([OrderLine("X", 1)], L.REGULAR, None, InvalidOrderError), ([OrderLine("A", 1), OrderLine("B", 2)], L.REGULAR, None, OutOfStockError), ([OrderLine("A", 1)], L.VIP, Coupon(K.FIXED, D("5"), D("0"), NOW), InvalidCouponError), ([OrderLine("A", 1)], L.VIP, Coupon(K.FIXED, D("5"), D("100"), NOW + timedelta(days=1)), InvalidCouponError)])
def test_checkout_failure_preserves_stock(lines, level, coupon, error):
    inventory = make_inventory()
    service = OrderService(inventory, lambda: NOW)
    before = inventory.snapshot()
    with pytest.raises(error):
        service.checkout(lines, level, coupon)
    assert inventory.snapshot() == before

def test_clock_failure_preserves_stock():
    inventory = make_inventory()
    clock = Mock(side_effect=RuntimeError("clock failed"))
    service = OrderService(inventory, clock)
    with pytest.raises(RuntimeError, match="clock failed"):
        service.checkout([OrderLine("A", 1)])
    assert inventory.snapshot() == {"A": 3, "B": 1}

def test_expiry_between_orders():
    inventory = make_inventory()
    expiry = NOW + timedelta(seconds=1)
    clock = Mock(side_effect=[NOW, expiry])
    service = OrderService(inventory, clock)
    coupon = Coupon(K.FIXED, D("5"), D("0"), expiry)
    assert service.checkout([OrderLine("A", 1)], coupon=coupon) == D("45.00")
    before = inventory.snapshot()
    with pytest.raises(InvalidCouponError, match="expired"):
        service.checkout([OrderLine("A", 1)], coupon=coupon)
    assert inventory.snapshot() == before

def test_default_clock_can_be_monkeypatched(monkeypatch):
    assert order_service.current_time().utcoffset() == timedelta(0)
    monkeypatch.setattr(order_service, "current_time", lambda: NOW)
    service = OrderService(make_inventory())
    assert service.clock() == NOW
""",
}
