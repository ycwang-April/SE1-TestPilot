from shipping import shipping_fee

def test_regular_small():
    assert shipping_fee(1) == 5
