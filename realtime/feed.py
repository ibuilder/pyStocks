"""Pluggable intraday bar feed.

`get_intraday(tickers, interval, days)` returns {ticker: OHLCV DataFrame} with a
timezone-aware index. yfinance is the prototype; add a provider by implementing the
same signature and selecting it via STOCKPREDICT_INTRADAY_PROVIDER.

Note: yfinance is polled, not streamed, and is delayed — fine for a prototype.
Alpaca/Polygon provide true WebSocket streaming (Phase 2 upgrade).
"""
from __future__ import annotations

import os

import pandas as pd

PROVIDER = os.environ.get("STOCKPREDICT_INTRADAY_PROVIDER", "yfinance")


def _yfinance_intraday(tickers: list[str], interval: str, days: int) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    period = f"{days}d"
    raw = yf.download(
        tickers=tickers, period=period, interval=interval,
        auto_adjust=True, group_by="ticker", threads=True, progress=False, prepost=False,
    )
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out

    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            if t in raw.columns.get_level_values(0):
                sub = raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
                if not sub.empty:
                    out[t] = sub
    else:  # single ticker -> flat columns
        sub = raw[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        if not sub.empty:
            out[tickers[0]] = sub
    return out


def get_intraday(tickers: list[str], interval: str = "5m", days: int = 5) -> dict[str, pd.DataFrame]:
    if PROVIDER == "yfinance":
        return _yfinance_intraday(tickers, interval, days)
    raise ValueError(f"Unknown intraday provider: {PROVIDER}")
