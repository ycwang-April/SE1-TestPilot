"""In-memory stock with all-or-nothing reservation; no persistence or concurrent access."""

from errors import InvalidOrderError, OutOfStockError
from models import OrderLine, Product


class Inventory:
    def __init__(self, products: list[Product], stock: dict[str, int]):
        self._products = {product.sku: product for product in products}
        if len(self._products) != len(products):
            raise InvalidOrderError("duplicate product SKU")
        if any(sku not in self._products for sku in stock):
            raise InvalidOrderError("stock refers to unknown SKU")
        if any(type(amount) is not int or amount < 0 for amount in stock.values()):
            raise InvalidOrderError("stock must be a nonnegative integer")
        self._stock = {sku: stock.get(sku, 0) for sku in self._products}

    def product(self, sku: str) -> Product:
        """Resolve a product; unknown SKU is a domain error, not an out-of-stock error."""
        if sku not in self._products:
            raise InvalidOrderError(f"unknown SKU: {sku}")
        return self._products[sku]

    def snapshot(self) -> dict[str, int]:
        """Return a copy: callers cannot change stock through the snapshot."""
        return dict(self._stock)

    def reserve(self, lines: list[OrderLine]) -> None:
        """Aggregate repeated SKUs, validate ALL stock, then commit the deduction."""
        if not lines:
            raise InvalidOrderError("empty order")
        requested: dict[str, int] = {}
        for line in lines:
            self.product(line.sku)
            requested[line.sku] = requested.get(line.sku, 0) + line.quantity
        for sku, quantity in requested.items():
            if quantity > self._stock[sku]:
                raise OutOfStockError(f"not enough stock: {sku}")
        for sku, quantity in requested.items():
            self._stock[sku] -= quantity
