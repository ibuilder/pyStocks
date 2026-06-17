"""U.S. equity market session status (for the header indicator).

Robust on Windows: tries IANA tz via zoneinfo, falls back to a fixed Eastern
offset if tzdata isn't installed (DST handled approximately for the fallback only).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _eastern_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: approximate EDT (Mar–Nov) / EST otherwise.
        utc = datetime.now(timezone.utc)
        month = utc.month
        offset = -4 if 3 <= month <= 11 else -5
        return utc + timedelta(hours=offset)


def status() -> tuple[str, str]:
    """Return (label, color-hint) for the current session."""
    now = _eastern_now()
    if now.weekday() >= 5:
        return ("Market closed (weekend)", "muted")
    mins = now.hour * 60 + now.minute
    if 9 * 60 + 30 <= mins < 16 * 60:
        return ("Market open", "green")
    if 4 * 60 <= mins < 9 * 60 + 30:
        return ("Pre-market", "amber")
    if 16 * 60 <= mins < 20 * 60:
        return ("After-hours", "amber")
    return ("Market closed", "muted")
