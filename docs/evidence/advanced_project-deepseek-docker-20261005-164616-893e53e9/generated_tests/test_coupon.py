"""Behavioral tests for coupon.py Coupon.discount."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from coupon import Coupon
from errors import InvalidCouponError
from models import CouponType


UTC = timezone.utc
EXPIRES = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
NOW_OK = EXPIRES - timedelta(hours=1)


def _fixed(value="5", minimum="0", expires_at=EXPIRES):
    return Coupon(
        kind=CouponType.FIXED,
        value=Decimal(value),
        minimum=Decimal(minimum),
        expires_at=expires_at,
    )


def test_fixed_at_inclusive_minimum_returns_full_value():
    coupon = _fixed(value="5", minimum="20")
    assert coupon.discount(Decimal("20"), NOW_OK) == Decimal("5")


def test_percent_returns_fraction_of_subtotal():
    coupon = Coupon(
        kind=CouponType.PERCENT,
        value=Decimal("0.25"),
        minimum=Decimal("0"),
        expires_at=EXPIRES,
    )
    assert coupon.discount(Decimal("80"), NOW_OK) == Decimal("20")


def test_percent_rate_of_exactly_one_returns_full_subtotal():
    coupon = Coupon(
        kind=CouponType.PERCENT,
        value=Decimal("1"),
        minimum=Decimal("0"),
        expires_at=EXPIRES,
    )
    assert coupon.discount(Decimal("50"), NOW_OK) == Decimal("50")


def test_percent_rate_just_above_one_is_rejected():
    coupon = Coupon(
        kind=CouponType.PERCENT,
        value=Decimal("1.01"),
        minimum=Decimal("0"),
        expires_at=EXPIRES,
    )
    with pytest.raises(InvalidCouponError, match="percentage exceeds one"):
        coupon.discount(Decimal("50"), NOW_OK)


def test_expiry_is_exclusive_now_strictly_before_succeeds():
    coupon = _fixed(value="5", minimum="0")
    now = EXPIRES - timedelta(seconds=1)
    assert coupon.discount(Decimal("20"), now) == Decimal("5")


def test_expiry_equality_at_expires_at_is_expired():
    coupon = _fixed(value="5", minimum="0")
    with pytest.raises(InvalidCouponError, match="coupon expired"):
        coupon.discount(Decimal("20"), EXPIRES)


def test_minimum_spend_just_below_is_rejected():
    coupon = _fixed(value="5", minimum="20")
    with pytest.raises(InvalidCouponError, match="minimum spend not met"):
        coupon.discount(Decimal("19.99"), NOW_OK)


def test_fixed_value_may_exceed_subtotal_and_is_not_floored():
    coupon = _fixed(value="30", minimum="0")
    assert coupon.discount(Decimal("10"), NOW_OK) == Decimal("30")


def test_non_enum_kind_is_rejected():
    coupon = Coupon(
        kind="fixed",
        value=Decimal("5"),
        minimum=Decimal("0"),
        expires_at=EXPIRES,
    )
    with pytest.raises(InvalidCouponError, match="unknown coupon type"):
        coupon.discount(Decimal("20"), NOW_OK)


@pytest.mark.parametrize(
    "value",
    [
        0.5,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0"),
        Decimal("-1"),
    ],
    ids=["float", "nan", "infinity", "zero", "negative"],
)
def test_invalid_coupon_value_is_rejected(value):
    coupon = Coupon(
        kind=CouponType.FIXED,
        value=value,
        minimum=Decimal("0"),
        expires_at=EXPIRES,
    )
    with pytest.raises(InvalidCouponError, match="invalid coupon amount"):
        coupon.discount(Decimal("20"), NOW_OK)


@pytest.mark.parametrize(
    "minimum",
    [0, Decimal("NaN"), Decimal("-0.01")],
    ids=["int", "nan", "negative"],
)
def test_invalid_coupon_minimum_is_rejected(minimum):
    coupon = Coupon(
        kind=CouponType.FIXED,
        value=Decimal("5"),
        minimum=minimum,
        expires_at=EXPIRES,
    )
    with pytest.raises(InvalidCouponError, match="invalid coupon amount"):
        coupon.discount(Decimal("20"), NOW_OK)


def test_naive_expires_at_is_rejected():
    naive_expiry = datetime(2030, 1, 1, 12, 0, 0)
    coupon = Coupon(
        kind=CouponType.FIXED,
        value=Decimal("5"),
        minimum=Decimal("0"),
        expires_at=naive_expiry,
    )
    with pytest.raises(InvalidCouponError, match="timezone-aware timestamps required"):
        coupon.discount(Decimal("20"), NOW_OK)


def test_naive_now_is_rejected():
    naive_now = datetime(2029, 12, 1, 0, 0, 0)
    coupon = _fixed(value="5", minimum="0")
    with pytest.raises(InvalidCouponError, match="timezone-aware timestamps required"):
        coupon.discount(Decimal("20"), naive_now)


def test_non_datetime_expires_at_is_rejected():
    coupon = Coupon(
        kind=CouponType.FIXED,
        value=Decimal("5"),
        minimum=Decimal("0"),
        expires_at="2030-01-01",
    )
    with pytest.raises(InvalidCouponError, match="timezone-aware timestamps required"):
        coupon.discount(Decimal("20"), NOW_OK)


def test_min_spend_satisfied_path_returns_value_after_expiry_check():
    coupon = _fixed(value="5", minimum="10")
    result = coupon.discount(Decimal("15"), NOW_OK)
    assert result == Decimal("5")
