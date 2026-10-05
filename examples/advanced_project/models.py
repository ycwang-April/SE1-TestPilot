"""Immutable order inputs; monetary arithmetic uses Decimal, not binary floats."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from errors import InvalidOrderError


class CustomerLevel(Enum):
    REGULAR = "regular"
    VIP = "vip"


class CouponType(Enum):
    FIXED = "fixed"
    PERCENT = "percent"


@dataclass(frozen=True)
class Product:
    sku: str
    price: Decimal

    def __post_init__(self):
        """SKU must be nonempty; price must be a finite nonnegative Decimal."""
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise InvalidOrderError("SKU must be nonempty")
        if not isinstance(self.price, Decimal) or not self.price.is_finite() or self.price < 0:
            raise InvalidOrderError("price must be a finite nonnegative Decimal")


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int

    def __post_init__(self):
        """Quantity is a strictly positive integer, excluding booleans."""
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise InvalidOrderError("SKU must be nonempty")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise InvalidOrderError("quantity must be a positive integer")
