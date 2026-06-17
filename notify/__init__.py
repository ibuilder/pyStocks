"""Notification delivery (Phase 3, Increment 4).

Pluggable channels for getting fired alerts off the screen and to the trader.
Ships a Windows desktop-toast channel and an always-on log channel; email/Telegram
slot in behind the same `Notifier` interface later. Dispatch is best-effort and
never raises into the alert pipeline.
"""
