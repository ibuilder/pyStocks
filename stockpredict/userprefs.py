"""Tiny JSON-backed user-preferences store (window geometry, selections).

Persists UI choices across restarts. Deliberately dependency-free and best-effort:
a corrupt or missing file just yields defaults.
"""
from __future__ import annotations

import json

from .config import CACHE_DIR

_PREFS_PATH = CACHE_DIR / "prefs.json"


def load() -> dict:
    try:
        return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(prefs: dict) -> None:
    try:
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass


def update(**kwargs) -> dict:
    prefs = load()
    prefs.update({k: v for k, v in kwargs.items() if v is not None})
    save(prefs)
    return prefs
