"""Celery tasks (Phase 0).

Thin wrappers over `pipeline.run_screen()`. The task persists to the database and
returns a small JSON-serializable summary (never the DataFrames) so results fit in
the Redis result backend.
"""
from __future__ import annotations

from celery.utils.log import get_task_logger

from .celery_app import app
from .pipeline import run_screen

logger = get_task_logger(__name__)


@app.task(name="stockpredict.tasks.run_daily_screen", bind=True, max_retries=2, default_retry_delay=30)
def run_daily_screen(self):
    """Run the full screen and persist it. Retries on transient failures."""
    try:
        summary = run_screen(progress=lambda d, t, m: logger.info(m), persist=True)
    except Exception as exc:  # provider hiccup, network, etc.
        logger.warning("screen failed, retrying: %s", exc)
        raise self.retry(exc=exc)

    if summary.get("error"):
        logger.warning("screen produced no data: %s", summary["error"])
        raise self.retry(exc=RuntimeError(summary["error"]))

    # Drop the in-process DataFrames before returning to the result backend.
    summary.pop("results", None)
    logger.info("screen ok: run=%s priced=%s", (summary.get("run_id") or "")[:8], summary.get("priced"))
    return summary


@app.task(name="stockpredict.tasks.refresh_news", bind=True, max_retries=2, default_retry_delay=30)
def refresh_news(self):
    """Fetch + score per-ticker news sentiment, publish to Redis."""
    try:
        from news.service import refresh_news as _refresh
        agg = _refresh(progress=lambda m: logger.info(m))
        return {"tickers": len(agg)}
    except Exception as exc:
        logger.warning("news refresh failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(name="stockpredict.tasks.refresh_intraday", bind=True, max_retries=2, default_retry_delay=10)
def refresh_intraday(self):
    """Pull intraday bars, compute indicators, publish snapshot to Redis."""
    try:
        from realtime.ingestor import refresh_intraday as _refresh
        snap = _refresh(progress=lambda m: logger.info(m))
        return {"tickers": len(snap)}
    except Exception as exc:
        logger.warning("intraday refresh failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(name="stockpredict.tasks.run_weekly_backtest", bind=True, max_retries=1, default_retry_delay=120)
def run_weekly_backtest(self):
    """Re-validate the model: backtest every horizon, write a tearsheet, store metrics."""
    try:
        from backtest.datalake import load_history
        from backtest.engine import run_backtest
        from backtest.report import render
        from stockpredict.config import HORIZONS, DEFAULT_WATCHLIST
        from . import storage

        prices = load_history(list(DEFAULT_WATCHLIST))
        results, metrics = {}, {}
        for h in HORIZONS:
            res = run_backtest(prices, h)
            results[h] = res
            metrics[h] = res.metrics
        tearsheet = render(results)
        run_id = storage.save_backtest_metrics(metrics)
        logger.info("backtest ok: run=%s tearsheet=%s", run_id[:8], tearsheet)
        return {"run_id": run_id, "tearsheet": str(tearsheet),
                "ic": {h: round(m.get("ic_mean") or 0, 4) for h, m in metrics.items()}}
    except Exception as exc:
        logger.warning("backtest failed, retrying: %s", exc)
        raise self.retry(exc=exc)


# ----- convenience for local testing without a worker running -----
def run_once() -> dict:
    """Run the pipeline inline (no broker needed). For dev/smoke tests."""
    summary = run_screen(progress=lambda d, t, m: print("  ", m), persist=True)
    summary.pop("results", None)
    print("Summary:", summary)
    return summary


if __name__ == "__main__":
    run_once()
