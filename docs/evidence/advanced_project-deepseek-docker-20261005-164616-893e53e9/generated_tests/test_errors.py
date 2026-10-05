"""Behavioral tests for the errors.py exception hierarchy."""

import pytest

from errors import (
    InvalidCouponError,
    InvalidOrderError,
    OrderError,
    OutOfStockError,
)


def test_ordererror_is_valueerror_subclass_carrying_message():
    assert issubclass(OrderError, ValueError)
    err = OrderError("boom")
    assert isinstance(err, ValueError)
    assert str(err) == "boom"


def test_invalidordererror_instance_is_domain_and_valueerror():
    err = InvalidOrderError("bad")
    assert isinstance(err, OrderError)
    assert isinstance(err, ValueError)
    assert str(err) == "bad"


def test_outofstockerror_is_domain_error_but_not_invalidorder():
    err = OutOfStockError("no stock")
    assert isinstance(err, OrderError)
    assert isinstance(err, ValueError)
    assert not isinstance(err, InvalidOrderError)


def test_invalidcouponerror_is_domain_error_disjoint_from_siblings():
    err = InvalidCouponError("bad coupon")
    assert isinstance(err, OrderError)
    assert isinstance(err, ValueError)
    assert not isinstance(err, InvalidOrderError)
    assert not isinstance(err, OutOfStockError)


def test_domain_error_is_catchable_as_valueerror():
    caught = None
    try:
        raise InvalidCouponError("x")
    except ValueError as exc:
        caught = exc
    assert isinstance(caught, InvalidCouponError)
    assert str(caught) == "x"


@pytest.mark.parametrize(
    "exc_type,expect_caught",
    [
        (InvalidOrderError, True),
        (OutOfStockError, False),
        (InvalidCouponError, False),
    ],
    ids=["invalid-order", "out-of-stock", "invalid-coupon"],
)
def test_catching_invalidordererror_does_not_catch_siblings(exc_type, expect_caught):
    caught = None
    try:
        raise exc_type("x")
    except InvalidOrderError as exc:
        caught = exc
    except OrderError:
        pass
    if expect_caught:
        assert isinstance(caught, InvalidOrderError)
    else:
        assert caught is None
