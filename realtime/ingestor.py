"""Intraday ingestor: feed -> indicators -> Redis snapshot/stream.

`refresh_intraday()` is one pass (called by the Celery beat task every minute during
market hours). `run_loop()` runs it continuously as a standalone process for dev:

    python -m realtime.ingestor            # poll every 60s, default watchlist
"""
from __future__ import annotations

import time

from stockpredict.config import DEFAULT_WATCHLIST
from .feed import get_intraday
from .indicators import compute_intraday_indicators
from . import store


def refresh_intraday(tickers: list[str] | None = None, interval: str = "5m",
                     days: int = 5, progress=None) -> dict:
    """One refresh pass. Returns {ticker: indicators} and publishes to Redis."""
    tickers = tickers or list(DEFAULT_WATCHLIST)
    if progress:
        progress(f"Fetching intraday bars for {len(tickers)} tickers…")
    bars = get_intraday(tickers, interval=interval, days=days)

    snapshot: dict[str, dict] = {}
    for t, df in bars.items():
        ind = compute_intraday_indicators(df)
        if ind:
            snapshot[t] = ind

    # Merge the latest news sentiment so it's visible and alertable.
    try:
        from news.service import load_latest as load_news
        news = load_news()
        for t, ind in snapshot.items():
            n = news.get(t)
            if n:
                ind["news_sentiment"] = n.get("sentiment")
                ind["news_count"] = n.get("count")
                ind["news_headline"] = n.get("top_headline")
    except Exception:
        pass

    persisted = store.publish(snapshot)
    if progress:
        progress(f"Computed {len(snapshot)} tickers "
                 f"({'published to Redis' if persisted else 'Redis unavailable'}).")

    # Evaluate alert rules against the fresh snapshot (best-effort).
    try:
        from alerts.service import evaluate_and_fire
        fired = evaluate_and_fire(snapshot)
        if fired and progress:
            progress(f"{len(fired)} alert(s) fired: "
                     + ", ".join(f"{a['ticker']}/{a['rule_name']}" for a in fired[:5]))
    except Exception as exc:
        if progress:
            progress(f"Alert evaluation skipped: {exc}")
    return snapshot


def run_loop(interval_seconds: int = 60):
    print("Intraday ingestor started. Ctrl-C to stop.")
    while True:
        try:
            refresh_intraday(progress=print)
        except Exception as exc:
            print("refresh error:", exc)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_loop()
