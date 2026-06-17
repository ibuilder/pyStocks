"""Backtesting & validation harness (Phase 1).

Validates the ranking model out-of-sample BEFORE any signal is trusted as
"actionable". Backtests the **price-based** factors point-in-time (no lookahead);
fundamentals are intentionally excluded because yfinance only exposes a *current*
snapshot, not point-in-time history — backtesting them would leak the future. See
README / ROADMAP for the point-in-time-fundamentals upgrade.
"""
