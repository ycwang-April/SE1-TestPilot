"""Behavioral tests for order_service.py: OrderService composition of pricing and inventory."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from coupon import Coupon
from errors import InvalidCouponError, InvalidOrderError, OutOfStockError
from inventory import Inventory
from models import CouponType, CustomerLevel, OrderLine, Product
from order_service import OrderService, current_time


UTC = timezone.utc
EXPIRES = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
NOW_OK = EXPIRES - timedelta(hours=1)


def _inventory(stock):
    products = [Product(sku="A", price=Decimal("10"))]
    return Inventory(products, stock)


def _service(clock=NOW_OK):
    inv = _inventory({"A": 5})
    fixed = (lambda: clock) if not callable(clock) else clock
    return OrderService(inv, clock=fixed), inv


def test_checkout_success_prices_then_reserves_stock():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    total = service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, None)
    assert total == Decimal("20.00")
    assert inv.snapshot() == {"A": 3}


def test_checkout_vip_without_coupon_applies_membership_discount():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    total = service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.VIP, None)
    assert total == Decimal("18.00")
    assert inv.snapshot()["A"] == 3


def test_checkout_calls_injected_clock_exactly_once_per_attempt():
    inv = _inventory({"A": 5})
    calls = []

    def clock():
        calls.append(NOW_OK)
        return NOW_OK

    service = OrderService(inv, clock=clock)
    coupon = Coupon(CouponType.FIXED, Decimal("5"), Decimal("0"), EXPIRES)
    total = service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, coupon)
    assert len(calls) == 1
    assert total == Decimal("15.00")
    assert inv.snapshot()["A"] == 3


def test_init_none_clock_uses_module_default_current_time():
    inv = _inventory({"A": 2})
    service = OrderService(inv, clock=None)
    assert service.clock is current_time
    inv2 = Inventory([Product(sku="A", price=Decimal("5"))], {"A": 2})
    service2 = OrderService(inv2, clock=None)
    total = service2.checkout([OrderLine(sku="A", quantity=1)], CustomerLevel.REGULAR, None)
    assert total == Decimal("5.00")
    assert inv2.snapshot()["A"] == 1


def test_init_injected_clock_stored_verbatim():
    inv = _inventory({"A": 5})
    sentinel = lambda: NOW_OK
    service = OrderService(inv, clock=sentinel)
    assert service.clock is sentinel
    assert service.clock is not current_time


def test_checkout_expired_coupon_leaves_inventory_untouched():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: EXPIRES)
    coupon = Coupon(CouponType.FIXED, Decimal("5"), Decimal("0"), EXPIRES)
    with pytest.raises(InvalidCouponError, match="coupon expired"):
        service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, coupon)
    assert inv.snapshot() == {"A": 5}


def test_checkout_empty_lines_rejected_and_stock_unchanged():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    with pytest.raises(InvalidOrderError, match="empty order"):
        service.checkout([], CustomerLevel.REGULAR, None)
    assert inv.snapshot() == {"A": 5}


def test_checkout_invalid_level_rejected_and_stock_unchanged():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    with pytest.raises(InvalidOrderError, match="unknown customer level"):
        service.checkout([OrderLine(sku="A", quantity=1)], "vip", None)
    assert inv.snapshot() == {"A": 5}


def test_checkout_unknown_sku_rejected_and_stock_unchanged():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    with pytest.raises(InvalidOrderError, match="unknown SKU"):
        service.checkout([OrderLine(sku="MISSING", quantity=1)], CustomerLevel.REGULAR, None)
    assert inv.snapshot() == {"A": 5}


def test_checkout_reserve_failure_after_valid_quote_preserves_stock():
    inv = _inventory({"A": 1})
    service = OrderService(inv, clock=lambda: NOW_OK)
    with pytest.raises(OutOfStockError, match="not enough stock: A"):
        service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, None)
    assert inv.snapshot()["A"] == 1


def test_checkout_repeated_calls_deduct_independently():
    inv = _inventory({"A": 5})
    service = OrderService(inv, clock=lambda: NOW_OK)
    first = service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, None)
    assert first == Decimal("20.00")
    assert inv.snapshot()["A"] == 3
    second = service.checkout([OrderLine(sku="A", quantity=2)], CustomerLevel.REGULAR, None)
    assert second == Decimal("20.00")
    assert inv.snapshot()["A"] == 1


def test_current_time_returns_aware_utc_datetime():
    first = current_time()
    second = current_time()
    assert first.utcoffset() == timedelta(0)
    assert second.utcoffset() == timedelta(0)
    assert second >= first
