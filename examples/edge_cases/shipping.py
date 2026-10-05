def shipping_fee(weight: float, express: bool = False) -> int:
    """Regular shipping costs 5 up to 1kg, 10 up to 5kg, else 20; express adds 8."""
    if weight <= 0:
        raise ValueError("weight must be positive")
    if weight <= 1:
        fee = 5
    elif weight <= 5:
        fee = 10
    else:
        fee = 20
    if express:
        fee += 8
    return fee
