"""Real-time scanners (Phase 3, Increment 3).

A scanner is a live filtered + ranked view over the whole intraday snapshot —
"show me everything matching X right now". It reuses the alert engine's condition
operators (DRY) for filtering, then sorts by a chosen field. Read-only and computed
on demand from the latest Redis snapshot; no separate Celery task needed.
"""
