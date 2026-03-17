"""
tests/test_order_manager.py — Unit tests for check_fills and related logic.

All Pionex API calls are mocked; no network activity occurs.
"""

import unittest.mock as mock

from grid_engine import GridLevel, GridState
from order_manager import check_fills


class TestPartialFill:

    def test_partial_fill_does_not_trigger_full_cycle(self):
        """
        When check_fills fetches an order whose status is PARTIALLY_FILLED it
        must NOT add it to the returned fill list, must NOT clear the order
        reference, and must NOT set filled_buy — so replace_filled_orders will
        never see the order and will not place a counter-order.
        """
        lv = GridLevel(index=0, price=29_000.0)
        lv.buy_order_id = "b001"
        state = GridState(levels=[lv])

        partial_order = {
            "orderId":    "b001",
            "side":       "BUY",
            "price":      "29000",
            "filledSize": "0.0005",
            "status":     "PARTIALLY_FILLED",
        }

        with mock.patch("pionex_client.get_open_orders", return_value=[]), \
             mock.patch("pionex_client.get_order", return_value=partial_order), \
             mock.patch("config.SYMBOL", "BTC_USDT"):
            filled = check_fills(state)

        # The PARTIALLY_FILLED order is not returned as a completed fill
        assert filled == []
        # The order reference is preserved so the bot keeps polling
        assert lv.buy_order_id == "b001"
        # The filled flag is never set — replace_filled_orders won't fire
        assert lv.filled_buy is False
