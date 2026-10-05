"""Checkout composes pricing and atomic inventory reservation with an injectable clock."""

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from coupon import Coupon
from inventory import Inventory
from models import CustomerLevel, OrderLine
from pricing import quote


def current_time() -> datetime:
    return datetime.now(timezone.utc)


class OrderService:
    def __init__(self, inventory: Inventory, clock: Callable[[], datetime] | None = None):
        self.inventory = inventory
        self.clock = clock if clock is not None else current_time

    def checkout(
        self,
        lines: list[OrderLine],
        level: CustomerLevel = CustomerLevel.REGULAR,
        coupon: Coupon | None = None,
    ) -> Decimal:
        """Only reserve after pricing/validation succeeds; any failure leaves stock unchanged.

        The injected clock is called once per attempt. This service is synchronous and
        assumes single-threaded ownership of Inventory during checkout.
        """
        total = quote(lines, self.inventory, level, coupon, self.clock())
        self.inventory.reserve(lines)
        return total
