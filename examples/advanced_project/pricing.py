"""Pricing contract: coupon replaces the VIP discount, then floor and round once."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from coupon import Coupon
from errors import InvalidOrderError
from inventory import Inventory
from models import CustomerLevel, OrderLine


def quote(
    lines: list[OrderLine],
    inventory: Inventory,
    level: CustomerLevel,
    coupon: Coupon | None,
    now: datetime,
) -> Decimal:
    """Calculate without reserving stock. VIP is 10% off when NO coupon is supplied.

    Coupons replace membership discounts even if less generous; invalid coupons raise,
    never silently fall back to VIP pricing. Return cents using ROUND_HALF_UP.
    """
    if not lines:
        raise InvalidOrderError("empty order")
    if not isinstance(level, CustomerLevel):
        raise InvalidOrderError("unknown customer level")
    subtotal = sum(
        (inventory.product(line.sku).price * line.quantity for line in lines), Decimal("0")
    )
    if coupon is not None:
        total = subtotal - coupon.discount(subtotal, now)
    elif level == CustomerLevel.VIP:
        total = subtotal * Decimal("0.90")
    else:
        total = subtotal
    return max(Decimal("0"), total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
