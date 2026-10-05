"""Behavioral tests for models.py: Product, OrderLine, CustomerLevel and CouponType."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from errors import InvalidOrderError
from models import CouponType, CustomerLevel, OrderLine, Product


# --- Product ---------------------------------------------------------------


def test_product_accepts_valid_sku_and_price():
    product = Product(sku="A1", price=Decimal("19.99"))
    assert product.sku == "A1"
    assert product.price == Decimal("19.99")


def test_product_zero_price_is_accepted():
    product = Product(sku="A1", price=Decimal("0"))
    assert product.price == Decimal("0")


@pytest.mark.parametrize(
    "sku",
    ["", "   ", None, 123],
    ids=["empty", "whitespace", "none", "int"],
)
def test_product_invalid_sku_rejected(sku):
    with pytest.raises(InvalidOrderError, match="SKU must be nonempty"):
        Product(sku=sku, price=Decimal("1"))


@pytest.mark.parametrize(
    "price",
    [1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01")],
    ids=["float", "nan", "infinity", "negative"],
)
def test_product_invalid_price_rejected(price):
    with pytest.raises(
        InvalidOrderError, match="price must be a finite nonnegative Decimal"
    ):
        Product(sku="A1", price=price)


def test_product_is_frozen():
    product = Product(sku="A1", price=Decimal("1"))
    with pytest.raises(FrozenInstanceError):
        product.price = Decimal("2")
    assert product.price == Decimal("1")


def test_product_value_equality_and_hash():
    p1 = Product(sku="A1", price=Decimal("5"))
    p2 = Product(sku="A1", price=Decimal("5"))
    assert p1 == p2
    assert hash(p1) == hash(p2)


def test_product_negative_price_error_is_valueerror_and_has_message():
    caught = None
    try:
        Product(sku="A1", price=Decimal("-1"))
    except ValueError as exc:
        caught = exc
    assert isinstance(caught, InvalidOrderError)
    assert str(caught) == "price must be a finite nonnegative Decimal"


# --- OrderLine -------------------------------------------------------------


def test_orderline_accepts_valid_sku_and_quantity():
    line = OrderLine(sku="A1", quantity=3)
    assert line.sku == "A1"
    assert line.quantity == 3


def test_orderline_quantity_one_is_accepted():
    line = OrderLine(sku="A1", quantity=1)
    assert line.quantity == 1


@pytest.mark.parametrize(
    "sku",
    ["", "\t", None, 7],
    ids=["empty", "tab", "none", "int"],
)
def test_orderline_invalid_sku_rejected(sku):
    with pytest.raises(InvalidOrderError, match="SKU must be nonempty"):
        OrderLine(sku=sku, quantity=1)


@pytest.mark.parametrize(
    "quantity",
    [0, -1, True, False, 1.0, "2", None],
    ids=["zero", "negative", "true", "false", "float", "string", "none"],
)
def test_orderline_invalid_quantity_rejected(quantity):
    with pytest.raises(InvalidOrderError, match="quantity must be a positive integer"):
        OrderLine(sku="A1", quantity=quantity)


def test_orderline_is_frozen():
    line = OrderLine(sku="A1", quantity=2)
    with pytest.raises(FrozenInstanceError):
        line.quantity = 5
    assert line.quantity == 2


# --- Enums -----------------------------------------------------------------


def test_customerlevel_members_and_values():
    assert CustomerLevel.REGULAR.value == "regular"
    assert CustomerLevel.VIP.value == "vip"
    assert isinstance(CustomerLevel.REGULAR, CustomerLevel)
    assert isinstance(CustomerLevel.VIP, CustomerLevel)


def test_coupontype_members_values_and_lookup():
    assert CouponType.FIXED.value == "fixed"
    assert CouponType.PERCENT.value == "percent"
    assert CouponType("fixed") is CouponType.FIXED
    assert CouponType("percent") is CouponType.PERCENT


def test_coupontype_unknown_value_raises_plain_valueerror():
    with pytest.raises(ValueError) as exc_info:
        CouponType("bogus")
    assert not isinstance(exc_info.value, InvalidOrderError)
