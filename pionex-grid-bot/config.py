"""
config.py — Grid parameters and API keys loaded from .env
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Pionex API credentials ────────────────────────────────────────────────────
API_KEY: str = os.getenv("PIONEX_API_KEY", "")
API_SECRET: str = os.getenv("PIONEX_API_SECRET", "")

# ── Trading pair ──────────────────────────────────────────────────────────────
SYMBOL: str = os.getenv("SYMBOL", "BTC_USDT")

# ── Grid parameters ───────────────────────────────────────────────────────────
GRID_LOWER: float = float(os.getenv("GRID_LOWER", "25000"))   # Lower price bound
GRID_UPPER: float = float(os.getenv("GRID_UPPER", "35000"))   # Upper price bound
GRID_COUNT: int   = int(os.getenv("GRID_COUNT", "10"))         # Number of grid levels
INVESTMENT: float = float(os.getenv("INVESTMENT", "1000"))     # Total USDT to invest

# ── Order / loop settings ─────────────────────────────────────────────────────
ORDER_TYPE: str    = os.getenv("ORDER_TYPE", "LIMIT")          # LIMIT or MARKET
LOOP_INTERVAL: int = int(os.getenv("LOOP_INTERVAL", "30"))     # Seconds between cycles

# ── Dry-run mode ───────────────────────────────────────────────────────────────
# When True, no real orders are placed.  Fill simulation is driven by live prices.
DRY_RUN: bool = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")

# ── Trading fees ──────────────────────────────────────────────────────────────
# Maker/taker fee rate as a decimal fraction (e.g. 0.001 = 0.1%).
# Pionex standard taker fee is 0.05 % — set to match your account tier.
# Fees for both legs of a round-trip (BUY + SELL) are subtracted from P&L.
FEE_RATE: float = float(os.getenv("FEE_RATE", "0.001"))

# ── Circuit breaker ───────────────────────────────────────────────────────────
# Cancel all orders and stop the bot if realized losses exceed this amount (USDT).
# Set to 0 to disable.
MAX_LOSS: float = float(os.getenv("MAX_LOSS", "0"))

# ── Derived grid step ─────────────────────────────────────────────────────────
GRID_STEP: float = (GRID_UPPER - GRID_LOWER) / GRID_COUNT

# ── Validation ────────────────────────────────────────────────────────────────
def validate() -> None:
    if not API_KEY or not API_SECRET:
        raise ValueError("PIONEX_API_KEY and PIONEX_API_SECRET must be set in .env")
    if GRID_LOWER >= GRID_UPPER:
        raise ValueError("GRID_LOWER must be less than GRID_UPPER")
    if GRID_COUNT < 2:
        raise ValueError("GRID_COUNT must be at least 2")
    if INVESTMENT <= 0:
        raise ValueError("INVESTMENT must be positive")
    if not 0.0 <= FEE_RATE < 1.0:
        raise ValueError("FEE_RATE must be between 0.0 and 1.0 (e.g. 0.001 for 0.1%)")
    if MAX_LOSS < 0:
        raise ValueError("MAX_LOSS must be >= 0 (use 0 to disable the circuit breaker)")
