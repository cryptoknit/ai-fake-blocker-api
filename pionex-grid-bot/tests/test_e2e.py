"""
tests/test_e2e.py — End-to-end flow test for the grid bot pipeline.

Exercises the full sequence without touching the exchange:
  build_grid → place_grid_orders → BUY fill → replace_filled_orders
  → SELL fill → verify P&L and processed_fills.
"""

import unittest.mock as mock

from grid_engine import GridState, build_grid, update_state_from_fills
from order_manager import place_grid_orders, replace_filled_orders

# Config values that produce a clean 3-level grid (indices 0, 1, 2) with a
# convenient quantity: usdt_per_interval = 58/2 = 29 → qty = 29/29_000 = 0.001
_CFG = dict(
    SYMBOL="BTC_USDT",
    GRID_LOWER=29_000.0,
    GRID_UPPER=31_000.0,
    GRID_COUNT=2,
    GRID_STEP=1_000.0,
    INVESTMENT=58.0,
    ORDER_TYPE="LIMIT",
    FEE_RATE=0.001,
)


class TestEndToEndFlow:

    def test_buy_fill_then_sell_fill_pnl_and_processed_fills(self):
        """
        Full pipeline with all exchange calls mocked:

        1. build_grid   — creates 3 levels: 29 000, 30 000, 31 000
        2. place_grid_orders(current_price=35 000) — price is above every level
           so all three levels get a BUY order placed.
        3. Simulate BUY fill at level 0 (price 29 000, qty 0.001).
        4. replace_filled_orders — places counter-SELL at level 1.
        5. Simulate SELL fill at level 1 (price 30 000, qty 0.001).
        6. Assert realized P&L == gross − buy_fee − sell_fee.
        7. Assert processed_fills contains both order IDs.
        """
        # IDs dispensed in order: three initial BUYs, then one counter-SELL.
        order_ids = iter(["b000", "b001", "b002", "s001_counter"])

        with mock.patch.multiple("config", **_CFG), \
             mock.patch("pionex_client.place_order",
                        side_effect=lambda **kw: {"orderId": next(order_ids)}):

            # ── 1. Build grid ──────────────────────────────────────────────────
            levels = build_grid()
            state  = GridState(levels=levels)
            assert [lv.price for lv in state.levels] == [29_000.0, 30_000.0, 31_000.0]

            # ── 2. Place initial orders ────────────────────────────────────────
            # current_price=35_000 is above every level → all get BUY orders
            place_grid_orders(state, current_price=35_000.0)
            assert state.levels[0].buy_order_id == "b000"
            assert state.levels[1].buy_order_id == "b001"
            assert state.levels[2].buy_order_id == "b002"

            # ── 3. BUY fill at level 0 ─────────────────────────────────────────
            update_state_from_fills(state, [{
                "orderId":    "b000",
                "side":       "BUY",
                "price":      "29000",
                "filledSize": "0.001",
                "status":     "FILLED",
            }])
            assert state.levels[0].filled_buy is True
            assert state.levels[0].buy_fill_price == 29_000.0
            assert state.total_buy_fills == 1

            # ── 4. replace_filled_orders → counter-SELL at level 1 ────────────
            # Level 1 already has a BUY reference but no SELL → counter-SELL placed
            replace_filled_orders(state)
            assert state.levels[1].sell_order_id == "s001_counter"
            assert state.levels[1].buy_fill_price == 29_000.0  # cost basis forwarded
            assert state.levels[0].filled_buy is False          # flag cleared

            # ── 5. SELL fill at level 1 ────────────────────────────────────────
            update_state_from_fills(state, [{
                "orderId":    "s001_counter",
                "side":       "SELL",
                "price":      "30000",
                "filledSize": "0.001",
                "status":     "FILLED",
            }])
            assert state.total_sell_fills == 1

        # ── 6. Verify realized P&L ─────────────────────────────────────────────
        qty      = 0.001
        fee_rate = 0.001
        gross    = (30_000.0 - 29_000.0) * qty
        buy_fee  = 29_000.0 * qty * fee_rate
        sell_fee = 30_000.0 * qty * fee_rate
        expected = gross - buy_fee - sell_fee
        assert abs(state.realized_pnl - expected) < 1e-9

        # ── 7. Both order IDs recorded in processed_fills ─────────────────────
        assert "b000"         in state.processed_fills
        assert "s001_counter" in state.processed_fills
