"""
main.py — Entry point; starts the Pionex grid-bot loop

Startup sequence
----------------
1. Validate config, check credentials.
2. Try to load a previously saved GridState from disk.
   a. If found and config matches → reconcile with exchange (detect offline
      fills, re-place missing orders) then resume.
   b. If found but config has changed → discard saved state, start fresh.
   c. If not found → build a new grid and place initial orders.
3. Save state after every operation that mutates it.
4. On clean Ctrl+C shutdown → cancel all orders, delete state file so the
   next startup builds a fresh grid rather than reconciling stale IDs.

Circuit breaker
---------------
If MAX_LOSS > 0 and realized losses reach or exceed that threshold,
CircuitBreakerTripped is raised.  The outer except block cancels all orders,
deletes the state file, and exits with code 2.
"""

import sys
import time

import config
import pionex_client as client
import state_store
from circuit_breaker import CircuitBreakerTripped, check as cb_check
from grid_engine import GridState, build_grid, update_state_from_fills
from logger import alert, logger
from monitor import display_status, log_cycle_summary
from order_manager import (
    cancel_all_orders,
    check_fills,
    place_grid_orders,
    reconcile_saved_state,
    replace_filled_orders,
)


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

    if config.MAX_LOSS > 0:
        logger.info("Circuit breaker enabled: max loss = %.6f USDT", config.MAX_LOSS)

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

    # ── Attempt to recover saved state ───────────────────────────────────────
    saved_state, cfg_matches = state_store.load()

    start_time = time.time()
    cycle      = 0

    try:
        if saved_state is not None and not cfg_matches:
            logger.warning(
                "Grid config has changed since the last run — "
                "discarding saved state and starting fresh."
            )
            state_store.delete()
            saved_state = None

        if saved_state is not None:
            # ── Resume from saved state ───────────────────────────────────────
            state = saved_state
            logger.info(
                "Resuming: %d levels | pnl=%.6f USDT | buys=%d sells=%d",
                len(state.levels), state.realized_pnl,
                state.total_buy_fills, state.total_sell_fills,
            )
            current_price    = client.get_price(config.SYMBOL)
            state.last_price = current_price

            if config.DRY_RUN:
                place_grid_orders(state, current_price)
            else:
                reconcile_saved_state(state, current_price)

            # Check breaker after reconciliation — losses may have accumulated
            # while the bot was offline (e.g. multiple sells filled at a loss).
            cb_check(state.realized_pnl)
            state_store.save(state)

        else:
            # ── Fresh start ───────────────────────────────────────────────────
            state            = GridState(levels=build_grid())
            current_price    = client.get_price(config.SYMBOL)
            state.last_price = current_price
            place_grid_orders(state, current_price)
            state_store.save(state)

        # Show dashboard immediately (before first sleep)
        display_status(state, current_price, start_time, cycle)
        log_cycle_summary(state, current_price, cycle)

        # ── Main polling loop ─────────────────────────────────────────────────
        while True:
            time.sleep(config.LOOP_INTERVAL)
            cycle += 1

            try:
                current_price    = client.get_price(config.SYMBOL)
                state.last_price = current_price

                if config.DRY_RUN:
                    import dry_run
                    dry_run.simulate_fills(current_price)

                # 1. Detect & process filled orders
                filled_orders = check_fills(state)
                if filled_orders:
                    update_state_from_fills(state, filled_orders)
                    # Check breaker immediately after P&L is updated — before
                    # placing any new counter-orders.
                    cb_check(state.realized_pnl)
                    replace_filled_orders(state)
                    state_store.save(state)

                # 2. Refresh console display
                display_status(state, current_price, start_time, cycle)
                log_cycle_summary(state, current_price, cycle)

            except (KeyboardInterrupt, CircuitBreakerTripped):
                raise
            except Exception as exc:
                alert(f"Unhandled error in cycle {cycle}: {exc}")
                logger.exception("Cycle %d error", cycle)
                display_status(state, state.last_price, start_time, cycle)

    except CircuitBreakerTripped as exc:
        print(f"\n\n{'!' * 60}")
        print(f"  CIRCUIT BREAKER TRIPPED")
        print(f"  {exc}")
        print(f"{'!' * 60}")
        logger.critical("Circuit breaker tripped — cancelling all orders and stopping.")
        cancel_all_orders(state)
        # Delete state so the next run starts fresh (don't resume into losses).
        state_store.delete()
        print(f"\nFinal realized P&L: {state.realized_pnl:+.6f} USDT")
        sys.exit(2)

    except KeyboardInterrupt:
        print("\n\nStopping bot — cancelling all open orders …")
        logger.info("KeyboardInterrupt received; cancelling all orders.")
        cancel_all_orders(state)
        state_store.delete()
        logger.info(
            "All orders cancelled.  Bot stopped.  Final realized P&L: %.6f USDT",
            state.realized_pnl,
        )
        print(f"Final realized P&L: {state.realized_pnl:+.6f} USDT")
        sys.exit(0)


if __name__ == "__main__":
    main()
