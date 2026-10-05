"""Domain failures propagated to callers without changing inventory."""


class OrderError(ValueError):
    """Base class for invalid business operations."""


class InvalidOrderError(OrderError):
    """Invalid product, quantity, stock or customer state."""


class OutOfStockError(OrderError):
    """A known product does not have enough available units."""


class InvalidCouponError(OrderError):
    """Coupon is malformed, expired or below its spending threshold."""
