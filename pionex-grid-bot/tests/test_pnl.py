"""
tests/test_pnl.py — Replay fill sequences and verify P&L calculation.

These tests use only grid_engine dataclasses; no network calls are made.
All GridLevel objects are constructed directly so config values don't matter.

The `zero_fees` autouse fixture patches FEE_RATE=0 so that the core P&L math
tests remain fee-agnostic.  Tests that specifically verify fee deduction opt
in to a non-zero rate via their own mock.patch context manager.
"""

import unittest.mock as mock

import pytest

from grid_engine import GridLevel, GridState, update_state_from_fills


@pytest.fixture(autouse=True)
def zero_fees():
    """Patch FEE_RATE to 0 for all tests in this module unless overridden."""
    with mock.patch("config.FEE_RATE", 0.0):
        yield


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


# ── Fee deduction ─────────────────────────────────────────────────────────────

class TestFeeDeduction:
    """Verify that both legs of a round-trip have their fees deducted from P&L."""

    def test_fees_reduce_profit(self):
        """Net profit = gross − buy_fee − sell_fee."""
        with mock.patch("config.FEE_RATE", 0.001):
            lv    = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
            state = GridState(levels=[lv])
            update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])

        qty        = 0.001
        gross      = (30_000.0 - 29_000.0) * qty           # 1.0
        buy_fee    = 29_000.0 * qty * 0.001                 # 0.029
        sell_fee   = 30_000.0 * qty * 0.001                 # 0.030
        expected   = gross - buy_fee - sell_fee             # 0.941
        assert abs(state.realized_pnl - expected) < 1e-9

    def test_fees_applied_to_both_legs(self):
        """Each fee leg is proportional to its own notional value."""
        with mock.patch("config.FEE_RATE", 0.002):
            lv    = make_level(1, 20_000.0, sell_id="s1", buy_fill_price=18_000.0)
            state = GridState(levels=[lv])
            update_state_from_fills(state, [sell_fill("s1", 20_000.0, 0.005)])

        qty        = 0.005
        gross      = (20_000.0 - 18_000.0) * qty
        buy_fee    = 18_000.0 * qty * 0.002
        sell_fee   = 20_000.0 * qty * 0.002
        expected   = gross - buy_fee - sell_fee
        assert abs(state.realized_pnl - expected) < 1e-9

    def test_zero_fee_rate_leaves_gross_unchanged(self):
        """FEE_RATE=0 (the autouse default) means net == gross."""
        # zero_fees fixture already applies; just confirm the formula holds
        lv    = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])
        update_state_from_fills(state, [sell_fill("s001", 30_000.0, 0.001)])
        expected = (30_000.0 - 29_000.0) * 0.001
        assert abs(state.realized_pnl - expected) < 1e-9

    def test_fees_can_turn_small_profit_into_loss(self):
        """If the grid step is smaller than the round-trip fee, net P&L is negative."""
        with mock.patch("config.FEE_RATE", 0.01):   # 1% — exaggerated for clarity
            lv    = make_level(1, 29_100.0, sell_id="s001", buy_fill_price=29_000.0)
            state = GridState(levels=[lv])
            update_state_from_fills(state, [sell_fill("s001", 29_100.0, 0.01)])

        # gross = 100 * 0.01 = 1.0 USDT; fees > 1.0 at 1% rate
        assert state.realized_pnl < 0.0

    def test_buy_fill_does_not_deduct_fees(self):
        """Fees are only deducted when the SELL fills (closing the round-trip)."""
        with mock.patch("config.FEE_RATE", 0.001):
            lv    = make_level(0, 29_000.0, buy_id="b001")
            state = GridState(levels=[lv])
            update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])

        assert state.realized_pnl == 0.0


# ── Duplicate fill prevention ─────────────────────────────────────────────────

class TestDuplicateFillPrevention:
    """Verify processed_fills blocks the same order ID from being counted twice."""

    def test_duplicate_buy_fill_is_skipped(self):
        lv    = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        fill  = buy_fill("b001", 29_000.0, 0.001)

        update_state_from_fills(state, [fill])
        # Re-add the order ID to the level to simulate a re-delivery scenario
        lv.buy_order_id = "b001"
        update_state_from_fills(state, [fill])

        assert state.total_buy_fills == 1       # counted only once

    def test_duplicate_sell_fill_does_not_double_pnl(self):
        lv    = make_level(1, 30_000.0, sell_id="s001", buy_fill_price=29_000.0)
        state = GridState(levels=[lv])
        fill  = sell_fill("s001", 30_000.0, 0.001)

        update_state_from_fills(state, [fill])
        first_pnl = state.realized_pnl

        # Simulate same fill arriving again (e.g. from both reconciliation and live poll)
        lv.sell_order_id  = "s001"
        lv.buy_fill_price = 29_000.0
        update_state_from_fills(state, [fill])

        assert state.realized_pnl == first_pnl  # not doubled
        assert state.total_sell_fills == 1      # counted only once

    def test_order_id_added_to_processed_set(self):
        lv    = make_level(0, 29_000.0, buy_id="b001")
        state = GridState(levels=[lv])
        update_state_from_fills(state, [buy_fill("b001", 29_000.0, 0.001)])
        assert "b001" in state.processed_fills

    def test_different_order_ids_both_processed(self):
        lv_a  = make_level(0, 29_000.0, buy_id="bA")
        lv_b  = make_level(1, 30_000.0, buy_id="bB")
        state = GridState(levels=[lv_a, lv_b])
        update_state_from_fills(state, [
            buy_fill("bA", 29_000.0, 0.001),
            buy_fill("bB", 30_000.0, 0.001),
        ])
        assert state.total_buy_fills == 2
        assert "bA" in state.processed_fills
        assert "bB" in state.processed_fills
