"""
tests/test_state_store.py — Verify state serialisation, deserialisation, and
config-mismatch detection without touching the filesystem in a permanent way.
"""

import json
import os
import tempfile
import unittest.mock as mock

import pytest

from grid_engine import GridLevel, GridState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state() -> GridState:
    """Build a small, realistic GridState with a mix of order and fill data."""
    levels = [
        GridLevel(index=0, price=29_000.0, buy_order_id="b001"),
        GridLevel(index=1, price=30_000.0, sell_order_id="s002",
                  buy_fill_price=29_000.0),
        GridLevel(index=2, price=31_000.0),
    ]
    return GridState(
        levels=levels,
        last_price=29_800.0,
        total_buy_fills=3,
        total_sell_fills=2,
        realized_pnl=1.5,
    )


def _mock_config(symbol="BTC_USDT", lower=25_000.0, upper=35_000.0, count=10):
    """Return a context-manager that patches the config values used by state_store."""
    return mock.patch.multiple(
        "config",
        SYMBOL=symbol,
        GRID_LOWER=lower,
        GRID_UPPER=upper,
        GRID_COUNT=count,
    )


# ── Roundtrip serialisation ───────────────────────────────────────────────────

class TestRoundtrip:

    def test_all_scalar_fields_survive_roundtrip(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")

            original = _make_state()
            state_store.save(original)
            recovered, matches = state_store.load()

        assert matches is True
        assert recovered is not None
        assert recovered.last_price       == original.last_price
        assert recovered.total_buy_fills  == original.total_buy_fills
        assert recovered.total_sell_fills == original.total_sell_fills
        assert abs(recovered.realized_pnl - original.realized_pnl) < 1e-9

    def test_all_levels_survive_roundtrip(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")

            original = _make_state()
            state_store.save(original)
            recovered, _ = state_store.load()

        assert len(recovered.levels) == len(original.levels)

        for orig, rec in zip(original.levels, recovered.levels):
            assert rec.index          == orig.index
            assert rec.price          == orig.price
            assert rec.buy_order_id   == orig.buy_order_id
            assert rec.sell_order_id  == orig.sell_order_id
            assert rec.filled_buy     == orig.filled_buy
            assert rec.filled_sell    == orig.filled_sell
            assert rec.buy_fill_price == orig.buy_fill_price

    def test_none_order_ids_survive_as_none(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")

            state = GridState(levels=[GridLevel(index=0, price=29_000.0)])
            state_store.save(state)
            recovered, _ = state_store.load()

        lv = recovered.levels[0]
        assert lv.buy_order_id  is None
        assert lv.sell_order_id is None
        assert lv.buy_fill_price is None


# ── No saved state ────────────────────────────────────────────────────────────

class TestNoFile:

    def test_load_returns_none_when_no_file_exists(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "does_not_exist.json")
            result, matches = state_store.load()

        assert result is None
        assert matches is True

    def test_delete_is_a_noop_when_no_file_exists(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "does_not_exist.json")
            state_store.delete()    # must not raise


# ── Config mismatch detection ─────────────────────────────────────────────────

class TestConfigMismatch:

    def _save_then_reload_with(self, tmp_path, save_cfg, load_cfg):
        """Save with save_cfg, reload with load_cfg, return config_matches."""
        path = str(tmp_path / "grid_state.json")

        with mock.patch.multiple("config", **save_cfg):
            import state_store
            state_store.STATE_FILE = path
            state_store.save(GridState(levels=[GridLevel(index=0, price=1.0)]))

        with mock.patch.multiple("config", **load_cfg):
            state_store.STATE_FILE = path
            _, matches = state_store.load()

        return matches

    def test_same_config_matches(self, tmp_path):
        cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                   GRID_UPPER=35_000.0, GRID_COUNT=10)
        assert self._save_then_reload_with(tmp_path, cfg, cfg) is True

    def test_symbol_change_detected(self, tmp_path):
        save_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        load_cfg = dict(SYMBOL="ETH_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        assert self._save_then_reload_with(tmp_path, save_cfg, load_cfg) is False

    def test_grid_lower_change_detected(self, tmp_path):
        save_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        load_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=26_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        assert self._save_then_reload_with(tmp_path, save_cfg, load_cfg) is False

    def test_grid_upper_change_detected(self, tmp_path):
        save_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        load_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=40_000.0, GRID_COUNT=10)
        assert self._save_then_reload_with(tmp_path, save_cfg, load_cfg) is False

    def test_grid_count_change_detected(self, tmp_path):
        save_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=10)
        load_cfg = dict(SYMBOL="BTC_USDT", GRID_LOWER=25_000.0,
                        GRID_UPPER=35_000.0, GRID_COUNT=20)
        assert self._save_then_reload_with(tmp_path, save_cfg, load_cfg) is False


# ── Atomic write robustness ───────────────────────────────────────────────────

class TestAtomicWrite:

    def test_state_file_written_atomically(self, tmp_path):
        """After save(), the .tmp file must not exist (it was renamed away)."""
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")
            state_store.save(_make_state())

        assert not os.path.exists(state_store.STATE_FILE + ".tmp")
        assert os.path.exists(state_store.STATE_FILE)

    def test_saved_file_is_valid_json(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")
            state_store.save(_make_state())

        with open(state_store.STATE_FILE) as fh:
            data = json.load(fh)   # raises if not valid JSON

        assert "levels" in data
        assert "saved_at" in data
        assert "config" in data

    def test_corrupt_file_treated_as_missing(self, tmp_path):
        path = str(tmp_path / "grid_state.json")
        with open(path, "w") as fh:
            fh.write("{ this is not valid json ~~~")

        with _mock_config():
            import state_store
            state_store.STATE_FILE = path
            result, matches = state_store.load()

        assert result is None
        assert matches is True

    def test_delete_removes_file(self, tmp_path):
        with _mock_config():
            import state_store
            state_store.STATE_FILE = str(tmp_path / "grid_state.json")
            state_store.save(_make_state())
            assert os.path.exists(state_store.STATE_FILE)
            state_store.delete()
            assert not os.path.exists(state_store.STATE_FILE)
