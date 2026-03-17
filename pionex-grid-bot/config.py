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
ORDER_TYPE: str  = os.getenv("ORDER_TYPE", "LIMIT")   # LIMIT or MARKET
LOOP_INTERVAL: int = int(os.getenv("LOOP_INTERVAL", "30"))  # Seconds between cycles

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
