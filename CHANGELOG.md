# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); this project aims
to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Kronos evaluation harness** (`forecast/`) — vetted the [Kronos](https://github.com/shiyu-coder/Kronos)
  candlestick foundation model as a potential forecasting upgrade, behind a
  pluggable `Forecaster` interface (optional PyTorch dependency, never bundled).
- README **banner**, status **badges**, and a refreshed GitHub Pages landing page.
- This `CHANGELOG.md`.

### Findings
- **Kronos was evaluated and NOT integrated.** Across three independent backtests
  (daily recent, daily full-history, and intraday 5m — its native domain), zero-shot
  Kronos showed no usable edge (IC ≈ 0 to slightly negative, directional accuracy
  below coin-flip) and lost to both the transparent factor model and a momentum
  baseline. See [`KRONOS_EVAL.md`](KRONOS_EVAL.md). The backtest gate did its job.

## [1.0.0] — Packaging & CI

### Added
- **Standalone Windows executable** via PyInstaller (`stockpredict.spec`) — bundles
  Python + Tk + pandas/matplotlib/yfinance/SQLAlchemy; runs with no Python install.
- App **icon**, `--selftest`/`--version` CLI, global exception hook → rotating log
  + friendly dialog; per-user data dir at `%LOCALAPPDATA%\stockpredict`.
- **GitHub Actions** workflow: test → build exe → attach to a Release on `v*` tags.
- **Inno Setup** installer script; `PACKAGING.md`.

### Changed
- Desktop app runs fully in-process (SQLite + threaded aggregator); Redis/Celery
  became an optional "power mode" rather than a hard dependency.

### Fixed
- Alert desktop toasts now fail closed via a circuit breaker (winotify needs
  PowerShell, absent in some frozen environments) — alerts still log and beep.

## [0.1.0] — Initial application

### Added
- **Desktop GUI** (Tkinter) with seven tabs: Next Week / Month / Year return
  estimates, ⚡ Intraday technicals, 🔔 Alerts, 📰 News, 🔍 Scanners.
- **Multi-horizon factor model** — horizon-specific blends of momentum, reversal,
  quality/value, low-volatility; volatility-scaled ranges and confidence.
- **Celery + Redis** background pipeline (pre-market screen, intraday refresh,
  weekly backtest) with SQLite/Postgres storage.
- **Point-in-time backtesting harness** with walk-forward, costs, and Information
  Coefficient reporting + HTML tearsheets.
- **Intraday spine** (VWAP, RVOL, RSI, ATR, EMA stack, opening-range), **news +
  finance-lexicon sentiment**, **market-wide scanners**, and an **edge-triggered
  alert engine** with desktop toasts.
- UX: click-to-sort columns, ticker filter, CSV export, embedded intraday chart,
  price sparklines, market-session indicator, persisted preferences.

[Unreleased]: https://github.com/ibuilder/pyStocks/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ibuilder/pyStocks/releases/tag/v1.0.0
