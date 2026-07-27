"""Thin wrapper around the vendored Kronos model — a pluggable Forecaster.

Lazy-loads the tokenizer + model once (CPU by default), then forecasts a future
OHLCV path from a trailing window of candles. Mirrors the shape of the rest of the
app's provider interfaces so it can be swapped/mocked.
"""
from __future__ import annotations

import os

import pandas as pd

# Model/tokenizer pairings (see the Kronos model card). Override via env:
#   KRONOS_MODEL / KRONOS_TOKENIZER / KRONOS_MAX_CONTEXT
VARIANTS = {
    "mini":  ("NeoQuasar/Kronos-mini",  "NeoQuasar/Kronos-Tokenizer-2k",   2048),
    "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512),
    "base":  ("NeoQuasar/Kronos-base",  "NeoQuasar/Kronos-Tokenizer-base", 512),
}
_ENV_VARIANT = os.environ.get("KRONOS_VARIANT", "small")
DEFAULT_MODEL, DEFAULT_TOKENIZER, DEFAULT_CTX = VARIANTS.get(_ENV_VARIANT, VARIANTS["small"])
DEFAULT_MODEL = os.environ.get("KRONOS_MODEL", DEFAULT_MODEL)
DEFAULT_TOKENIZER = os.environ.get("KRONOS_TOKENIZER", DEFAULT_TOKENIZER)
DEFAULT_CTX = int(os.environ.get("KRONOS_MAX_CONTEXT", DEFAULT_CTX))


class KronosForecaster:
    def __init__(self, model_id: str = DEFAULT_MODEL, tokenizer_id: str = DEFAULT_TOKENIZER,
                 max_context: int = DEFAULT_CTX, device: str = "cpu"):
        self.model_id = model_id
        self.tokenizer_id = tokenizer_id
        self.max_context = max_context
        self.device = device
        self._predictor = None

    def _ensure_loaded(self):
        if self._predictor is not None:
            return
        from .kronos_pkg import Kronos, KronosTokenizer, KronosPredictor
        tok = KronosTokenizer.from_pretrained(self.tokenizer_id)
        model = Kronos.from_pretrained(self.model_id)
        model.eval()
        self._predictor = KronosPredictor(model, tok, device=self.device,
                                          max_context=self.max_context)

    def forecast(self, ohlcv: pd.DataFrame, horizon: int, sample_count: int = 1,
                 T: float = 1.0, top_p: float = 0.9, freq: str = "B") -> pd.DataFrame:
        """Return a predicted OHLCV DataFrame `horizon` steps ahead.

        `ohlcv` must have a DatetimeIndex and columns open/high/low/close (+volume).
        Context is truncated to the model's max_context automatically.
        """
        self._ensure_loaded()
        cols = ["open", "high", "low", "close"]
        if "volume" in ohlcv.columns:
            cols = cols + ["volume"]
        # Drop incomplete/pending rows (yfinance can append a trailing NaN bar).
        df = ohlcv[cols].dropna(how="any").tail(self.max_context).copy()
        if len(df) < 30:
            return pd.DataFrame()
        x_ts = pd.Series(df.index)
        future_idx = pd.date_range(df.index[-1], periods=horizon + 1, freq=freq)[1:]
        y_ts = pd.Series(future_idx)
        return self._predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts,
                                       pred_len=horizon, T=T, top_p=top_p,
                                       sample_count=sample_count, verbose=False)

    def expected_return(self, ohlcv: pd.DataFrame, horizon: int, sample_count: int = 1) -> float:
        """Predicted cumulative return over the horizon (final close vs last close)."""
        clean_close = ohlcv["close"].dropna()
        if clean_close.empty:
            return float("nan")
        last_close = float(clean_close.iloc[-1])
        pred = self.forecast(ohlcv, horizon, sample_count=sample_count)
        if pred is None or pred.empty:
            return float("nan")
        return float(pred["close"].iloc[-1]) / last_close - 1.0
