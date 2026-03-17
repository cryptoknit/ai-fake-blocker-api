"""
main.py — Entry point; starts the Pionex grid-bot loop
"""

import time
import sys

import config
import pionex_client as client
from grid_engine import GridState, build_grid, update_state_from_fills
from order_manager import (
    place_grid_orders,
    cancel_all_orders,
    check_fills,
    replace_filled_orders,
)
from monitor import display_status, log_cycle_summary
from logger import logger, alert


def main() -> None:
    # ── Validate config ───────────────────────────────────────────────────────
    try:
        config.validate()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(1)

    logger.info("Starting Pionex Grid Bot | symbol=%s | range=[%.4f, %.4f] | levels=%d",
                config.SYMBOL, config.GRID_LOWER, config.GRID_UPPER, config.GRID_COUNT)

    # ── Build initial grid ────────────────────────────────────────────────────
    state = GridState(levels=build_grid())
    start_time = time.time()
    cycle = 0

    try:
        # ── Initial order placement ───────────────────────────────────────────
        current_price = client.get_price(config.SYMBOL)
        state.last_price = current_price
        place_grid_orders(state, current_price)

        # ── Main loop ─────────────────────────────────────────────────────────
        while True:
            cycle += 1
            try:
                current_price = client.get_price(config.SYMBOL)
                state.last_price = current_price

                # 1. Detect filled orders
                filled_orders = check_fills(state)
                if filled_orders:
                    update_state_from_fills(state, filled_orders)
                    replace_filled_orders(state)

                # 2. Display live status
                display_status(state, current_price, start_time, cycle)
                log_cycle_summary(state, current_price, cycle)

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                alert(f"Unhandled error in cycle {cycle}: {exc}")
                logger.exception("Cycle %d error", cycle)

            time.sleep(config.LOOP_INTERVAL)

    except KeyboardInterrupt:
        print("\n\nStopping bot — cancelling all open orders …")
        logger.info("KeyboardInterrupt received; cancelling orders.")
        cancel_all_orders(state)
        logger.info("All orders cancelled. Bot stopped. Final P&L: %.4f USDT",
                    state.realized_pnl)
        print(f"Final realized P&L: {state.realized_pnl:+.4f} USDT")
        sys.exit(0)


if __name__ == "__main__":
    main()
