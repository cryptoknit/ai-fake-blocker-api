"""
logger.py — File logging and error alerts
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "grid_bot.log")

os.makedirs(LOG_DIR, exist_ok=True)

# Root logger for the bot
logger = logging.getLogger("grid_bot")
logger.setLevel(logging.DEBUG)

# ── File handler (rotates at 5 MB, keeps 3 backups) ──────────────────────────
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(_fh)

# ── Console handler ───────────────────────────────────────────────────────────
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_ch)


def alert(message: str) -> None:
    """Log a critical alert.  Hook in email/Telegram/Slack here if needed."""
    logger.critical("ALERT: %s", message)
