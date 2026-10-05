"""Behavioral tests for inventory.py Inventory: construction, lookup, snapshot and atomic reservation."""

from decimal import Decimal

import pytest

from errors import InvalidOrderError, OutOfStockError
from inventory import Inventory
from models import OrderLine, Product


def _inventory(**stock):
    products = [Product(sku="A", price=Decimal("1")), Product(sku="B", price=Decimal("2"))]
    return Inventory(products, stock)


def test_init_zero_fills_missing_skus_and_exposes_products():
    products = [Product(sku="A", price=Decimal("1")), Product(sku="B", price=Decimal("2"))]
    inv = Inventory(products, {"A": 5})
    assert inv.snapshot() == {"A": 5, "B": 0}
    assert inv.product("B").sku == "B"
    assert inv.product("B").price == Decimal("2")


def test_init_duplicate_sku_rejected():
    products = [Product(sku="A", price=Decimal("1")), Product(sku="A", price=Decimal("2"))]
    with pytest.raises(InvalidOrderError, match="duplicate product SKU"):
        Inventory(products, {})


def test_init_stock_with_unknown_sku_rejected():
    with pytest.raises(InvalidOrderError, match="stock refers to unknown SKU"):
        _inventory(A=1, Z=3)


@pytest.mark.parametrize(
    "amount",
    [True, 0.0, "3", -1],
    ids=["bool", "float", "string", "negative"],
)
def test_init_invalid_stock_amount_rejected(amount):
    with pytest.raises(InvalidOrderError, match="stock must be a nonnegative integer"):
        _inventory(A=amount)


def test_init_explicit_zero_stock_amount_accepted():
    inv = _inventory(A=0)
    assert inv.snapshot() == {"A": 0, "B": 0}


def test_product_known_sku_returns_instance():
    inv = _inventory(A=2)
    resolved = inv.product("A")
    assert resolved.sku == "A"
    assert resolved.price == Decimal("1")


def test_product_unknown_sku_is_domain_error_not_out_of_stock():
    inv = _inventory(A=2)
    with pytest.raises(InvalidOrderError, match="unknown SKU") as exc_info:
        inv.product("NOPE")
    assert not isinstance(exc_info.value, OutOfStockError)


def test_snapshot_returns_independent_copy():
    inv = _inventory(A=5)
    snap = inv.snapshot()
    snap["A"] = 999
    assert inv.snapshot() == {"A": 5, "B": 0}
    assert snap is not inv.snapshot()


def test_reserve_single_line_deducts_stock():
    inv = _inventory(A=5)
    inv.reserve([OrderLine(sku="A", quantity=2)])
    assert inv.snapshot()["A"] == 3


def test_reserve_aggregates_repeated_skus_to_exact_stock():
    inv = _inventory(A=5)
    inv.reserve([OrderLine(sku="A", quantity=2), OrderLine(sku="A", quantity=3)])
    assert inv.snapshot()["A"] == 0


def test_reserve_exact_stock_accepted():
    inv = _inventory(A=3)
    inv.reserve([OrderLine(sku="A", quantity=3)])
    assert inv.snapshot()["A"] == 0


def test_reserve_one_over_stock_raises_and_preserves_stock():
    inv = _inventory(A=3)
    with pytest.raises(OutOfStockError, match="not enough stock: A"):
        inv.reserve([OrderLine(sku="A", quantity=4)])
    assert inv.snapshot()["A"] == 3


def test_reserve_empty_lines_rejected():
    inv = _inventory(A=5)
    with pytest.raises(InvalidOrderError, match="empty order"):
        inv.reserve([])
    assert inv.snapshot() == {"A": 5, "B": 0}


def test_reserve_unknown_sku_surfaces_before_deduction():
    inv = _inventory(A=5)
    with pytest.raises(InvalidOrderError, match="Z") as exc_info:
        inv.reserve([OrderLine(sku="A", quantity=1), OrderLine(sku="Z", quantity=1)])
    assert "unknown SKU" in str(exc_info.value)
    assert inv.snapshot() == {"A": 5, "B": 0}


def test_reserve_is_all_or_nothing_when_later_sku_out_of_stock():
    inv = _inventory(A=2, B=1)
    with pytest.raises(OutOfStockError, match="not enough stock: B"):
        inv.reserve([OrderLine(sku="A", quantity=1), OrderLine(sku="B", quantity=5)])
    assert inv.snapshot() == {"A": 2, "B": 1}


def test_reserve_multiline_success_commits_all_and_keeps_catalog():
    inv = _inventory(A=4, B=4)
    inv.reserve([OrderLine(sku="A", quantity=1), OrderLine(sku="B", quantity=2)])
    assert inv.snapshot() == {"A": 3, "B": 2}
    assert inv.product("A").sku == "A"


def test_reserve_aggregate_exceeds_stock_even_when_lines_fit_individually():
    inv = _inventory(A=3)
    with pytest.raises(OutOfStockError, match="not enough stock: A"):
        inv.reserve([OrderLine(sku="A", quantity=2), OrderLine(sku="A", quantity=2)])
    assert inv.snapshot()["A"] == 3
