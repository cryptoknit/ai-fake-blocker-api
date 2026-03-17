"""
order_manager.py — Place, cancel, and monitor grid orders
"""

from typing import Optional
import pionex_client as client
import config
from grid_engine import GridLevel, GridState, quantity_per_grid
from logger import logger, alert


def place_grid_orders(state: GridState, current_price: float) -> None:
    """
    For each grid level:
    - Place a BUY limit if the level price is below current price and no buy order exists.
    - Place a SELL limit if the level price is above current price and no sell order exists.
    """
    qty = quantity_per_grid(state.levels)

    for lv in state.levels:
        if lv.price < current_price and not lv.buy_order_id:
            _place_buy(lv, qty)
        elif lv.price > current_price and not lv.sell_order_id:
            _place_sell(lv, qty)


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
        logger.info("BUY order placed at level %d price=%.4f id=%s",
                    lv.index, lv.price, lv.buy_order_id)
    except Exception as exc:
        logger.error("Failed to place BUY at level %d: %s", lv.index, exc)


def _place_sell(lv: GridLevel, qty: float) -> None:
    try:
        result = client.place_order(
            symbol=config.SYMBOL,
            side="SELL",
            price=lv.price,
            quantity=qty,
            order_type=config.ORDER_TYPE,
        )
        lv.sell_order_id = result.get("orderId")
        logger.info("SELL order placed at level %d price=%.4f id=%s",
                    lv.index, lv.price, lv.sell_order_id)
    except Exception as exc:
        logger.error("Failed to place SELL at level %d: %s", lv.index, exc)


def cancel_all_orders(state: GridState) -> None:
    """Cancel every open order tracked in the grid state."""
    for lv in state.levels:
        if lv.buy_order_id:
            _cancel(lv.buy_order_id, lv, "buy")
        if lv.sell_order_id:
            _cancel(lv.sell_order_id, lv, "sell")


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


def check_fills(state: GridState) -> list[dict]:
    """
    Poll the exchange for order status updates and return a list of
    fully-filled orders so grid_engine can update state.
    """
    try:
        open_orders = client.get_open_orders(config.SYMBOL)
    except Exception as exc:
        alert(f"Failed to fetch open orders: {exc}")
        return []

    open_ids = {o["orderId"] for o in open_orders}
    filled: list[dict] = []

    for lv in state.levels:
        for oid_attr, side, filled_attr in [
            ("buy_order_id", "BUY", "filled_buy"),
            ("sell_order_id", "SELL", "filled_sell"),
        ]:
            oid = getattr(lv, oid_attr)
            if oid and oid not in open_ids and not getattr(lv, filled_attr):
                # Order is no longer open → assume filled
                try:
                    order = client.get_order(config.SYMBOL, oid)
                    filled.append(order)
                except Exception as exc:
                    logger.warning("Could not fetch order %s: %s", oid, exc)

    return filled


def replace_filled_orders(state: GridState) -> None:
    """
    After a BUY fills, place the corresponding SELL one level up.
    After a SELL fills, place the corresponding BUY one level down.
    """
    for i, lv in enumerate(state.levels):
        if lv.filled_buy and not lv.sell_order_id:
            # Place SELL at the next level up
            if i + 1 < len(state.levels):
                upper = state.levels[i + 1]
                qty = quantity_per_grid(state.levels)
                _place_sell(upper, qty)
                lv.filled_buy = False   # reset for next cycle

        if lv.filled_sell and not lv.buy_order_id:
            # Place BUY at the next level down
            if i - 1 >= 0:
                lower = state.levels[i - 1]
                qty = quantity_per_grid(state.levels)
                _place_buy(lower, qty)
                lv.filled_sell = False  # reset for next cycle
