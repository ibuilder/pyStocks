"""Dispatch fired alerts to the enabled notification channels.

Toasts are capped per cycle so a burst of alerts can't flood the desktop — the
first few show individually, the rest collapse into one summary toast. Cross-process
de-duplication is handled upstream by the alert engine's edge-trigger + cooldown
(shared state in Redis), so the same alert won't toast twice from the worker and
the app.
"""
from __future__ import annotations

import os

from .channels import DesktopToastNotifier, LogNotifier

MAX_TOASTS_PER_CYCLE = int(os.environ.get("STOCKPREDICT_MAX_TOASTS", "4"))
TOAST_ENABLED = os.environ.get("STOCKPREDICT_TOAST", "1") not in ("0", "false", "False")

import logging

_log = LogNotifier()
_toast = DesktopToastNotifier()
_logger = logging.getLogger("stockpredict.notify")

# Circuit breaker: some environments (e.g. a frozen build where winotify can't
# find PowerShell) fail every toast. After a few failures, disable toasts for the
# process so we don't block the alert thread or spam the log.
_toast_failures = 0
_toast_disabled = False
_TOAST_FAIL_LIMIT = 3


def _yahoo_link(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


def _try_toast(title: str, message: str, link: str | None = None) -> bool:
    global _toast_failures, _toast_disabled
    if _toast_disabled:
        return False
    ok = _toast.send(title, message, link)
    if ok:
        _toast_failures = 0
    else:
        _toast_failures += 1
        if _toast_failures >= _TOAST_FAIL_LIMIT:
            _toast_disabled = True
            _logger.warning("Desktop toasts unavailable in this environment — "
                            "disabling them for this session (alerts still log + beep).")
    return ok


def notify_alerts(fired: list[dict]) -> int:
    """Send notifications for freshly-fired alerts. Returns toasts shown."""
    if not fired:
        return 0

    # Log every alert; toast a capped subset.
    for a in fired:
        _log.send(f"{a['ticker']} — {a['rule_name']}", a.get("message", ""))

    shown = 0
    if TOAST_ENABLED and not _toast_disabled and _toast.available():
        for a in fired[:MAX_TOASTS_PER_CYCLE]:
            msg = a.get("message", "")
            if "—" in msg:
                msg = msg.split("—", 1)[1].strip()
            if _try_toast(f"🔔 {a['ticker']} — {a['rule_name']}", msg, _yahoo_link(a["ticker"])):
                shown += 1
        extra = len(fired) - MAX_TOASTS_PER_CYCLE
        if extra > 0 and not _toast_disabled:
            _try_toast("🔔 stockpredict", f"+{extra} more alert(s) fired — see the Alerts tab")
    return shown


def active_channels() -> list[str]:
    chans = [_log.name]
    if TOAST_ENABLED and _toast.available():
        chans.append(_toast.name)
    return chans
