"""
grid_engine.py — Grid level calculation and state management
"""

from dataclasses import dataclass, field
from typing import Optional
import config
from logger import logger


@dataclass
class GridLevel:
    index: int
    price: float
    buy_order_id: Optional[str] = None
    sell_order_id: Optional[str] = None
    filled_buy: bool = False
    filled_sell: bool = False


@dataclass
class GridState:
    levels: list[GridLevel] = field(default_factory=list)
    last_price: float = 0.0
    total_buy_fills: int = 0
    total_sell_fills: int = 0
    realized_pnl: float = 0.0   # USDT profit from completed round-trips


def build_grid() -> list[GridLevel]:
    """
    Compute evenly-spaced price levels between GRID_LOWER and GRID_UPPER.
    Returns a list of GridLevel objects sorted ascending by price.
    """
    levels: list[GridLevel] = []
    for i in range(config.GRID_COUNT + 1):
        price = config.GRID_LOWER + i * config.GRID_STEP
        levels.append(GridLevel(index=i, price=round(price, 8)))
    logger.info(
        "Grid built: %d levels from %.4f to %.4f (step %.4f)",
        len(levels), levels[0].price, levels[-1].price, config.GRID_STEP,
    )
    return levels


def quantity_per_grid(grid_levels: list[GridLevel]) -> float:
    """
    Distribute the total INVESTMENT evenly across all buy levels below
    the current price. Returns the base-asset quantity per grid cell.

    Falls back to dividing by total levels if price is unavailable yet.
    """
    # Each grid interval gets an equal share of the investment (in USDT)
    usdt_per_level = config.INVESTMENT / config.GRID_COUNT
    # mid-price of first interval as a conservative denominator
    mid_price = (grid_levels[0].price + grid_levels[1].price) / 2
    qty = usdt_per_level / mid_price
    return round(qty, 6)


def update_state_from_fills(state: GridState, filled_orders: list[dict]) -> None:
    """
    Reconcile GridState after receiving a batch of fill notifications.
    *filled_orders* is a list of order dicts from the exchange.
    """
    level_by_buy_id  = {lv.buy_order_id:  lv for lv in state.levels if lv.buy_order_id}
    level_by_sell_id = {lv.sell_order_id: lv for lv in state.levels if lv.sell_order_id}

    for order in filled_orders:
        oid  = order.get("orderId")
        side = order.get("side", "").upper()
        fill_price = float(order.get("price", 0))
        fill_qty   = float(order.get("filledSize", 0))

        if side == "BUY" and oid in level_by_buy_id:
            lv = level_by_buy_id[oid]
            lv.filled_buy = True
            state.total_buy_fills += 1
            logger.info("BUY filled at level %d (price=%.4f)", lv.index, lv.price)

        elif side == "SELL" and oid in level_by_sell_id:
            lv = level_by_sell_id[oid]
            lv.filled_sell = True
            state.total_sell_fills += 1
            profit = (fill_price - lv.price) * fill_qty
            state.realized_pnl += profit
            logger.info(
                "SELL filled at level %d (price=%.4f) → PnL +%.4f USDT",
                lv.index, fill_price, profit,
            )
