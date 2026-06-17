"""Factor computation from price history + fundamentals.

Each ticker is reduced to a handful of well-studied raw factor inputs. The model
(model.py) z-scores these cross-sectionally and blends them per horizon. Sources
for the factor choices are summarized in README.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Fundamentals

TRADING_DAYS_YEAR = 252


def price_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute raw price-based factors. `prices` columns=tickers, index=dates.

    Returns a DataFrame indexed by ticker with raw (not yet z-scored) factors.
    """
    out = {}
    p = prices.sort_index()
    rets = p.pct_change()

    for t in p.columns:
        s = p[t].dropna()
        if len(s) < 30:
            continue
        last = s.iloc[-1]

        def ret_over(days):
            if len(s) > days:
                return s.iloc[-1] / s.iloc[-1 - days] - 1.0
            return np.nan

        ret_5 = ret_over(5)
        ret_21 = ret_over(21)
        ret_63 = ret_over(63)
        ret_126 = ret_over(126)
        ret_252 = ret_over(252)

        # 12-1 momentum: return from ~252d ago to ~21d ago (skip the last month
        # to avoid contaminating momentum with short-term reversal).
        if len(s) > 252:
            mom_12_1 = s.iloc[-21] / s.iloc[-252] - 1.0
        elif len(s) > 63:
            mom_12_1 = s.iloc[-21] / s.iloc[0] - 1.0
        else:
            mom_12_1 = np.nan

        daily = rets[t].dropna()
        vol_21 = daily.tail(21).std() * np.sqrt(TRADING_DAYS_YEAR) if len(daily) >= 21 else np.nan
        vol_63 = daily.tail(63).std() * np.sqrt(TRADING_DAYS_YEAR) if len(daily) >= 63 else np.nan

        ma50 = s.tail(50).mean() if len(s) >= 50 else np.nan
        ma200 = s.tail(200).mean() if len(s) >= 200 else np.nan
        dist_ma50 = (last / ma50 - 1.0) if ma50 and not np.isnan(ma50) else np.nan
        dist_ma200 = (last / ma200 - 1.0) if ma200 and not np.isnan(ma200) else np.nan

        hi_252 = s.tail(252).max()
        dist_52w_high = (last / hi_252 - 1.0) if hi_252 else np.nan  # <=0; near 0 = strong

        out[t] = dict(
            price=last,
            ret_5=ret_5, ret_21=ret_21, ret_63=ret_63,
            ret_126=ret_126, ret_252=ret_252, mom_12_1=mom_12_1,
            vol_21=vol_21, vol_63=vol_63,
            dist_ma50=dist_ma50, dist_ma200=dist_ma200,
            dist_52w_high=dist_52w_high,
            hist_days=len(s),
        )
    return pd.DataFrame.from_dict(out, orient="index")


# --------------------------- fundamental quality/value sub-scores (0..1) ---
PE_IDEAL_LOW, PE_IDEAL_HIGH, PE_HARD_CAP = 10.0, 25.0, 50.0


def _pe_score(pe):
    if pe is None or pe <= 0:
        return np.nan
    if PE_IDEAL_LOW <= pe <= PE_IDEAL_HIGH:
        return 1.0
    if pe < PE_IDEAL_LOW:
        return 0.7
    if pe >= PE_HARD_CAP:
        return 0.0
    return max(0.0, 1.0 - (pe - PE_IDEAL_HIGH) / (PE_HARD_CAP - PE_IDEAL_HIGH))


def _peg_score(peg):
    if peg is None or peg <= 0:
        return np.nan
    if peg <= 1.0:
        return 1.0
    if peg >= 3.0:
        return 0.0
    return max(0.0, 1.0 - (peg - 1.0) / 2.0)


def _growth_score(g):
    if g is None:
        return np.nan
    return float(np.clip(g / 0.25, 0.0, 1.0)) if g > 0 else 0.0


def _margin_score(m):
    if m is None:
        return np.nan
    return float(np.clip(m / 0.20, 0.0, 1.0)) if m > 0 else 0.0


def _leverage_score(de):
    if de is None:
        return np.nan
    de = de / 100.0 if de > 5 else de  # some feeds report D/E as a percentage
    if de <= 0.5:
        return 1.0
    if de >= 2.5:
        return 0.0
    return max(0.0, 1.0 - (de - 0.5) / 2.0)


def quality_value_score(f: Fundamentals) -> tuple[float | None, dict]:
    """Composite 0..1 quality/value score (weighted avg over present factors)."""
    weights = {"pe": 0.30, "peg": 0.20, "growth": 0.20, "margin": 0.20, "leverage": 0.10}
    raw = {
        "pe": _pe_score(f.pe),
        "peg": _peg_score(f.peg),
        "growth": _growth_score(f.eps_growth),
        "margin": _margin_score(f.profit_margin),
        "leverage": _leverage_score(f.debt_to_equity),
    }
    present = {k: v for k, v in raw.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
    if not present:
        return None, raw
    wsum = sum(weights[k] for k in present)
    comp = sum(weights[k] * v for k, v in present.items()) / wsum
    return comp, raw
