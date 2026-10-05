import pytest

from calculator import clamp, divide


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (10, 2, 5.0),
        (7, -2, -3.5),
        (-9, 3, -3.0),
        (1, 4, 0.25),
    ],
)
def test_divide_normal_quotient(a, b, expected):
    assert divide(a, b) == expected


@pytest.mark.parametrize("a,b", [(1, 0), (0, 0)])
def test_divide_zero_divisor_raises_value_error(a, b):
    with pytest.raises(ValueError, match="divisor must not be zero"):
        divide(a, b)


def test_divide_integers_yield_float():
    result = divide(4, 2)
    assert result == 2.0
    assert isinstance(result, float)


def test_clamp_below_lower_returns_lower():
    assert clamp(-5, 0, 10) == 0


def test_clamp_equal_lower_returns_lower():
    assert clamp(0, 0, 10) == 0


def test_clamp_within_range_returns_value():
    assert clamp(5, 0, 10) == 5


def test_clamp_equal_upper_returns_upper():
    assert clamp(10, 0, 10) == 10


def test_clamp_above_upper_returns_upper():
    assert clamp(15, 0, 10) == 10


def test_clamp_inverted_bounds_raises_value_error():
    with pytest.raises(ValueError, match="lower exceeds upper"):
        clamp(5, 10, 0)


@pytest.mark.parametrize("value", [5, -1])
def test_clamp_degenerate_range_returns_single_point(value):
    assert clamp(value, 3, 3) == 3
