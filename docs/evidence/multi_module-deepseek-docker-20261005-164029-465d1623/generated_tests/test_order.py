import pytest

from models import Item
from order import order_total


class _NegativeStub:
    def subtotal(self) -> float:
        return -5.0


class _ConstantStub:
    def __init__(self, value: float) -> None:
        self._value = value

    def subtotal(self) -> float:
        return self._value


def test_empty_items_zero_total():
    assert order_total([]) == 0.0
    assert order_total([], member=True) == 0.0


@pytest.mark.parametrize(
    "items, expected",
    [
        ([Item(10.0, 2)], 20.0),
        ([Item(2.5, 4), Item(10.0, 3)], 40.0),
        ([Item(0.99, 100)], 99.0),
    ],
)
def test_nonmember_below_threshold_no_discount(items, expected):
    assert order_total(items, member=False) == expected


@pytest.mark.parametrize(
    "items, expected",
    [
        ([Item(25.5, 4)], 91.8),
        ([Item(100.0, 10)], 900.0),
    ],
)
def test_nonmember_volume_discount_applied(items, expected):
    assert order_total(items, member=False) == expected


@pytest.mark.parametrize(
    "items, expected",
    [
        ([Item(10.0, 2)], 16.0),
        ([Item(2.5, 4)], 8.0),
        ([Item(60.0, 1)], 48.0),
    ],
)
def test_member_discount_applied(items, expected):
    assert order_total(items, member=True) == expected


def test_threshold_boundary_inclusive_aggregate():
    assert order_total([Item(50.0, 2)], member=False) == 90.0
    assert order_total([Item(49.99, 2)], member=False) == 99.98


@pytest.mark.parametrize(
    "items, expected",
    [
        ([Item(50.0, 2)], 80.0),
        ([Item(100.0, 10)], 800.0),
    ],
)
def test_member_precedence_over_volume_aggregate(items, expected):
    assert order_total(items, member=True) == expected


def test_discounted_result_rounded():
    assert order_total([Item(12.345, 1)], member=False) == round(12.345, 2)
    assert order_total([Item(12.345, 1)], member=True) == round(12.345 * 0.8, 2)


@pytest.mark.parametrize(
    "items",
    [
        [Item(-1.0, 1)],
        [Item(10.0, -2)],
        [Item(5.0, 1), Item(-3.0, 2)],
    ],
)
def test_item_error_propagation(items):
    with pytest.raises(ValueError, match="negative price or quantity"):
        order_total(items, member=False)


def test_negative_aggregate_propagation():
    with pytest.raises(ValueError, match="negative total"):
        order_total([_NegativeStub()], member=False)


@pytest.mark.parametrize("items", [None, 42])
def test_invalid_items_type_error(items):
    with pytest.raises(TypeError):
        order_total(items)


@pytest.mark.parametrize("items", [[object()], [1, 2]])
def test_invalid_item_element_attribute_error(items):
    with pytest.raises(AttributeError):
        order_total(items)


def test_aggregate_drives_discount_threshold():
    items = [Item(40.0, 1), Item(40.0, 1), Item(20.0, 1)]
    assert order_total(items, member=False) == 90.0


def test_member_flag_forwarded():
    items = [Item(10.0, 1)]
    assert order_total(items, member=False) == 10.0
    assert order_total(items, member=True) == 8.0


def test_partial_sum_below_threshold_uses_aggregate_not_single_item():
    items = [Item(60.0, 1), Item(30.0, 1)]
    assert order_total(items, member=False) == 90.0
