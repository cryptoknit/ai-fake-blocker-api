"""
order_manager.py — Place, cancel, and monitor grid orders
"""

import pionex_client as client
import config
from grid_engine import GridLevel, GridState, quantity_per_grid
from logger import logger, alert


# ── Initial grid placement ────────────────────────────────────────────────────

def place_grid_orders(state: GridState, current_price: float) -> None:
    """
    Initial sweep: for every level that has no open order yet:
    - price < current → place BUY limit
    - price > current → place SELL limit
    Levels at exactly current_price are skipped (no order needed).
    """
    qty = quantity_per_grid(state.levels)
    for lv in state.levels:
        if lv.price < current_price and not lv.buy_order_id:
            _place_buy(lv, qty)
        elif lv.price > current_price and not lv.sell_order_id:
            _place_sell(lv, qty, buy_cost=None)


# ── Fill detection ────────────────────────────────────────────────────────────

def check_fills(state: GridState) -> list[dict]:
    """
    Compare tracked order IDs against the exchange's open-orders list.
    Any order no longer in open-orders is treated as filled; its full
    order dict is fetched and returned for state reconciliation.
    """
    try:
        open_orders = client.get_open_orders(config.SYMBOL)
    except Exception as exc:
        alert(f"Failed to fetch open orders: {exc}")
        return []

    open_ids = {o["orderId"] for o in open_orders}
    filled: list[dict] = []

    for lv in state.levels:
        for oid_attr, already_filled_attr in [
            ("buy_order_id",  "filled_buy"),
            ("sell_order_id", "filled_sell"),
        ]:
            oid = getattr(lv, oid_attr)
            if oid and oid not in open_ids and not getattr(lv, already_filled_attr):
                try:
                    order = client.get_order(config.SYMBOL, oid)
                    # Only treat as filled if the exchange confirms it
                    if order.get("status", "").upper() in ("FILLED", "PARTIALLY_FILLED"):
                        filled.append(order)
                    else:
                        # Order was cancelled externally — clear our reference
                        setattr(lv, oid_attr, None)
                        logger.warning(
                            "Order %s vanished with status %s; clearing reference.",
                            oid, order.get("status"),
                        )
                except Exception as exc:
                    logger.warning("Could not fetch order %s: %s", oid, exc)

    return filled


# ── Counter-order placement after fills ──────────────────────────────────────

def replace_filled_orders(state: GridState) -> None:
    """
    Grid rotation logic:
    - BUY at level i filled  → place SELL at level i+1 (one step up)
    - SELL at level j filled → place BUY  at level j-1 (one step down)

    The buy_fill_price is forwarded to the sell level so grid_engine can
    compute accurate P&L when that sell eventually fills.
    """
    qty = quantity_per_grid(state.levels)
    levels = state.levels

    for i, lv in enumerate(levels):
        if lv.filled_buy:
            upper_idx = i + 1
            if upper_idx < len(levels):
                upper = levels[upper_idx]
                if not upper.sell_order_id:   # don't double-place
                    _place_sell(upper, qty, buy_cost=lv.buy_fill_price)
                else:
                    logger.debug(
                        "Skipping counter-SELL for level %d: level %d already has sell order %s",
                        i, upper_idx, upper.sell_order_id,
                    )
            lv.filled_buy = False             # clear flag regardless

        if lv.filled_sell:
            lower_idx = i - 1
            if lower_idx >= 0:
                lower = levels[lower_idx]
                if not lower.buy_order_id:    # don't double-place
                    _place_buy(lower, qty)
                else:
                    logger.debug(
                        "Skipping counter-BUY for level %d: level %d already has buy order %s",
                        i, lower_idx, lower.buy_order_id,
                    )
            lv.filled_sell = False            # clear flag regardless


# ── Cancel everything ─────────────────────────────────────────────────────────

def cancel_all_orders(state: GridState) -> None:
    """Cancel every open order tracked in the grid state."""
    for lv in state.levels:
        if lv.buy_order_id:
            _cancel(lv.buy_order_id, lv, "buy")
        if lv.sell_order_id:
            _cancel(lv.sell_order_id, lv, "sell")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _place_buy(lv: GridLevel, qty: float) -> None:
    try:
        result = client.place_order(
            symbol=config.SYMBOL,
            side="BUY",
            price=lv.price,
            quantity=qty,
            order_type=config.ORDER_TYPE,
        )
        lv.buy_order_id = result.get("orderId")
        logger.info(
            "BUY  placed  level=%d  price=%.6f  qty=%.6f  id=%s",
            lv.index, lv.price, qty, lv.buy_order_id,
        )
    except Exception as exc:
        logger.error("Failed to place BUY at level %d (price=%.6f): %s", lv.index, lv.price, exc)


def _place_sell(lv: GridLevel, qty: float, *, buy_cost: float | None) -> None:
    """
    Place a SELL order at *lv*.  Store *buy_cost* as the cost basis for P&L.
    """
    try:
        result = client.place_order(
            symbol=config.SYMBOL,
            side="SELL",
            price=lv.price,
            quantity=qty,
            order_type=config.ORDER_TYPE,
        )
        lv.sell_order_id   = result.get("orderId")
        lv.buy_fill_price  = buy_cost   # carry cost basis forward for P&L
        logger.info(
            "SELL placed  level=%d  price=%.6f  qty=%.6f  id=%s  cost_basis=%.6f",
            lv.index, lv.price, qty, lv.sell_order_id, buy_cost or 0,
        )
    except Exception as exc:
        logger.error("Failed to place SELL at level %d (price=%.6f): %s", lv.index, lv.price, exc)


def _cancel(order_id: str, lv: GridLevel, side: str) -> None:
    try:
        client.cancel_order(config.SYMBOL, order_id)
        if side == "buy":
            lv.buy_order_id = None
        else:
            lv.sell_order_id = None
        logger.info("Cancelled %s order %s at level %d", side, order_id, lv.index)
    except Exception as exc:
        logger.error("Failed to cancel %s order %s: %s", side, order_id, exc)
