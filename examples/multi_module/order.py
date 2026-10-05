from discount import discount_rate
from models import Item


def order_total(items: list[Item], member: bool = False) -> float:
    """Compute discounted total, rounded to two decimal places."""
    total = sum(item.subtotal() for item in items)
    return round(total * (1 - discount_rate(total, member)), 2)
