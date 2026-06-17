"""Market-data layer: price history + fundamentals via yfinance, with caching.

yfinance is an unofficial Yahoo feed — great for a zero-setup prototype, not for
production. Everything degrades gracefully: one bad ticker never sinks a refresh.
"""
from __future__ import annotations

import pickle
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import CACHE_DIR, HISTORY_DAYS, config


@dataclass
class Fundamentals:
    ticker: str
    name: str | None = None
    price: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    eps_growth: float | None = None      # YoY, as fraction (0.15 = 15%)
    profit_margin: float | None = None
    debt_to_equity: float | None = None
    market_cap: float | None = None
    sector: str | None = None
    beta: float | None = None
    fetched_at: float = 0.0


def _f(x) -> float | None:
    try:
        if x in (None, "None", "", "-"):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- universe ---
def get_universe() -> list[str]:
    if config.universe_source == "sp500":
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            syms = [s.replace(".", "-") for s in tables[0]["Symbol"].tolist()]
            if syms:
                return syms
        except Exception:
            pass  # fall back to the watchlist if the scrape fails
    return list(config.watchlist)


# ------------------------------------------------------------ price history ---
_PRICE_CACHE = CACHE_DIR / "prices.pkl"


def fetch_prices(tickers: list[str], progress=None) -> pd.DataFrame:
    """Return a DataFrame of adjusted close prices, columns=tickers, index=dates.

    Downloads in one bulk call (fast), then drops empty columns. `progress` is an
    optional callable(done, total, message) for UI feedback.
    """
    import yfinance as yf

    if progress:
        progress(0, 1, f"Downloading {len(tickers)} price histories…")

    period = f"{HISTORY_DAYS}d"
    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            auto_adjust=True,
            group_by="column",
            threads=True,
            progress=False,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        if progress:
            progress(1, 1, f"Price download failed: {exc}")
        return _load_cached_prices()

    # Normalize to a plain close-price frame regardless of single/multi ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.levels[0] else raw.xs("Close", axis=1, level=0)
    else:
        # Single ticker -> flat columns; build a one-column frame.
        col = "Close" if "Close" in raw.columns else raw.columns[-1]
        close = raw[[col]].rename(columns={col: tickers[0]})

    close = close.dropna(how="all").dropna(axis=1, how="all")
    if not close.empty:
        try:
            close.to_pickle(_PRICE_CACHE)
        except Exception:
            pass
    if progress:
        progress(1, 1, f"Got prices for {close.shape[1]} tickers.")
    return close


def _load_cached_prices() -> pd.DataFrame:
    if _PRICE_CACHE.exists():
        try:
            return pd.read_pickle(_PRICE_CACHE)
        except Exception:
            pass
    return pd.DataFrame()


# ------------------------------------------------------------- fundamentals ---
_FUND_CACHE = CACHE_DIR / "fundamentals.pkl"


def _load_fund_cache() -> dict[str, Fundamentals]:
    if _FUND_CACHE.exists():
        try:
            with open(_FUND_CACHE, "rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass
    return {}


def _save_fund_cache(cache: dict[str, Fundamentals]) -> None:
    try:
        with open(_FUND_CACHE, "wb") as fh:
            pickle.dump(cache, fh)
    except Exception:
        pass


def fetch_fundamentals_one(ticker: str) -> Fundamentals | None:
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return None
    if not info:
        return None
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    de = _f(info.get("debtToEquity"))
    return Fundamentals(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName"),
        price=_f(price),
        pe=_f(info.get("trailingPE")),
        forward_pe=_f(info.get("forwardPE")),
        peg=_f(info.get("trailingPegRatio") or info.get("pegRatio")),
        eps_growth=_f(info.get("earningsGrowth")),
        profit_margin=_f(info.get("profitMargins")),
        debt_to_equity=de,
        market_cap=_f(info.get("marketCap")),
        sector=info.get("sector"),
        beta=_f(info.get("beta")),
        fetched_at=time.time(),
    )


def get_fundamentals(tickers: list[str], ttl: float, chunk: int, progress=None) -> dict[str, Fundamentals]:
    """Return fundamentals for `tickers`, refreshing only stale entries.

    Only up to `chunk` stale tickers are refreshed per call so a big universe is
    updated gradually across refresh cycles instead of in one slow burst.
    """
    cache = _load_fund_cache()
    now = time.time()
    stale = [t for t in tickers if t not in cache or (now - cache[t].fetched_at) > ttl]
    to_fetch = stale[:chunk]

    for i, t in enumerate(to_fetch, 1):
        if progress:
            progress(i, len(to_fetch), f"Fundamentals {t} ({i}/{len(to_fetch)})")
        f = fetch_fundamentals_one(t)
        if f:
            cache[t] = f
    if to_fetch:
        _save_fund_cache(cache)
    return {t: cache[t] for t in tickers if t in cache}
