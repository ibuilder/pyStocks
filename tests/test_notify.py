"""Notification dispatch tests (fake channels — no real toasts)."""
from __future__ import annotations

import notify.dispatch as dispatch


class FakeToast:
    name = "toast"

    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def send(self, title, message, link=None):
        self.calls.append((title, message, link))
        return True


def _alerts(n):
    return [{"rule_id": 1, "rule_name": "R", "ticker": f"T{i}",
             "message": f"T{i}: R — rsi14=20"} for i in range(n)]


def test_caps_toasts_and_summarizes(monkeypatch):
    fake = FakeToast()
    monkeypatch.setattr(dispatch, "_toast", fake)
    monkeypatch.setattr(dispatch, "TOAST_ENABLED", True)
    monkeypatch.setattr(dispatch, "MAX_TOASTS_PER_CYCLE", 3)

    shown = dispatch.notify_alerts(_alerts(10))
    assert shown == 3                     # capped
    # 3 individual + 1 summary toast
    assert len(fake.calls) == 4
    assert "+7 more" in fake.calls[-1][1]


def test_no_alerts_no_calls(monkeypatch):
    fake = FakeToast()
    monkeypatch.setattr(dispatch, "_toast", fake)
    assert dispatch.notify_alerts([]) == 0
    assert fake.calls == []


def test_link_is_yahoo(monkeypatch):
    fake = FakeToast()
    monkeypatch.setattr(dispatch, "_toast", fake)
    monkeypatch.setattr(dispatch, "TOAST_ENABLED", True)
    monkeypatch.setattr(dispatch, "MAX_TOASTS_PER_CYCLE", 5)
    dispatch.notify_alerts(_alerts(1))
    assert fake.calls[0][2] == "https://finance.yahoo.com/quote/T0"
