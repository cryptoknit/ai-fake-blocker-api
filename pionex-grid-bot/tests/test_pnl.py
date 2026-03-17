"""
tests/test_pnl.py — Replay fill sequences and verify P&L calculation.

These tests use only grid_engine dataclasses; no network calls are made.
All GridLevel objects are constructed directly so config values don't matter.
"""

import pytest
from grid_engine import GridLevel, GridState, update_state_from_fills


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_level(
    index: int,
    price: float,
    *,
    buy_id: str | None = None,
    sell_id: str | None = None,
    buy_fill_price: float | None = None,
) -> GridLevel:
    lv = GridLevel(index=index, price=price)
    lv.buy_order_id   = buy_id
    lv.sell_order_id  = sell_id
    lv.buy_fill_price = buy_fill_price
    return lv


def buy_fill(order_id: str, price: float, qty: float) -> dict:
    return {
        "orderId": order_id,
        "side": "BUY",
        "price": str(price),
        "filledSize": str(qty),
        "status": "FILLED",
    }


def sell_fill(order_id: str, price: float, qty: float) -> dict:
    return {
        "orderId": order_id,
        "side": "SELL",
        "price": str(price),
        "filledSize": str(qty),
        "status": "FILLED",
    }


# ── BUY fill mechanics ────────────────────────────────────────────────────────

class TestBuyFillMechanics:

    def test_buy_fill_sets_filled_flag(self):
        lv = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert lv.filled_buy is True

    def test_buy_fill_records_fill_price(self):
        lv = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        # Market slipped slightly — fill price differs from limit price
        update_state_from_fills(state, [buy_fill("b001", 28_990.0, 0.001)])
        assert lv.buy_fill_price == 28_990.0

    def test_buy_fill_clears_order_id(self):
        lv = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert lv.buy_order_id is None

    def test_buy_fill_increments_counter(self):
        lv = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert state.total_buy_fills == 1

    def test_buy_fill_does_not_add_pnl(self):
        lv = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert state.realized_pnl == 0.0


# ── SELL fill mechanics ───────────────────────────────────────────────────────

class TestSellFillMechanics:

    def test_sell_fill_sets_filled_flag(self):
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])
        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])
        assert lv.filled_sell is True

    def test_sell_fill_clears_order_id(self):
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])
        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])
        assert lv.sell_order_id is None

    def test_sell_fill_resets_buy_fill_price(self):
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])
        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])
        assert lv.buy_fill_price is None


# ── P&L accuracy ─────────────────────────────────────────────────────────────

class TestPnLCalculation:

    def test_single_round_trip(self):
        """BUY at 29 000, SELL at 30 000, qty=0.001 → profit = 1.0 USDT."""
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])

        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])

        expected = (30_000.0 - 29_000.0) * 0.001   # 1.0
        assert abs(state.realized_pnl - expected) < 1e-9

    def test_multiple_round_trips_accumulate(self):
        """Two independent round-trips, each earning 1.0 USDT."""
        lv_a = make_level(1, 30_000.0, sell_id="sA", buy_fill_price=29_000.0)
        lv_b = make_level(3, 32_000.0, sell_id="sB", buy_fill_price=31_000.0)
        state = GridState(levels=[lv_a, lv_b])

        fills = [
            sell_fill("sA", 30_000.0, 0.001),
            sell_fill("sB", 32_000.0, 0.001),
        ]
        update_state_from_fills(state, fills)

        expected = (30_000.0 - 29_000.0) * 0.001 + (32_000.0 - 31_000.0) * 0.001  # 2.0
        assert abs(state.realized_pnl - expected) < 1e-9
        assert state.total_sell_fills == 2

    def test_pnl_uses_actual_fill_price_not_limit_price(self):
        """If the market fills us at a better price the extra slip is captured."""
        # SELL limit at 30 000 but filled at 30 050 (price ran through us)
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])

        update_state_from_fills(state, [sell_fill("s001", 30_050.0, 0.001)])

        expected = (30_050.0 - 29_000.0) * 0.001   # 1.05
        assert abs(state.realized_pnl - expected) < 1e-9

    def test_pnl_fallback_when_no_cost_basis(self):
        """
        If buy_fill_price was never set (e.g. the initial SELL placed at
        startup without a prior BUY), fall back to lv.price as cost basis.
        The SELL fills exactly at its limit price → profit is 0.
        """
        lv = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=None)
        state = GridState(levels=[lv])

        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])

        assert abs(state.realized_pnl - 0.0) < 1e-9

    def test_many_cycles_no_float_drift(self):
        """Accumulate 1 000 round-trips and verify no significant float drift."""
        QTY   = 0.001
        STEP  = 1_000.0
        N     = 1_000
        total = 0.0

        for i in range(N):
            sell_id = f"s{i:06d}"
            lv = make_level(1, 30_000.0, sell_id=sell_id, buy_fill_price=30_000.0 - STEP)
            state = GridState(levels=[lv])
            update_state_from_fills(state, [sell_fill(sell_id, 30_000.0, QTY)])
            total += state.realized_pnl

        expected = STEP * QTY * N   # 1_000 * 0.001 * 1_000 = 1.0 USDT
        assert abs(total - expected) < 1e-6   # tolerate tiny float rounding

    def test_unknown_order_id_is_ignored(self):
        """A fill with an unrecognised order ID must not corrupt state."""
        lv = make_level(0, 29_000.0, buy_id="known")
        state = GridState(levels=[lv])

        update_state_from_fills(state, [buy_fill("UNKNOWN", 29_000.0, 0.001)])

        assert state.total_buy_fills == 0
        assert lv.buy_order_id == "known"   # unchanged


# ── Sequence: BUY fill then SELL fill ────────────────────────────────────────

class TestBuySellSequence:

    def test_buy_then_sell_end_to_end_pnl(self):
        """
        Full in-order sequence:
        1. BUY at level 0 (price=29 000) fills.
        2. order_manager would set buy_fill_price=29 000 on the sell level.
        3. SELL at level 1 (price=30 000) fills → profit=1.0 USDT.
        """
        buy_lv  = make_level(0, 29_000.0, buy_id="b001")
        sell_lv = make_level(1, 30_000.0, sell_id="s001")
        state   = GridState(levels=[buy_lv, sell_lv])

        # Step 1 — BUY fills
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert buy_lv.buy_fill_price == 29_000.0
        assert state.realized_pnl == 0.0

        # Simulate what order_manager does: carry cost basis to the sell level
        sell_lv.buy_fill_price = buy_lv.buy_fill_price
        sell_lv.sell_order_id  = "s001"   # pretend counter-sell was placed

        # Step 2 — SELL fills
        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])
        expected = (30_000.0 - 29_000.0) * 0.001
        assert abs(state.realized_pnl - expected) < 1e-9
        assert state.total_buy_fills  == 1
        assert state.total_sell_fills == 1
