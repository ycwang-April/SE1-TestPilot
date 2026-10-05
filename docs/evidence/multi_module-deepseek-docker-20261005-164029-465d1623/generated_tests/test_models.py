import pytest

from models import Item


@pytest.mark.parametrize(
    "price, quantity",
    [(2.5, 4), (10.0, 3), (0.99, 100)],
)
def test_subtotal_positive_price_quantity(price, quantity):
    assert Item(price=price, quantity=quantity).subtotal() == price * quantity


def test_subtotal_default_quantity_equals_price():
    assert Item(price=7.25).subtotal() == 7.25
    assert Item(price=7.25, quantity=1).subtotal() == 7.25


def test_subtotal_default_quantity_attribute_is_one():
    assert Item(price=7.25).quantity == 1


@pytest.mark.parametrize(
    "price, quantity",
    [(0, 5), (10, 0), (0, 0)],
)
def test_subtotal_zero_boundary(price, quantity):
    assert Item(price=price, quantity=quantity).subtotal() == 0.0


@pytest.mark.parametrize("price", [-0.01, -5.0])
def test_negative_price_rejected(price):
    with pytest.raises(ValueError, match="negative price or quantity"):
        Item(price=price, quantity=2).subtotal()


@pytest.mark.parametrize(
    "price, quantity",
    [(10.0, -1), (10.0, -100), (0, -3)],
)
def test_negative_quantity_rejected(price, quantity):
    with pytest.raises(ValueError, match="negative price or quantity"):
        Item(price=price, quantity=quantity).subtotal()


def test_both_negative_rejected():
    with pytest.raises(ValueError, match="negative price or quantity"):
        Item(price=-3.0, quantity=-2).subtotal()


@pytest.mark.parametrize(
    "price, quantity",
    [(None, 1), ("abc", 1), (1.0, "x")],
)
def test_non_numeric_operand_type_error(price, quantity):
    with pytest.raises(TypeError):
        Item(price=price, quantity=quantity).subtotal()
