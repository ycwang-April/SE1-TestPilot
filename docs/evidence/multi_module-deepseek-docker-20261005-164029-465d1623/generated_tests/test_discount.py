import pytest

from discount import discount_rate


@pytest.mark.parametrize("total", [0, 50, 99.99])
def test_member_rate_precedence(total):
    assert discount_rate(total, member=True) == 0.2


@pytest.mark.parametrize("total", [100, 250, 1000])
def test_nonmember_volume_discount(total):
    assert discount_rate(total, member=False) == 0.1


@pytest.mark.parametrize("total", [0, 1, 99])
def test_nonmember_no_discount(total):
    assert discount_rate(total, member=False) == 0.0


def test_threshold_boundary_inclusive():
    assert discount_rate(100, member=False) == 0.1
    assert discount_rate(99, member=False) == 0.0


def test_zero_total_valid():
    assert discount_rate(0, member=False) == 0.0
    assert discount_rate(0, member=True) == 0.2


@pytest.mark.parametrize("total", [-0.01, -1, -100])
def test_negative_total_rejected_nonmember(total):
    with pytest.raises(ValueError, match="negative total"):
        discount_rate(total, member=False)


@pytest.mark.parametrize("total", [-0.01, -1, -100])
def test_negative_total_rejected_member(total):
    with pytest.raises(ValueError, match="negative total"):
        discount_rate(total, member=True)


@pytest.mark.parametrize("total", [100, 500])
def test_member_precedence_over_volume(total):
    assert discount_rate(total, member=True) == 0.2


@pytest.mark.parametrize("total", [None, "abc", []])
def test_non_numeric_total_type_error(total):
    with pytest.raises(TypeError):
        discount_rate(total)
