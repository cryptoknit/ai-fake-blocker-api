"""
dry_run.py — Simulated order book for DRY_RUN=true mode.

Implements the same interface as the mutating functions in pionex_client
(place_order, cancel_order, get_open_orders, get_order, get_balances) so
order_manager and grid_engine work without modification.

Fill simulation
---------------
Call simulate_fills(current_price) once per bot cycle.  A BUY limit fills
when current_price <= order_price; a SELL limit fills when
current_price >= order_price.  This mirrors how a real exchange fills
resting limit orders as the market moves through them.
"""

from __future__ import annotations

from logger import logger

# ── Internal state ────────────────────────────────────────────────────────────

# order_id → order dict
_orders: dict[str, dict] = {}
_serial: int = 0


def _new_id() -> str:
    global _serial
    _serial += 1
    return f"DRY-{_serial:08d}"


def reset() -> None:
    """Clear all simulated orders (useful for tests / restart)."""
    global _serial
    _orders.clear()
    _serial = 0


# ── Public interface (mirrors pionex_client) ──────────────────────────────────

def place_order(
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    order_type: str = "LIMIT",
) -> dict:
    oid = _new_id()
    order = {
        "orderId": oid,
        "symbol": symbol,
        "side": side.upper(),
        "type": order_type.upper(),
        "price": str(price),
        "size": str(quantity),
        "filledSize": "0",
        "status": "OPEN",
    }
    _orders[oid] = order
    logger.info("[DRY-RUN] %s %s placed  id=%s  price=%.6f  qty=%.6f",
                order_type, side, oid, price, quantity)
    return order


def cancel_order(symbol: str, order_id: str) -> dict:
    order = _orders.pop(order_id, {"orderId": order_id, "status": "NOT_FOUND"})
    logger.info("[DRY-RUN] Cancelled order %s", order_id)
    return order


def get_open_orders(symbol: str) -> dict:
    open_orders = [
        o for o in _orders.values()
        if o["symbol"] == symbol and o["status"] == "OPEN"
    ]
    return {"orders": open_orders}


def get_order(symbol: str, order_id: str) -> dict:
    if order_id in _orders:
        return _orders[order_id]
    # Not in our book — treat as filled (the simulate step removed it)
    return {"orderId": order_id, "status": "FILLED", "filledSize": "0", "size": "0"}


def get_balances() -> dict:
    """Return a synthetic balance so startup checks pass in dry-run mode."""
    return {"balances": [{"coinType": "USDT", "free": "999999", "frozen": "0"}]}


# ── Fill simulation ───────────────────────────────────────────────────────────

def simulate_fills(current_price: float) -> None:
    """
    Walk every open simulated order and mark it FILLED if the market has
    crossed its limit price:
    - BUY  fills when current_price <= order_price  (market dropped to us)
    - SELL fills when current_price >= order_price  (market rose to us)
    """
    for order in list(_orders.values()):
        if order["status"] != "OPEN":
            continue

        order_price = float(order["price"])
        side        = order["side"]

        should_fill = (
            (side == "BUY"  and current_price <= order_price) or
            (side == "SELL" and current_price >= order_price)
        )

        if should_fill:
            order["status"]     = "FILLED"
            order["filledSize"] = order["size"]
            logger.info(
                "[DRY-RUN] %s order %s FILLED  limit=%.6f  market=%.6f",
                side, order["orderId"], order_price, current_price,
            )
