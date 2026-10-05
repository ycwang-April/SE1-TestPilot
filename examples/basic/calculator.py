"""Small arithmetic contracts with explicit boundary and error behavior."""


def divide(a: float, b: float) -> float:
    """Divide a by b; a zero divisor is invalid."""
    if b == 0:
        raise ValueError("divisor must not be zero")
    return a / b


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp to the inclusive range; reject inverted bounds."""
    if lower > upper:
        raise ValueError("lower exceeds upper")
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
