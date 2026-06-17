"""Continuous data aggregation on a background thread.

The aggregator owns the refresh loop: pull prices, refresh a rotating chunk of
fundamentals, recompute the model, and hand results back via a callback. The GUI
subscribes to it and never blocks on the network itself.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from .config import config
from .pipeline import run_screen


class DataAggregator:
    def __init__(self, on_update=None, on_status=None):
        """on_update(results, meta) and on_status(msg) are called from this thread."""
        self.on_update = on_update
        self.on_status = on_status
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_results = None
        self.last_meta = {}
        self.lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aggregator", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh_now(self):
        """Trigger an immediate refresh without waiting for the interval."""
        self._wake.set()

    # -- internals -----------------------------------------------------------
    def _status(self, msg):
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                self._refresh_once()
            except Exception as exc:  # never let the loop die
                self._status(f"Refresh error: {exc}")
            # Wait for the interval OR an explicit wake/stop.
            self._wake.clear()
            self._wake.wait(timeout=max(30, config.refresh_seconds))

    def _refresh_once(self):
        started = time.time()
        # One shared code path with the Celery task; persists the snapshot too.
        summary = run_screen(progress=lambda d, t, m: self._status(m), persist=True)

        if summary.get("error") or not summary.get("results"):
            self._status("No price data available (network?). Will retry.")
            return

        results = summary["results"]
        meta = {
            "updated_at": datetime.now(),
            "universe": summary.get("universe", 0),
            "priced": summary.get("priced", 0),
            "with_fundamentals": summary.get("with_fundamentals", 0),
            "run_id": summary.get("run_id"),
            "elapsed": round(time.time() - started, 1),
        }
        with self.lock:
            self.last_results = results
            self.last_meta = meta
        if self.on_update:
            try:
                self.on_update(results, meta)
            except Exception:
                pass
        self._status(
            f"Updated {meta['updated_at']:%H:%M:%S} — "
            f"{meta['priced']} priced, {meta['with_fundamentals']} w/ fundamentals "
            f"({meta['elapsed']}s)"
        )
