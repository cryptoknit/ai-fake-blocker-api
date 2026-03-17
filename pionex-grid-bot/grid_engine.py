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
    price: float                          # price at which the order is placed
    buy_order_id:  Optional[str] = None
    sell_order_id: Optional[str] = None
    filled_buy:    bool = False
    filled_sell:   bool = False
    # Cost basis recorded when a BUY fills, used for P&L on the paired SELL
    buy_fill_price: Optional[float] = None


@dataclass
class GridState:
    levels: list[GridLevel] = field(default_factory=list)
    last_price: float = 0.0
    total_buy_fills:  int   = 0
    total_sell_fills: int   = 0
    realized_pnl:     float = 0.0   # USDT profit from completed round-trips
    # Order IDs that have already been processed — guards against double-counting
    # the same fill during both reconciliation at startup and the live poll cycle.
    processed_fills: set[str] = field(default_factory=set)


def build_grid() -> list[GridLevel]:
    """
    Compute GRID_COUNT + 1 evenly-spaced price levels between GRID_LOWER and
    GRID_UPPER, creating GRID_COUNT grid intervals.  Returns the list sorted
    ascending by price (index 0 = bottom).
    """
    levels: list[GridLevel] = []
    for i in range(config.GRID_COUNT + 1):
        price = config.GRID_LOWER + i * config.GRID_STEP
        levels.append(GridLevel(index=i, price=round(price, 8)))

    logger.info(
        "Grid built: %d levels from %.6f to %.6f  (step %.6f)",
        len(levels), levels[0].price, levels[-1].price, config.GRID_STEP,
    )
    return levels


def quantity_per_grid(grid_levels: list[GridLevel]) -> float:
    """
    Distribute INVESTMENT evenly across all GRID_COUNT intervals.
    Uses the lower-bound price of the first interval as a conservative
    denominator so the bot never over-invests.

    Returns base-asset quantity (rounded to 6 decimal places).
    """
    usdt_per_interval = config.INVESTMENT / config.GRID_COUNT
    # Use the bottom level price as denominator (worst-case cost per unit)
    qty = usdt_per_interval / grid_levels[0].price
    return round(qty, 6)


def update_state_from_fills(state: GridState, filled_orders: list[dict]) -> None:
    """
    Reconcile GridState after receiving a batch of fill notifications.

    *filled_orders* is a list of order dicts returned by get_order().
    For BUY fills  → mark level, record buy_fill_price for P&L tracking.
    For SELL fills → compute profit as (sell_fill_price − paired buy_fill_price) × qty.
    """
    level_by_buy_id  = {lv.buy_order_id:  lv for lv in state.levels if lv.buy_order_id}
    level_by_sell_id = {lv.sell_order_id: lv for lv in state.levels if lv.sell_order_id}

    for order in filled_orders:
        oid        = order.get("orderId")
        side       = order.get("side", "").upper()
        fill_price = float(order.get("price", 0))
        fill_qty   = float(order.get("filledSize") or order.get("size", 0))

        if oid in state.processed_fills:
            logger.warning("Skipping duplicate fill for order %s (already processed).", oid)
            continue
        state.processed_fills.add(oid)

        if side == "BUY" and oid in level_by_buy_id:
            lv = level_by_buy_id[oid]
            lv.filled_buy    = True
            lv.buy_fill_price = fill_price
            lv.buy_order_id  = None        # slot is now free; a new buy can be placed later
            state.total_buy_fills += 1
            logger.info(
                "BUY  filled  level=%d  price=%.6f  qty=%.6f",
                lv.index, fill_price, fill_qty,
            )

        elif side == "SELL" and oid in level_by_sell_id:
            lv = level_by_sell_id[oid]
            lv.filled_sell    = True
            lv.sell_order_id  = None       # slot is free; a new sell can be placed later
            state.total_sell_fills += 1

            # P&L: profit comes from the BUY that was placed one level below this SELL.
            # buy_fill_price was stored on THIS level when order_manager set it up.
            cost_basis   = lv.buy_fill_price if lv.buy_fill_price is not None else lv.price
            gross_profit = (fill_price - cost_basis) * fill_qty
            # Deduct fees for both legs: buy fee (paid when BUY filled) and
            # sell fee (paid now).  Both are a fraction of the notional traded.
            buy_fee  = cost_basis  * fill_qty * config.FEE_RATE
            sell_fee = fill_price  * fill_qty * config.FEE_RATE
            profit   = gross_profit - buy_fee - sell_fee
            state.realized_pnl += profit
            logger.info(
                "SELL filled  level=%d  price=%.6f  cost=%.6f  "
                "gross=%.6f  fees=%.6f  net=%.6f USDT",
                lv.index, fill_price, cost_basis,
                gross_profit, buy_fee + sell_fee, profit,
            )
            # Reset cost basis now that the cycle is closed
            lv.buy_fill_price = None
