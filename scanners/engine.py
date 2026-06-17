"""Pure scan execution: filter the snapshot, then rank.

A scan is {name, filters: [{field, op, value}], sort, desc, min_bars}. Filtering
reuses the alert engine's `_check` so operator semantics never diverge between
alerts and scanners.
"""
from __future__ import annotations

from alerts.engine import _check


def run_scan(snapshot: dict[str, dict], scan: dict) -> list[dict]:
    """Return matching rows [{ticker, **indicators}] sorted by the scan's key."""
    filters = scan.get("filters", [])
    sort_field = scan.get("sort")
    desc = scan.get("desc", True)
    min_bars = scan.get("min_bars", 0)

    rows = []
    for ticker, ind in (snapshot or {}).items():
        if not ind or ind.get("bars", 0) < min_bars:
            continue
        if all(_check(f, ind, {}) for f in filters):
            row = dict(ind)
            row["ticker"] = ticker
            rows.append(row)

    def key(r):
        v = r.get(sort_field)
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (-1, 0.0)  # missing sort value sinks to the bottom

    if sort_field:
        rows.sort(key=key, reverse=desc)
    return rows
