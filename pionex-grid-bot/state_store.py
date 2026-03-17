"""
state_store.py — Persist GridState to disk so the bot can recover after a crash.

Format
------
A single JSON file (state/grid_state.json).  The top level includes the grid
config that was active when the state was saved so a config mismatch can be
detected at startup and a clean slate offered automatically.

Atomic writes
-------------
The file is written to a sibling .tmp path then renamed into place.  On POSIX
os.replace() is atomic, so a crash during the write can never leave a partially-
written (corrupt) state file — the previous good file is always there until the
new one is fully flushed.
"""

import dataclasses
import json
import os
from datetime import datetime, timezone
from typing import Optional

import config
from grid_engine import GridLevel, GridState
from logger import logger

_BOT_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_DIR  = os.path.join(_BOT_DIR, "state")
STATE_FILE = os.path.join(STATE_DIR, "grid_state.json")


# ── Save ──────────────────────────────────────────────────────────────────────

def save(state: GridState) -> None:
    """
    Serialise *state* to STATE_FILE atomically.

    Called after every operation that changes state (order placement, fill
    processing, counter-order placement) so the on-disk snapshot is always
    within one operation of reality.
    """
    os.makedirs(STATE_DIR, exist_ok=True)

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        # Grid config fingerprint — used at startup to detect mismatches
        "config": {
            "symbol":     config.SYMBOL,
            "grid_lower": config.GRID_LOWER,
            "grid_upper": config.GRID_UPPER,
            "grid_count": config.GRID_COUNT,
        },
        "last_price":       state.last_price,
        "total_buy_fills":  state.total_buy_fills,
        "total_sell_fills": state.total_sell_fills,
        "realized_pnl":     state.realized_pnl,
        "processed_fills":  sorted(state.processed_fills),   # set → sorted list for JSON
        "levels": [dataclasses.asdict(lv) for lv in state.levels],
    }

    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, STATE_FILE)   # atomic on POSIX
    except OSError as exc:
        logger.error("Failed to save state: %s", exc)
        # Non-fatal — bot keeps running; worst case is a less-recent snapshot
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── Load ──────────────────────────────────────────────────────────────────────

def load() -> tuple[Optional[GridState], bool]:
    """
    Attempt to load a previously saved GridState.

    Returns
    -------
    (state, config_matches)
        state          – the deserialized GridState, or None if no file exists
        config_matches – False when the saved config differs from the current
                         config (symbol, bounds, or level count changed)

    The caller is responsible for deciding what to do on a config mismatch;
    the typical response is to discard the file and start fresh.
    """
    if not os.path.exists(STATE_FILE):
        return None, True

    try:
        with open(STATE_FILE) as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not read state file (%s); starting fresh.", exc)
        return None, True

    # ── Config mismatch check ─────────────────────────────────────────────────
    saved_cfg = payload.get("config", {})
    config_matches = (
        saved_cfg.get("symbol")     == config.SYMBOL     and
        saved_cfg.get("grid_lower") == config.GRID_LOWER and
        saved_cfg.get("grid_upper") == config.GRID_UPPER and
        saved_cfg.get("grid_count") == config.GRID_COUNT
    )

    # ── Reconstruct GridState ─────────────────────────────────────────────────
    try:
        levels = [GridLevel(**lv) for lv in payload["levels"]]
        state  = GridState(
            levels           = levels,
            last_price       = float(payload.get("last_price",       0.0)),
            total_buy_fills  = int(payload.get("total_buy_fills",    0)),
            total_sell_fills = int(payload.get("total_sell_fills",   0)),
            realized_pnl     = float(payload.get("realized_pnl",     0.0)),
            processed_fills  = set(payload.get("processed_fills",    [])),
        )
    except (KeyError, TypeError) as exc:
        logger.error("State file is malformed (%s); starting fresh.", exc)
        return None, True

    saved_at = payload.get("saved_at", "unknown time")
    logger.info(
        "Loaded saved state: %d levels  pnl=%.6f USDT  saved_at=%s",
        len(levels), state.realized_pnl, saved_at,
    )
    return state, config_matches


# ── Delete ────────────────────────────────────────────────────────────────────

def delete() -> None:
    """
    Remove the state file after a clean shutdown (Ctrl+C → cancel all).
    This signals that the next startup should build a fresh grid rather than
    attempting to reconcile stale order IDs.
    """
    try:
        os.remove(STATE_FILE)
        logger.info("State file deleted (clean shutdown).")
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not delete state file: %s", exc)
