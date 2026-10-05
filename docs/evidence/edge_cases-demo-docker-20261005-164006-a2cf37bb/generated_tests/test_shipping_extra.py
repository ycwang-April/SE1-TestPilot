import pytest
from shipping import shipping_fee

@pytest.mark.parametrize("weight,express,expected", [(0.1, False, 5), (1, True, 13), (1.01, False, 10), (5, True, 18), (5.01, False, 20), (10, True, 28)])
def test_other_paths(weight, express, expected):
    assert shipping_fee(weight, express) == expected

@pytest.mark.parametrize("weight", [0, -1])
def test_invalid_weight(weight):
    with pytest.raises(ValueError, match="positive"):
        shipping_fee(weight)
