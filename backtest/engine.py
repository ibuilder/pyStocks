"""Cross-sectional ranking backtester (point-in-time, no lookahead).

Strategy under test: at each rebalance date, rank the universe by the horizon's
composite price-signal, buy an equal-weight basket of the top-N, hold for the
horizon, rebalance. We compare against an equal-weight-universe benchmark and
report the metric that actually matters for a ranking model — the Information
Coefficient (rank correlation between predicted score and realized forward return).

Honesty notes baked in:
  * Only PRICE factors are used (momentum/reversal/trend/low-vol). Fundamentals are
    excluded — yfinance gives only a current snapshot, so backtesting them leaks
    the future.
  * Universe = today's constituents → mild SURVIVORSHIP BIAS. Reported, not hidden.
  * Year horizon yields few non-overlapping samples; flagged when n is small.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockpredict.config import HORIZONS
from stockpredict.factors import price_factors
from stockpredict.model import HORIZON_WEIGHTS, _z

# Map each horizon's PRICE-only z-factors to the raw column they come from.
RAW_FOR_Z = {
    "z_ret_5": ("ret_5", 1.0),
    "z_ret_21": ("ret_21", 1.0),
    "z_ret_63": ("ret_63", 1.0),
    "z_ret_126": ("ret_126", 1.0),
    "z_mom_12_1": ("mom_12_1", 1.0),
    "z_lowvol": ("_lowvol", 1.0),   # derived: -mean(vol_21, vol_63)
    "z_trend": ("_trend", 1.0),     # derived:  mean(dist_ma50, dist_ma200)
}
PRICE_Z = set(RAW_FOR_Z)


def _price_weights(horizon: str) -> dict[str, float]:
    """The horizon weights restricted to price factors (fundamentals dropped)."""
    return {k: w for k, w in HORIZON_WEIGHTS[horizon].items() if k in PRICE_Z}


def _raw_factor_frame(window: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker raw price factors as of the end of `window` (point-in-time)."""
    pf = price_factors(window)
    if pf.empty:
        return pf
    pf = pf.copy()
    pf["_lowvol"] = -pf[["vol_21", "vol_63"]].mean(axis=1)
    pf["_trend"] = pf[["dist_ma50", "dist_ma200"]].mean(axis=1)
    return pf


def _composite(pf: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    score = pd.Series(0.0, index=pf.index)
    for zname, w in weights.items():
        raw_col, _ = RAW_FOR_Z[zname]
        if raw_col in pf:
            score = score + w * _z(pf[raw_col])
    return score


@dataclass
class BacktestResult:
    horizon: str
    top_n: int
    cost_bps: float
    periods: int
    strat_returns: pd.Series
    bench_returns: pd.Series
    ics: pd.Series                       # per-period Information Coefficient
    factor_ic: dict[str, float]          # mean IC of each raw factor
    suggested_weights: dict[str, float]  # evidence-based (∝ factor IC)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _spearman(a: pd.Series, b: pd.Series) -> float:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 5:
        return np.nan
    return df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank())


def run_backtest(
    prices: pd.DataFrame,
    horizon: str,
    top_n: int = 10,
    cost_bps: float = 10.0,        # round-trip cost (commission + slippage), basis points
    lookback: int = 300,          # days of window fed to factor computation
    warmup: int = 260,            # need >252 for 12-1 momentum / 1y return
) -> BacktestResult:
    """Run a non-overlapping walk-forward backtest for one horizon."""
    H = HORIZONS[horizon]["trading_days"]
    weights = _price_weights(horizon)
    prices = prices.sort_index()
    n = len(prices)

    strat, bench, ic_list, dates = [], [], [], []
    factor_vals: dict[str, list[float]] = {RAW_FOR_Z[z][0]: [] for z in weights}
    fwd_for_factor: list[float] = []  # parallel realized returns for factor IC

    i = warmup
    while i + H < n:
        window = prices.iloc[max(0, i - lookback): i + 1]
        pf = _raw_factor_frame(window)
        if pf.empty:
            i += H
            continue

        score = _composite(pf, weights).dropna()
        # forward return over the horizon for every ticker with data at both ends.
        p0 = prices.iloc[i]
        p1 = prices.iloc[i + H]
        fwd = (p1 / p0 - 1.0).reindex(score.index).dropna()
        common = score.index.intersection(fwd.index)
        if len(common) < max(5, top_n):
            i += H
            continue
        score, fwd = score.loc[common], fwd.loc[common]

        picks = score.sort_values(ascending=False).head(top_n).index
        cost = cost_bps / 1e4
        strat.append(float(fwd.loc[picks].mean()) - cost)   # round-trip cost
        bench.append(float(fwd.mean()))                      # equal-weight universe
        ic_list.append(_spearman(score, fwd))
        dates.append(prices.index[i])

        # accumulate per-factor IC inputs (raw factor vs realized fwd return)
        for z in weights:
            raw_col = RAW_FOR_Z[z][0]
            factor_vals[raw_col].append(_spearman(pf[raw_col].reindex(common), fwd))
        i += H

    idx = pd.DatetimeIndex(dates)
    strat_s = pd.Series(strat, index=idx, name="strategy")
    bench_s = pd.Series(bench, index=idx, name="benchmark")
    ic_s = pd.Series(ic_list, index=idx, name="ic").dropna()

    factor_ic = {col: float(np.nanmean(v)) if v else np.nan for col, v in factor_vals.items()}
    # Evidence-based weights ∝ each factor's mean IC (sign & magnitude from data).
    abs_sum = sum(abs(v) for v in factor_ic.values() if v == v) or 1.0
    z_by_raw = {RAW_FOR_Z[z][0]: z for z in weights}
    suggested = {z_by_raw[col]: round(ic / abs_sum, 3) for col, ic in factor_ic.items() if ic == ic}

    res = BacktestResult(
        horizon=horizon, top_n=top_n, cost_bps=cost_bps, periods=len(strat_s),
        strat_returns=strat_s, bench_returns=bench_s, ics=ic_s,
        factor_ic=factor_ic, suggested_weights=suggested,
    )
    res.metrics = _metrics(strat_s, bench_s, ic_s, H)
    res.warnings = _warnings(res, H)
    return res


def _metrics(strat: pd.Series, bench: pd.Series, ic: pd.Series, H: int) -> dict:
    ppy = 252.0 / H  # periods per year
    def ann_cagr(r):
        if len(r) == 0:
            return np.nan
        eq = (1 + r).prod()
        years = len(r) / ppy
        return eq ** (1 / years) - 1 if years > 0 and eq > 0 else np.nan
    def sharpe(r):
        if r.std(ddof=1) == 0 or len(r) < 2:
            return np.nan
        return (r.mean() / r.std(ddof=1)) * np.sqrt(ppy)
    def maxdd(r):
        eq = (1 + r).cumprod()
        return float((eq / eq.cummax() - 1).min()) if len(eq) else np.nan

    ic_mean = float(ic.mean()) if len(ic) else np.nan
    ic_t = (ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))) if len(ic) > 1 and ic.std(ddof=1) else np.nan
    return {
        "periods": len(strat),
        "strat_cagr": ann_cagr(strat),
        "bench_cagr": ann_cagr(bench),
        "excess_cagr": (ann_cagr(strat) - ann_cagr(bench)) if len(strat) else np.nan,
        "strat_sharpe": sharpe(strat),
        "bench_sharpe": sharpe(bench),
        "max_drawdown": maxdd(strat),
        "hit_rate": float((strat > 0).mean()) if len(strat) else np.nan,
        "ic_mean": ic_mean,
        "ic_t_stat": float(ic_t) if ic_t == ic_t else np.nan,
        "total_return": float((1 + strat).prod() - 1) if len(strat) else np.nan,
    }


def _warnings(res: BacktestResult, H: int) -> list[str]:
    w = []
    if res.periods < 20:
        w.append(f"Only {res.periods} non-overlapping samples — results are noisy; "
                 f"treat {res.horizon}-horizon numbers as indicative, not conclusive.")
    if res.metrics.get("ic_t_stat") is not None and abs(res.metrics.get("ic_t_stat") or 0) < 2:
        w.append("IC t-stat < 2 — the ranking signal is not statistically convincing here.")
    w.append("Fundamentals excluded (no point-in-time data); universe is current "
             "constituents (survivorship bias).")
    return w


def walk_forward(prices: pd.DataFrame, horizon: str, split: float = 0.6, **kw) -> dict:
    """Fit suggested weights on the first `split` of history, evaluate on the rest.

    Returns train/test BacktestResults plus an OOS comparison of current vs
    evidence-based weights — the honest 're-fit' the roadmap calls for.
    """
    prices = prices.sort_index()
    cut = int(len(prices) * split)
    train_p, test_p = prices.iloc[:cut], prices.iloc[cut - 300:]  # overlap warmup

    train = run_backtest(train_p, horizon, **kw)
    test = run_backtest(test_p, horizon, **kw)

    # Evaluate the TRAIN-derived suggested weights out-of-sample on TEST.
    oos_suggested = _run_with_weights(test_p, horizon, train.suggested_weights, **kw)
    return {
        "train": train,
        "test_current": test,
        "test_suggested": oos_suggested,
        "train_suggested_weights": train.suggested_weights,
    }


def _run_with_weights(prices, horizon, weights, top_n=10, cost_bps=10.0, lookback=300, warmup=260):
    """Backtest using an arbitrary weight dict (for OOS re-fit comparison)."""
    H = HORIZONS[horizon]["trading_days"]
    prices = prices.sort_index()
    n = len(prices)
    strat, bench, dates = [], [], []
    i = warmup
    while i + H < n:
        window = prices.iloc[max(0, i - lookback): i + 1]
        pf = _raw_factor_frame(window)
        if pf.empty:
            i += H
            continue
        score = _composite(pf, weights).dropna()
        fwd = (prices.iloc[i + H] / prices.iloc[i] - 1.0).reindex(score.index).dropna()
        common = score.index.intersection(fwd.index)
        if len(common) < max(5, top_n):
            i += H
            continue
        score, fwd = score.loc[common], fwd.loc[common]
        picks = score.sort_values(ascending=False).head(top_n).index
        strat.append(float(fwd.loc[picks].mean()) - cost_bps / 1e4)
        bench.append(float(fwd.mean()))
        dates.append(prices.index[i])
        i += H
    idx = pd.DatetimeIndex(dates)
    s = pd.Series(strat, index=idx)
    b = pd.Series(bench, index=idx)
    return _metrics(s, b, pd.Series(dtype=float), H)
