"""Coupons use the pre-discount subtotal; expiry is exclusive at expires_at."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from errors import InvalidCouponError
from models import CouponType


@dataclass(frozen=True)
class Coupon:
    kind: CouponType
    value: Decimal
    minimum: Decimal
    expires_at: datetime

    def discount(self, subtotal: Decimal, now: datetime) -> Decimal:
        """Minimum spend is inclusive; percent values are fractions in (0, 1].

        Both timestamps must be timezone-aware. A fixed discount may exceed subtotal;
        pricing, not the coupon, floors the final charge at zero.
        """
        if not isinstance(self.kind, CouponType):
            raise InvalidCouponError("unknown coupon type")
        if (
            not isinstance(self.value, Decimal)
            or not self.value.is_finite()
            or self.value <= 0
            or not isinstance(self.minimum, Decimal)
            or not self.minimum.is_finite()
            or self.minimum < 0
        ):
            raise InvalidCouponError("invalid coupon amount")
        if self.kind == CouponType.PERCENT and self.value > 1:
            raise InvalidCouponError("percentage exceeds one")
        if (
            not isinstance(self.expires_at, datetime)
            or not isinstance(now, datetime)
            or self.expires_at.utcoffset() is None
            or now.utcoffset() is None
        ):
            raise InvalidCouponError("timezone-aware timestamps required")
        if now >= self.expires_at:
            raise InvalidCouponError("coupon expired")
        if subtotal < self.minimum:
            raise InvalidCouponError("minimum spend not met")
        if self.kind == CouponType.FIXED:
            return self.value
        return subtotal * self.value
