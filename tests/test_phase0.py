"""Phase 0 tests: model determinism, storage round-trip, pipeline persistence.

Network-dependent pieces (yfinance) are stubbed so these run offline and fast.
    pytest -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockpredict.data import Fundamentals
from stockpredict.model import estimate_returns


def _fake_prices(tickers, days=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-06-12", periods=days)
    data = {}
    for i, t in enumerate(tickers):
        steps = rng.normal(0.0005 * (i + 1), 0.02, size=days)
        data[t] = 100 * np.exp(np.cumsum(steps))
    return pd.DataFrame(data, index=idx)


def _fake_funds(tickers):
    return {
        t: Fundamentals(ticker=t, name=t, price=100.0, pe=15 + i, peg=1.2,
                        eps_growth=0.18, profit_margin=0.22, debt_to_equity=0.4,
                        market_cap=1e11, sector="Tech")
        for i, t in enumerate(tickers)
    }


def test_estimate_returns_shapes_and_ordering():
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    prices = _fake_prices(tickers)
    res = estimate_returns(prices, _fake_funds(tickers))

    for horizon in ("week", "month", "year"):
        df = res[horizon]
        assert not df.empty
        # ranked descending by estimated return
        assert (df["est_return"].values == sorted(df["est_return"].values, reverse=True)).all()
        # confidence is bounded 0..78 (the cap), bands bracket the estimate
        assert df["confidence"].between(0, 78).all()
        assert (df["band_lo"] <= df["est_return"]).all()
        assert (df["est_return"] <= df["band_hi"]).all()


def test_estimates_are_capped():
    # A runaway momentum name must not produce a runaway estimate.
    tickers = ["MOON", "FLAT", "DOWN"]
    prices = _fake_prices(tickers, seed=1)
    prices["MOON"] = np.linspace(10, 200, len(prices))  # huge uptrend
    res = estimate_returns(prices, _fake_funds(tickers))
    assert res["year"]["est_return"].max() <= 0.45  # base 0.08 + cap 0.35


def test_storage_roundtrip(tmp_path, monkeypatch):
    # Point storage at a throwaway SQLite file.
    import importlib
    from stockpredict import config as cfg
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    import stockpredict.storage as storage
    importlib.reload(storage)

    tickers = ["AAA", "BBB", "CCC"]
    res = estimate_returns(_fake_prices(tickers), _fake_funds(tickers))
    rid = storage.save_snapshot(res, universe_source="watchlist")
    assert rid

    loaded = storage.load_latest()
    assert set(loaded) == {"week", "month", "year"}
    assert loaded["year"]["ticker"].notna().all()
    assert storage.run_count() == 1
