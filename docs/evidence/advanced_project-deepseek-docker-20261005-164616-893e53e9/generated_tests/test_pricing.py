"""Behavioral tests for pricing.py quote: coupon replaces VIP discount, then floor and round once."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from coupon import Coupon
from errors import InvalidCouponError, InvalidOrderError
from inventory import Inventory
from models import CouponType, CustomerLevel, OrderLine, Product
from pricing import quote


UTC = timezone.utc
EXPIRES = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
NOW_OK = EXPIRES - timedelta(hours=1)


def _inv(products, stock):
    return Inventory(products, stock)


def test_regular_no_coupon_returns_subtotal_and_does_not_reserve():
    inv = _inv(
        [Product(sku="A", price=Decimal("10.005")), Product(sku="B", price=Decimal("3.33"))],
        {"A": 10, "B": 10},
    )
    before = inv.snapshot()
    result = quote(
        [OrderLine(sku="A", quantity=2), OrderLine(sku="B", quantity=3)],
        inv,
        CustomerLevel.REGULAR,
        None,
        NOW_OK,
    )
    assert result == Decimal("30.00")
    assert inv.snapshot() == before


def test_vip_without_coupon_applies_membership_discount():
    inv = _inv([Product(sku="A", price=Decimal("20"))], {"A": 5})
    result = quote([OrderLine(sku="A", quantity=1)], inv, CustomerLevel.VIP, None, NOW_OK)
    assert result == Decimal("18.00")


def test_coupon_replaces_vip_discount_even_when_less_generous():
    inv = _inv([Product(sku="A", price=Decimal("100"))], {"A": 5})
    coupon = Coupon(CouponType.PERCENT, Decimal("0.05"), Decimal("0"), EXPIRES)
    result = quote(
        [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.VIP, coupon, NOW_OK
    )
    assert result == Decimal("95.00")


def test_coupon_replaces_vip_discount_when_more_generous():
    inv = _inv([Product(sku="A", price=Decimal("100"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, Decimal("30"), Decimal("0"), EXPIRES)
    result = quote(
        [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.VIP, coupon, NOW_OK
    )
    assert result == Decimal("70.00")


def test_fixed_coupon_exceeding_subtotal_floors_total_at_zero():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, Decimal("100"), Decimal("0"), EXPIRES)
    result = quote(
        [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.REGULAR, coupon, NOW_OK
    )
    assert result == Decimal("0.00")


def test_zero_total_boundary_when_discount_equals_subtotal():
    inv = _inv([Product(sku="A", price=Decimal("50"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, Decimal("50"), Decimal("0"), EXPIRES)
    result = quote(
        [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.REGULAR, coupon, NOW_OK
    )
    assert result == Decimal("0.00")


def test_rounding_uses_round_half_up_at_half_cent():
    inv = _inv([Product(sku="A", price=Decimal("10.005"))], {"A": 5})
    result = quote(
        [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.REGULAR, None, NOW_OK
    )
    assert result == Decimal("10.01")


def test_single_rounding_applied_after_coupon_subtraction():
    inv = _inv([Product(sku="A", price=Decimal("0.01"))], {"A": 5})
    coupon = Coupon(CouponType.PERCENT, Decimal("0.5"), Decimal("0"), EXPIRES)
    result = quote(
        [OrderLine(sku="A", quantity=2)], inv, CustomerLevel.REGULAR, coupon, NOW_OK
    )
    assert result == Decimal("0.01")


def test_empty_lines_rejected():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    with pytest.raises(InvalidOrderError, match="empty order"):
        quote([], inv, CustomerLevel.REGULAR, None, NOW_OK)


def test_non_enum_level_rejected():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    with pytest.raises(InvalidOrderError, match="unknown customer level"):
        quote([OrderLine(sku="A", quantity=1)], inv, "vip", None, NOW_OK)


def test_expired_coupon_propagates_and_never_falls_back_to_vip():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, Decimal("5"), Decimal("0"), EXPIRES)
    with pytest.raises(InvalidCouponError, match="coupon expired"):
        quote([OrderLine(sku="A", quantity=1)], inv, CustomerLevel.VIP, coupon, EXPIRES)


def test_coupon_below_minimum_propagates_and_never_falls_back_to_vip():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, Decimal("1"), Decimal("50"), EXPIRES)
    with pytest.raises(InvalidCouponError, match="minimum spend not met"):
        quote([OrderLine(sku="A", quantity=1)], inv, CustomerLevel.VIP, coupon, NOW_OK)


def test_unknown_sku_surfaces_during_subtotal_accumulation():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    with pytest.raises(InvalidOrderError, match="unknown SKU: MISSING"):
        quote(
            [OrderLine(sku="A", quantity=1), OrderLine(sku="MISSING", quantity=1)],
            inv,
            CustomerLevel.REGULAR,
            None,
            NOW_OK,
        )


def test_branch_regular_vs_vip_isolates_else_branch():
    products = [Product(sku="A", price=Decimal("7.77"))]
    regular = quote(
        [OrderLine(sku="A", quantity=1)],
        _inv(products, {"A": 5}),
        CustomerLevel.REGULAR,
        None,
        NOW_OK,
    )
    vip = quote(
        [OrderLine(sku="A", quantity=1)],
        _inv(products, {"A": 5}),
        CustomerLevel.VIP,
        None,
        NOW_OK,
    )
    assert regular == Decimal("7.77")
    assert vip == Decimal("6.99")


def test_quote_never_mutates_inventory():
    inv = _inv([Product(sku="A", price=Decimal("3"))], {"A": 5})
    before = inv.snapshot()
    result = quote([OrderLine(sku="A", quantity=3)], inv, CustomerLevel.REGULAR, None, NOW_OK)
    assert result == Decimal("9.00")
    assert inv.snapshot() == before == {"A": 5}


def test_multiline_same_sku_sums_without_aggregation():
    inv = _inv([Product(sku="A", price=Decimal("2.50"))], {"A": 100})
    result = quote(
        [OrderLine(sku="A", quantity=2), OrderLine(sku="A", quantity=3)],
        inv,
        CustomerLevel.REGULAR,
        None,
        NOW_OK,
    )
    assert result == Decimal("12.50")


def test_invalid_coupon_value_from_float_propagates_through_quote():
    inv = _inv([Product(sku="A", price=Decimal("10"))], {"A": 5})
    coupon = Coupon(CouponType.FIXED, 5.0, Decimal("0"), EXPIRES)
    with pytest.raises(InvalidCouponError, match="invalid coupon amount"):
        quote(
            [OrderLine(sku="A", quantity=1)], inv, CustomerLevel.REGULAR, coupon, NOW_OK
        )
