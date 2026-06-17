"""Backtest engine tests (offline, synthetic prices)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import run_backtest, walk_forward


def _prices(tickers, days=1200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-06-12", periods=days)
    data = {}
    for i, t in enumerate(tickers):
        steps = rng.normal(0.0003, 0.018, size=days)
        data[t] = 100 * np.exp(np.cumsum(steps))
    return pd.DataFrame(data, index=idx)


def test_backtest_runs_and_reports():
    tickers = [f"T{i}" for i in range(20)]
    res = run_backtest(_prices(tickers), "month", top_n=5)
    assert res.periods > 5
    assert set(res.metrics) >= {"strat_cagr", "ic_mean", "ic_t_stat", "max_drawdown"}
    # equity series aligns with reported period count
    assert len(res.strat_returns) == res.periods == len(res.bench_returns)
    # IC is a correlation, must be within [-1, 1]
    assert -1.0 <= res.metrics["ic_mean"] <= 1.0
    # suggested weights derived for each price factor in the month model
    assert res.suggested_weights


def test_no_lookahead_costs_reduce_return():
    tickers = [f"T{i}" for i in range(15)]
    p = _prices(tickers, seed=3)
    cheap = run_backtest(p, "week", top_n=4, cost_bps=0)
    pricey = run_backtest(p, "week", top_n=4, cost_bps=50)
    # higher costs cannot increase total return
    assert pricey.metrics["total_return"] <= cheap.metrics["total_return"] + 1e-9


def test_walk_forward_structure():
    tickers = [f"T{i}" for i in range(18)]
    wf = walk_forward(_prices(tickers), "month", top_n=5)
    assert set(wf) >= {"train", "test_current", "test_suggested", "train_suggested_weights"}
    assert "strat_cagr" in wf["test_suggested"]
