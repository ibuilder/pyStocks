"""Notification channels. Add a channel by subclassing Notifier."""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger("stockpredict.notify")

APP_ID = "stockpredict"


class Notifier:
    name = "base"

    def available(self) -> bool:
        return False

    def send(self, title: str, message: str, link: str | None = None) -> bool:
        raise NotImplementedError


class LogNotifier(Notifier):
    """Always-available fallback — writes alerts to the log."""
    name = "log"

    def available(self) -> bool:
        return True

    def send(self, title: str, message: str, link: str | None = None) -> bool:
        logger.info("ALERT %s — %s", title, message)
        return True


class DesktopToastNotifier(Notifier):
    """Windows toast via winotify. No-ops gracefully off Windows / if missing."""
    name = "toast"

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winotify  # noqa: F401
            return True
        except Exception:
            return False

    def send(self, title: str, message: str, link: str | None = None) -> bool:
        try:
            from winotify import Notification
            t = Notification(app_id=APP_ID, title=title, msg=message)
            if link:
                t.add_actions(label="Open chart", launch=link)
            t.show()
            return True
        except Exception as exc:
            logger.warning("toast failed: %s", exc)
            return False
