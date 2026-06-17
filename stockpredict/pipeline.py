"""The screen pipeline, decoupled from any runner.

`run_screen()` is the single source of truth for "produce ranked estimates and
persist them." Both the Celery task (background/scheduled) and the desktop
aggregator (interactive) call it, so they can never drift apart.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import FUNDAMENTALS_CHUNK, FUNDAMENTALS_TTL_SECONDS, config
from .data import fetch_prices, get_fundamentals, get_universe
from .model import estimate_returns
from . import storage


def run_screen(progress=None, persist: bool = True) -> dict:
    """Fetch data, score every horizon, optionally persist, return a summary.

    `progress(done, total, msg)` is an optional callback for UI/log feedback.
    Returns a dict with the run_id, per-horizon top picks, and counts.
    """
    def report(msg):
        if progress:
            progress(0, 1, msg)

    universe = get_universe()
    report(f"Universe: {len(universe)} tickers")

    prices = fetch_prices(universe, progress=progress)
    if prices.empty:
        report("No price data available.")
        return {"run_id": None, "priced": 0, "picks": {}, "error": "no_price_data"}

    avail = list(prices.columns)
    funds = get_fundamentals(
        avail, ttl=FUNDAMENTALS_TTL_SECONDS, chunk=FUNDAMENTALS_CHUNK, progress=progress
    )

    report("Scoring & ranking…")
    results = estimate_returns(prices, funds)

    run_id = None
    if persist:
        run_id = storage.save_snapshot(results, universe_source=config.universe_source)
        report(f"Saved run {run_id[:8]}…")

    picks = {
        h: df.head(5)["ticker"].tolist() if (df is not None and not df.empty) else []
        for h, df in results.items()
    }
    return {
        "run_id": run_id,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "universe": len(universe),
        "priced": len(avail),
        "with_fundamentals": len(funds),
        "picks": picks,
        "results": results,  # in-process callers (the desktop app) use this directly
    }
