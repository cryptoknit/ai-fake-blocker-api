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

    if config.DRY_RUN:
        print("=" * 60)
        print("  *** DRY-RUN MODE — no real orders will be placed ***")
        print("=" * 60)
        logger.info("DRY-RUN mode enabled.")

    logger.info(
        "Starting Pionex Grid Bot | symbol=%s | range=[%.6f, %.6f] | levels=%d | invest=%.2f USDT",
        config.SYMBOL, config.GRID_LOWER, config.GRID_UPPER,
        config.GRID_COUNT, config.INVESTMENT,
    )

    # ── Verify API credentials before doing anything else ────────────────────
    try:
        client.check_credentials()
    except RuntimeError as exc:
        print(f"\nStartup error: {exc}")
        sys.exit(1)

    # ── Build initial grid ────────────────────────────────────────────────────
    state      = GridState(levels=build_grid())
    start_time = time.time()
    cycle      = 0

    try:
        # ── Fetch price & place initial orders ────────────────────────────────
        current_price    = client.get_price(config.SYMBOL)
        state.last_price = current_price
        place_grid_orders(state, current_price)

        # Show status immediately (before first sleep)
        display_status(state, current_price, start_time, cycle)
        log_cycle_summary(state, current_price, cycle)

        # ── Main polling loop ─────────────────────────────────────────────────
        while True:
            time.sleep(config.LOOP_INTERVAL)
            cycle += 1

            try:
                current_price    = client.get_price(config.SYMBOL)
                state.last_price = current_price

                # In dry-run mode advance the simulated order book before
                # checking fills so the cycle sees up-to-date statuses.
                if config.DRY_RUN:
                    import dry_run
                    dry_run.simulate_fills(current_price)

                # 1. Detect & process filled orders
                filled_orders = check_fills(state)
                if filled_orders:
                    update_state_from_fills(state, filled_orders)
                    replace_filled_orders(state)

                # 2. Refresh console display
                display_status(state, current_price, start_time, cycle)
                log_cycle_summary(state, current_price, cycle)

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                alert(f"Unhandled error in cycle {cycle}: {exc}")
                logger.exception("Cycle %d error", cycle)
                # Display last known state even if the cycle errored
                display_status(state, state.last_price, start_time, cycle)

    except KeyboardInterrupt:
        print("\n\nStopping bot — cancelling all open orders …")
        logger.info("KeyboardInterrupt received; cancelling all orders.")
        cancel_all_orders(state)
        logger.info(
            "All orders cancelled.  Bot stopped.  Final realized P&L: %.6f USDT",
            state.realized_pnl,
        )
        print(f"Final realized P&L: {state.realized_pnl:+.6f} USDT")
        sys.exit(0)


if __name__ == "__main__":
    main()
