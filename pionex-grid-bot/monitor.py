"""
monitor.py — Console status display and P&L tracking
"""

import os
import time
from datetime import datetime

from grid_engine import GridState
import config
from logger import logger


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def display_status(state: GridState, current_price: float,
                   start_time: float, cycle: int) -> None:
    """Print a live dashboard to the console."""
    _clear()
    elapsed = time.time() - start_time
    h, rem = divmod(int(elapsed), 3600)
    m, s   = divmod(rem, 60)

    dry_tag = "  *** DRY-RUN — no real orders ***" if config.DRY_RUN else ""
    print("=" * 60)
    print(f"  Pionex Grid Bot  —  {config.SYMBOL}{dry_tag}")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)
    print(f"  Uptime         : {h:02d}h {m:02d}m {s:02d}s  (cycle #{cycle})")
    print(f"  Current price  : {current_price:.4f}")
    print(f"  Grid range     : {config.GRID_LOWER:.4f} – {config.GRID_UPPER:.4f}")
    print(f"  Grid levels    : {config.GRID_COUNT}  (step {config.GRID_STEP:.4f})")
    print()
    print(f"  Buy  fills     : {state.total_buy_fills}")
    print(f"  Sell fills     : {state.total_sell_fills}")
    print(f"  Realized P&L   : {state.realized_pnl:+.4f} USDT")

    if config.MAX_LOSS > 0:
        loss       = max(0.0, -state.realized_pnl)          # 0 when P&L is positive
        used_frac  = min(1.0, loss / config.MAX_LOSS)
        filled     = int(used_frac * 10)
        bar        = "▓" * filled + "░" * (10 - filled)
        print(f"  Max loss       : -{config.MAX_LOSS:.4f} USDT  [{bar}] {used_frac * 100:.1f}% consumed")

    print()

    # Show per-level order status
    print(f"  {'Level':>5}  {'Price':>10}  {'Buy':>18}  {'Sell':>18}")
    print("  " + "-" * 55)
    for lv in reversed(state.levels):
        marker = " ◄" if abs(lv.price - current_price) < config.GRID_STEP / 2 else ""
        buy_s  = lv.buy_order_id[:8] + "…" if lv.buy_order_id  else "—"
        sell_s = lv.sell_order_id[:8] + "…" if lv.sell_order_id else "—"
        print(f"  {lv.index:>5}  {lv.price:>10.4f}  {buy_s:>18}  {sell_s:>18}{marker}")

    print("=" * 60)
    print("  Press Ctrl+C to stop the bot.")


def log_cycle_summary(state: GridState, current_price: float, cycle: int) -> None:
    """Write a concise cycle summary to the log file."""
    logger.info(
        "Cycle %d | price=%.4f | buys=%d sells=%d | pnl=%.4f USDT",
        cycle, current_price, state.total_buy_fills,
        state.total_sell_fills, state.realized_pnl,
    )
