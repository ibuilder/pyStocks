"""Alert service: evaluate the latest intraday snapshot against stored rules.

Loads rules (seeding defaults on first run), loads prior state, runs the pure
engine, persists newly-fired alerts, and saves the next state. Returns the fired
alerts so callers (Celery task, ingestor) can log/notify.
"""
from __future__ import annotations

import time

from stockpredict import storage
from . import state
from .engine import evaluate


def evaluate_and_fire(snapshot: dict[str, dict]) -> list[dict]:
    if not snapshot:
        return []
    storage.seed_default_rules()
    rules = storage.get_rules(enabled_only=True)
    if not rules:
        return []

    prev = state.load_all()
    fired, new_state = evaluate(snapshot, rules, prev, now=time.time())
    state.save_all(new_state)

    for a in fired:
        storage.save_fired(a["rule_id"], a["rule_name"], a["ticker"], a["message"])

    # Deliver to notification channels (toast/log) — best effort.
    if fired:
        try:
            from notify.dispatch import notify_alerts
            notify_alerts(fired)
        except Exception:
            pass
    return fired
