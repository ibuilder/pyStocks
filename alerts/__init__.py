"""Alert engine (Phase 3, Increment 1).

User-defined rules over the live intraday indicators, evaluated by Celery after
each intraday refresh. Rules are edge-triggered (fire on the transition into the
matching state) with a per-rule cooldown so a persistent condition doesn't spam.
The core `evaluate()` is pure and fully unit-tested; the service layer wires it to
storage + Redis-backed state.
"""
