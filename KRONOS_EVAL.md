# Kronos evaluation — tested, not integrated

We evaluated [Kronos](https://github.com/shiyu-coder/Kronos) (AAAI 2026), an
open-source foundation model for OHLCV candlesticks, as a potential upgrade to the
factor-based return model. **Conclusion: zero-shot Kronos showed no usable edge on
US equities and was not integrated.** This document records the evidence so the
question isn't re-litigated.

## Why it was appealing
A real learned, probabilistic forecaster of price paths (MIT license) — on paper a
much stronger engine than transparent factor heuristics, with sampled predictive
intervals that could power confidence bands and chart overlays.

## How it was tested
A pluggable `KronosForecaster` (`forecast/kronos_forecaster.py`) wraps the vendored,
MIT-licensed model code (`forecast/kronos_pkg/`). Three independent, point-in-time
backtests ranked a diverse universe by predicted return and scored the ranking's
**Information Coefficient** (rank correlation vs realized forward return) and
**directional hit-rate** against fair baselines. Variant: Kronos-mini/​small,
zero-shot, CPU.

## Results

| Test | Kronos mean IC | Kronos dir-hit | Baseline mean IC |
|---|---|---|---|
| Daily, recent 6 mo (6 dates, small) | −0.28 | 37.5% | Factor **+0.36** |
| Daily, full 7 yr (20 dates, mini) | −0.05 | 45.4% | Factor **+0.12** |
| **Intraday 5m → next 30 min (24 sessions, mini)** — *native domain* | **−0.09** | **42.5%** | Momentum **+0.06** |

All three agree: zero-shot Kronos sits at **~0-to-negative IC** with **below-coin-flip
direction (42–45%)**, losing to both the factor model and a one-line momentum rule —
*including on its native intraday short-horizon domain*.

## Practical blockers (even if skill existed)
- **~37 s per forecast** for Kronos-small on CPU — impractical for a real universe
  without a GPU.
- **~2 GB** of PyTorch + weights — would break the lean standalone `.exe`.

## Fair caveats
- Tested **zero-shot** (untuned); Kronos ships a fine-tuning pipeline. **Mini** is
  the weakest variant. A fine-tuned larger variant on a GPU with a proper large
  backtest *might* differ — but that is a research project, not a plug-in, with no
  guaranteed payoff.

## What we kept
- The **model-agnostic evaluation harness** (`forecast/kronos_eval.py`,
  `kronos_intraday_eval.py`) — reusable to vet the next forecaster with the same IC
  gate (`--summarize` reads the checkpoint CSV).
- The vendored Kronos model code + wrapper (small, MIT), gated as optional.

## How to reproduce
```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers huggingface_hub safetensors einops
$env:KRONOS_VARIANT="mini"; $env:KRONOS_MAX_CONTEXT="512"
python -m forecast.kronos_eval --tickers 12 --dates 20            # daily
python -m forecast.kronos_intraday_eval --tickers 10 --horizon 6  # intraday 5m
```
The full Kronos repo clone (`vendor_kronos/`) and downloaded weights are not tracked.
