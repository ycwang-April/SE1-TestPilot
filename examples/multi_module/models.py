from dataclasses import dataclass


@dataclass
class Item:
    price: float
    quantity: int = 1

    def subtotal(self) -> float:
        if self.price < 0 or self.quantity < 0:
            raise ValueError("negative price or quantity")
        return self.price * self.quantity
