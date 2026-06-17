"""Celery application + background schedule (Phase 0).

Run the pieces (Redis must be reachable at STOCKPREDICT_REDIS_URL):

    docker compose up -d redis           # or any Redis
    celery -A stockpredict.celery_app worker --loglevel=info --pool=solo
    celery -A stockpredict.celery_app beat   --loglevel=info

`--pool=solo` is recommended on Windows. The Beat schedule runs a pre-market
daily screen and a light intraday refresh during U.S. market hours; both call the
same `pipeline.run_screen()` the desktop app uses.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from .config import REDIS_URL

app = Celery("stockpredict", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/New_York",      # schedule in market time
    enable_utc=True,
    task_acks_late=True,              # re-queue if a worker dies mid-task
    worker_prefetch_multiplier=1,     # fair dispatch; data tasks are I/O heavy
    task_default_rate_limit="60/m",   # be polite to data providers
    result_expires=3600,
)

app.conf.beat_schedule = {
    # Full pre-market screen at 7:30 AM ET on weekdays (before the 9:30 open).
    "premarket-screen": {
        "task": "stockpredict.tasks.run_daily_screen",
        "schedule": crontab(hour=7, minute=30, day_of_week="mon-fri"),
    },
    # Light intraday refresh every 30 min during the cash session.
    "intraday-refresh": {
        "task": "stockpredict.tasks.run_daily_screen",
        "schedule": crontab(minute="*/30", hour="9-16", day_of_week="mon-fri"),
    },
    # News + sentiment every 10 min through extended + cash hours.
    "news-sentiment": {
        "task": "stockpredict.tasks.refresh_news",
        "schedule": crontab(minute="*/10", hour="7-20", day_of_week="mon-fri"),
    },
    # Intraday research refresh every minute during the cash session.
    "intraday-indicators": {
        "task": "stockpredict.tasks.refresh_intraday",
        "schedule": crontab(minute="*", hour="9-16", day_of_week="mon-fri"),
    },
    # Weekly model re-validation: backtest every horizon, store metrics + tearsheet.
    "weekly-backtest": {
        "task": "stockpredict.tasks.run_weekly_backtest",
        "schedule": crontab(hour=6, minute=0, day_of_week="sun"),
    },
}

from . import tasks  # noqa: E402,F401  (register tasks)
