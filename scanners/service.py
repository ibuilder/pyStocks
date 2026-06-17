"""Run scans against the latest intraday snapshot — built-in + custom (DB)."""
from __future__ import annotations

from realtime import store as intraday_store
from .engine import run_scan
from .library import SCANS, SCANS_BY_NAME


def _all_scans_by_name() -> dict[str, dict]:
    merged = dict(SCANS_BY_NAME)
    try:
        from stockpredict import storage
        for s in storage.get_scans():     # custom scans can add to / override built-ins
            merged[s["name"]] = s
    except Exception:
        pass
    return merged


def run_named(scan_name: str, snapshot: dict | None = None, limit: int = 50) -> list[dict]:
    scan = _all_scans_by_name().get(scan_name)
    if not scan:
        return []
    snap = snapshot if snapshot is not None else intraday_store.load_latest()
    return run_scan(snap, scan)[:limit]


def available() -> list[str]:
    """Built-in scans first (library order), then any custom scans."""
    builtin = [s["name"] for s in SCANS]
    custom = [n for n in _all_scans_by_name() if n not in set(builtin)]
    return builtin + custom
