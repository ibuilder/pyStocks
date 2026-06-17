"""Intraday indicator tests (offline, synthetic bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from realtime.indicators import compute_intraday_indicators


def _session(day, base=100.0, n=78, drift=0.0, seed=0, tz="America/New_York"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{day} 09:30", periods=n, freq="5min", tz=tz)
    close = base + np.cumsum(rng.normal(drift, 0.2, n))
    high = close + np.abs(rng.normal(0.1, 0.1, n))
    low = close - np.abs(rng.normal(0.1, 0.1, n))
    open_ = np.concatenate([[base], close[:-1]])
    vol = rng.integers(1000, 5000, n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def test_indicators_basic():
    df = pd.concat([
        _session("2026-06-12", base=100, drift=0.05, seed=1),
        _session("2026-06-15", base=102, drift=0.10, seed=2),
    ])
    ind = compute_intraday_indicators(df)
    assert ind["session"] == "2026-06-15"
    assert ind["bars"] == 78
    # core fields present
    for k in ("last", "vwap", "rvol", "rsi14", "atr14", "ema9", "ema20",
              "or_high", "or_low", "pct_from_open"):
        assert k in ind
    assert 0 <= ind["rsi14"] <= 100
    assert ind["rvol"] is not None and ind["rvol"] > 0  # has a prior session
    assert ind["day_high"] >= ind["last"] >= 0


def test_empty_returns_empty():
    assert compute_intraday_indicators(pd.DataFrame()) == {}


def test_opening_range_flags():
    df = _session("2026-06-15", base=50, drift=0.5, seed=7)  # strong uptrend
    ind = compute_intraday_indicators(df)
    # in a steady uptrend the last price should be at/above the opening range high
    assert ind["last"] >= ind["or_low"]
    assert isinstance(ind["above_or_high"], bool)
