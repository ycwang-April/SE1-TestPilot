def discount_rate(total: float, member: bool = False) -> float:
    """Members get 20%; other orders >= 100 get 10%; reject negative totals."""
    if total < 0:
        raise ValueError("negative total")
    if member:
        return 0.2
    if total >= 100:
        return 0.1
    return 0.0
