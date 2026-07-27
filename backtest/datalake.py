"""Historical price data lake for backtesting.

Downloads long daily history once and caches it as Parquet, keyed by the universe
+ period so repeated backtests are instant and offline. This is the seed of the
Phase 2+ data lake.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pandas as pd

from stockpredict.config import CACHE_DIR

LAKE_DIR = Path(CACHE_DIR) / "lake"
LAKE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PERIOD = "10y"
TTL_SECONDS = 24 * 60 * 60  # refresh history at most daily


def _key(tickers: list[str], period: str) -> str:
    h = hashlib.sha1((period + "|" + ",".join(sorted(tickers))).encode()).hexdigest()[:16]
    return f"prices_{period}_{len(tickers)}_{h}.parquet"


def load_history(tickers: list[str], period: str = DEFAULT_PERIOD, force: bool = False) -> pd.DataFrame:
    """Return a daily adjusted-close DataFrame (index=dates, cols=tickers).

    Cached to Parquet with a daily TTL. Set force=True to re-download.
    """
    path = LAKE_DIR / _key(tickers, period)
    if not force and path.exists() and (time.time() - path.stat().st_mtime) < TTL_SECONDS:
        try:
            return pd.read_parquet(path)
        except Exception:
            pass

    import yfinance as yf

    raw = yf.download(
        tickers=tickers, period=period, interval="1d",
        auto_adjust=True, group_by="column", threads=True, progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.levels[0] else raw.xs("Close", axis=1, level=0)
    else:
        col = "Close" if "Close" in raw.columns else raw.columns[-1]
        close = raw[[col]].rename(columns={col: tickers[0]})

    close = close.dropna(how="all").dropna(axis=1, how="all").sort_index()
    if not close.empty:
        try:
            close.to_parquet(path)
        except Exception:
            pass
    return close


def load_ohlcv(tickers: list[str], period: str = DEFAULT_PERIOD, force: bool = False) -> dict[str, pd.DataFrame]:
    """Return {ticker: OHLCV DataFrame} (open/high/low/close/volume), Parquet-cached.

    Needed by the Kronos forecaster, which consumes full candles, not just close.
    """
    key = _key(tickers, period).replace("prices_", "ohlcv_").replace(".parquet", "")
    out: dict[str, pd.DataFrame] = {}
    combined = LAKE_DIR / f"{key}.parquet"
    if not force and combined.exists() and (time.time() - combined.stat().st_mtime) < TTL_SECONDS:
        try:
            flat = pd.read_parquet(combined)
            for t in flat.columns.get_level_values(0).unique():
                out[t] = flat[t].dropna(how="all")
            if out:
                return out
        except Exception:
            pass

    import yfinance as yf
    raw = yf.download(tickers=tickers, period=period, interval="1d", auto_adjust=True,
                      group_by="ticker", threads=True, progress=False)
    if raw is None or raw.empty:
        return out
    fields = ["Open", "High", "Low", "Close", "Volume"]
    for t in tickers:
        try:
            sub = raw[t][fields].dropna(how="all") if isinstance(raw.columns, pd.MultiIndex) else raw[fields]
        except Exception:
            continue
        sub = sub.rename(columns=str.lower).sort_index()
        if not sub.empty:
            out[t] = sub
    if out:
        try:
            pd.concat(out, axis=1).to_parquet(combined)
        except Exception:
            pass
    return out
