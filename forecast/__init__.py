"""Optional ML forecasting layer (Kronos).

Kronos (https://github.com/shiyu-coder/Kronos, MIT) is a foundation model for OHLCV
candlesticks. It is a HEAVY, OPTIONAL dependency (PyTorch + HF weights) — never
imported by the core app or bundled into the exe. Use it from source to research
whether a learned forecaster beats the transparent factor model, validated the same
way (walk-forward, IC). Vendored model code lives in `forecast/kronos_pkg/` (MIT).
"""
