import pytest

from shipping import shipping_fee


@pytest.mark.parametrize("weight", [0.1, 0.5, 1.0])
def test_regular_tier_low_returns_5(weight):
    assert shipping_fee(weight, False) == 5


@pytest.mark.parametrize("weight", [1.001, 3.0, 5.0])
def test_regular_tier_mid_returns_10(weight):
    assert shipping_fee(weight, False) == 10


@pytest.mark.parametrize("weight", [5.001, 10.0, 100.0])
def test_regular_tier_high_returns_20(weight):
    assert shipping_fee(weight, False) == 20


@pytest.mark.parametrize("weight,base", [(0.5, 5), (3.0, 10), (7.0, 20)])
def test_express_surcharge_adds_8(weight, base):
    assert shipping_fee(weight, True) == base + 8


@pytest.mark.parametrize("weight", [0, -0.001, -1, -100])
@pytest.mark.parametrize("express", [False, True])
def test_invalid_weight_raises_value_error(weight, express):
    with pytest.raises(ValueError, match="weight must be positive"):
        shipping_fee(weight, express)


def test_zero_weight_raises_value_error():
    with pytest.raises(ValueError, match="weight must be positive"):
        shipping_fee(0)


def test_negative_zero_weight_raises_value_error():
    with pytest.raises(ValueError, match="weight must be positive"):
        shipping_fee(-0.0)


def test_express_defaults_to_false():
    assert shipping_fee(0.5) == shipping_fee(0.5, False)
    assert shipping_fee(0.5) == 5
