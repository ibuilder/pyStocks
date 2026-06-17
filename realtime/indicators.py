"""Intraday technical indicators computed from an OHLCV bar frame.

Pure functions: a per-ticker OHLCV DataFrame (multiple sessions of intraday bars)
goes in, a flat dict of indicators for the latest session comes out. These are the
standard situational-awareness signals a day trader watches — VWAP, opening range,
relative volume, RSI, ATR, EMA stack, distance from session open/high/low.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, n: int = 14) -> float:
    d = close.diff().dropna()
    if len(d) < n + 1:
        return float("nan")
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1]) if not rsi.empty else float("nan")


def _atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    return float(atr.iloc[-1]) if not atr.empty and atr.notna().any() else float("nan")


def compute_intraday_indicators(df: pd.DataFrame, opening_range_min: int = 30) -> dict:
    """Return intraday indicators for the latest session in `df`.

    `df` is an intraday OHLCV frame (tz-aware index) spanning one or more sessions.
    """
    if df is None or df.empty:
        return {}
    df = df.sort_index()
    dates = pd.Index([ts.date() for ts in df.index])
    unique_days = list(dict.fromkeys(dates))  # ordered, de-duped

    # Use the latest session, but if it's too thin to be meaningful (pre-market /
    # just-opened), fall back to the most recent session with enough bars so RSI/
    # RVOL aren't distorted. During live trading the session quickly clears this.
    MIN_SESSION_BARS = 10
    last_day = unique_days[-1]
    for d in reversed(unique_days):
        if (dates == d).sum() >= MIN_SESSION_BARS:
            last_day = d
            break
    sess = df[dates == last_day]
    prior = df[dates < last_day]
    if sess.empty:
        return {}

    close = sess["Close"]
    last = float(close.iloc[-1])
    sess_open = float(sess["Open"].iloc[0])
    day_high = float(sess["High"].max())
    day_low = float(sess["Low"].min())

    # VWAP (session)
    typ = (sess["High"] + sess["Low"] + sess["Close"]) / 3.0
    vol = sess["Volume"].fillna(0)
    cum_v = vol.cumsum().iloc[-1]
    vwap = float((typ * vol).cumsum().iloc[-1] / cum_v) if cum_v > 0 else float("nan")

    # Opening range (first N minutes of the session)
    bar_min = _infer_bar_minutes(sess.index)
    n_or = max(1, int(round(opening_range_min / bar_min))) if bar_min else 1
    or_block = sess.iloc[:n_or]
    or_high = float(or_block["High"].max())
    or_low = float(or_block["Low"].min())

    # Relative volume: today's cumulative vs avg of prior sessions' total volume
    rvol = float("nan")
    if not prior.empty:
        prior_day_vol = prior.groupby([ts.date() for ts in prior.index])["Volume"].sum()
        avg_prior = prior_day_vol.mean()
        if avg_prior and avg_prior > 0:
            rvol = float(cum_v / avg_prior)

    ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])

    return {
        "last": round(last, 4),
        "session": str(last_day),
        "pct_from_open": _safe((last / sess_open - 1) * 100),
        "vwap": round(vwap, 4) if vwap == vwap else None,
        "pct_from_vwap": _safe((last / vwap - 1) * 100) if vwap == vwap else None,
        "day_high": round(day_high, 4),
        "day_low": round(day_low, 4),
        "or_high": round(or_high, 4),
        "or_low": round(or_low, 4),
        "above_or_high": bool(last > or_high),
        "below_or_low": bool(last < or_low),
        "rvol": round(rvol, 2) if rvol == rvol else None,
        "rsi14": _safe(_rsi(close)),
        "atr14": _safe(_atr(sess)),
        "ema9": round(ema9, 4),
        "ema20": round(ema20, 4),
        "above_ema9": bool(last > ema9),
        "ema_stack_bull": bool(ema9 > ema20),
        "bars": int(len(sess)),
    }


def _infer_bar_minutes(index) -> float:
    if len(index) < 2:
        return 5.0
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    med = deltas.median()
    return max(1.0, med.total_seconds() / 60.0)


def _safe(x):
    try:
        x = float(x)
        return None if x != x else round(x, 4)
    except (TypeError, ValueError):
        return None
