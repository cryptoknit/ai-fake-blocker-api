"""
circuit_breaker.py — Maximum-loss safeguard.

When MAX_LOSS > 0, check() inspects the current realized P&L after every fill
batch.  If losses have reached or exceeded the threshold it raises
CircuitBreakerTripped, which main.py catches at the outer scope so it can
cancel all orders, remove the state file, and exit cleanly.

Setting MAX_LOSS=0 (the default) disables the breaker entirely.
"""

import config
from logger import logger, alert


class CircuitBreakerTripped(Exception):
    """Raised when realized losses exceed the configured MAX_LOSS threshold."""

    def __init__(self, pnl: float, limit: float) -> None:
        self.pnl   = pnl
        self.limit = limit
        super().__init__(
            f"Circuit breaker tripped: realized P&L {pnl:+.6f} USDT "
            f"has reached or exceeded the max-loss limit of -{limit:.6f} USDT"
        )


def check(pnl: float) -> None:
    """
    Raise CircuitBreakerTripped if *pnl* has breached the MAX_LOSS threshold.

    A MAX_LOSS of 0 means the breaker is disabled and this function is a
    no-op.  Only negative P&L (net losses) can trigger the breaker; positive
    or zero P&L is always safe.
    """
    if config.MAX_LOSS <= 0:
        return   # circuit breaker disabled

    if pnl <= -config.MAX_LOSS:
        msg = (
            f"CIRCUIT BREAKER: realized P&L {pnl:+.6f} USDT has reached "
            f"the max-loss limit of -{config.MAX_LOSS:.6f} USDT"
        )
        alert(msg)
        raise CircuitBreakerTripped(pnl, config.MAX_LOSS)
