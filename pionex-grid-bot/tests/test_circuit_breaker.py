"""
tests/test_circuit_breaker.py — Verify the maximum-loss circuit breaker.
"""

import unittest.mock as mock

import pytest

from circuit_breaker import CircuitBreakerTripped, check


def _with_max_loss(value: float):
    return mock.patch("config.MAX_LOSS", value)


# ── Disabled (MAX_LOSS = 0) ───────────────────────────────────────────────────

class TestDisabled:

    def test_zero_max_loss_never_trips_on_small_loss(self):
        with _with_max_loss(0.0):
            check(-999_999.0)   # should not raise

    def test_negative_max_loss_never_trips(self):
        # validate() rejects negatives, but check() should still be safe
        with _with_max_loss(-50.0):
            check(-1000.0)

    def test_positive_pnl_never_trips_when_disabled(self):
        with _with_max_loss(0.0):
            check(100.0)


# ── Safe zone (loss < MAX_LOSS) ───────────────────────────────────────────────

class TestSafeZone:

    def test_zero_pnl_is_safe(self):
        with _with_max_loss(50.0):
            check(0.0)

    def test_positive_pnl_is_safe(self):
        with _with_max_loss(50.0):
            check(99.99)

    def test_loss_strictly_below_limit_is_safe(self):
        with _with_max_loss(50.0):
            check(-49.999999)

    def test_one_cent_below_limit_is_safe(self):
        with _with_max_loss(50.0):
            check(-49.99)


# ── Boundary (pnl == -MAX_LOSS) ───────────────────────────────────────────────

class TestBoundary:

    def test_exact_limit_trips(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped):
                check(-50.0)

    def test_one_satoshi_over_limit_trips(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped):
                check(-50.000001)


# ── Exceeded (pnl < -MAX_LOSS) ────────────────────────────────────────────────

class TestExceeded:

    def test_large_loss_trips(self):
        with _with_max_loss(100.0):
            with pytest.raises(CircuitBreakerTripped):
                check(-500.0)

    def test_small_limit_trips_quickly(self):
        with _with_max_loss(0.01):
            with pytest.raises(CircuitBreakerTripped):
                check(-0.02)


# ── Exception attributes ──────────────────────────────────────────────────────

class TestExceptionAttributes:

    def test_exception_carries_pnl(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped) as exc_info:
                check(-75.5)
        assert exc_info.value.pnl == -75.5

    def test_exception_carries_limit(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped) as exc_info:
                check(-75.5)
        assert exc_info.value.limit == 50.0

    def test_exception_message_contains_pnl(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped) as exc_info:
                check(-75.5)
        assert "-75.5" in str(exc_info.value) or "75" in str(exc_info.value)

    def test_exception_message_contains_limit(self):
        with _with_max_loss(50.0):
            with pytest.raises(CircuitBreakerTripped) as exc_info:
                check(-75.5)
        assert "50" in str(exc_info.value)

    def test_exception_is_subclass_of_exception(self):
        assert issubclass(CircuitBreakerTripped, Exception)


# ── Various limit values ──────────────────────────────────────────────────────

class TestVariousLimits:

    @pytest.mark.parametrize("max_loss,pnl,should_trip", [
        (10.0,    -9.99,   False),
        (10.0,   -10.0,    True),
        (10.0,   -10.01,   True),
        (0.5,     -0.49,   False),
        (0.5,     -0.5,    True),
        (1000.0, -999.99,  False),
        (1000.0, -1000.0,  True),
    ])
    def test_parametrized_thresholds(self, max_loss, pnl, should_trip):
        with _with_max_loss(max_loss):
            if should_trip:
                with pytest.raises(CircuitBreakerTripped):
                    check(pnl)
            else:
                check(pnl)   # must not raise
