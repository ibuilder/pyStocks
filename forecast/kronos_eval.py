"""Head-to-head: Kronos vs. the transparent factor model (month horizon).

Apples-to-apples, point-in-time, non-overlapping. For each rebalance date we rank
the universe by (a) Kronos's predicted horizon return and (b) the factor model's
month composite, then correlate each ranking with the REALIZED forward return
(Information Coefficient). Higher mean IC / IC t-stat wins. Also reports directional
hit-rate for Kronos.

CPU inference is slow, so defaults are modest — this is a signal check, not a
definitive study. Scale --tickers / --dates up on a GPU.

    python -m forecast.kronos_eval --tickers 10 --dates 12 --horizon 21
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from backtest.datalake import load_ohlcv
from backtest.engine import _raw_factor_frame, _composite, _price_weights, _spearman
from stockpredict.config import DEFAULT_WATCHLIST


def _factor_scores(close_df: pd.DataFrame, upto_iloc: int, lookback: int = 300) -> pd.Series:
    window = close_df.iloc[max(0, upto_iloc - lookback): upto_iloc + 1]
    pf = _raw_factor_frame(window)
    if pf.empty:
        return pd.Series(dtype=float)
    return _composite(pf, _price_weights("month"))


_OUT = None


def _emit(msg):
    print(msg, flush=True)
    if _OUT:
        _OUT.write(msg + "\n")
        _OUT.flush()
        import os
        os.fsync(_OUT.fileno())


CKPT_HEADER = "iloc,date,ic_k,ic_f,hit,n\n"


def _load_ckpt(path):
    done = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 6:
                    done[int(parts[0])] = parts
    return done


def run_eval(n_tickers=12, n_dates=20, horizon=21, warmup=300, sample_count=1,
             out_path="kronos_eval_out.txt", ckpt="kronos_ckpt.csv"):
    global _OUT
    _OUT = open(out_path, "w", encoding="utf-8")
    # Spread across the watchlist (grouped by sector) for a diverse cross-section.
    step = max(1, len(DEFAULT_WATCHLIST) // n_tickers)
    tickers = list(DEFAULT_WATCHLIST)[::step][:n_tickers]
    _emit(f"Loading OHLCV for {len(tickers)} tickers…")
    ohlcv = load_ohlcv(tickers, period="8y")
    tickers = [t for t in tickers if t in ohlcv and len(ohlcv[t]) > warmup + horizon + 20]
    close_df = pd.DataFrame({t: ohlcv[t]["close"] for t in tickers}).dropna(how="all").sort_index()
    n = len(close_df)
    _emit(f"  {len(tickers)} usable tickers x {n} days")

    # Rebalance points SPREAD ACROSS THE FULL HISTORY (removes recent-regime bias).
    all_pts = list(range(warmup, n - horizon, horizon))
    if len(all_pts) > n_dates:
        idx = np.linspace(0, len(all_pts) - 1, n_dates).round().astype(int)
        pts = sorted({all_pts[j] for j in idx})
    else:
        pts = all_pts
    _emit(f"  {len(pts)} rebalance dates spread over "
          f"{close_df.index[pts[0]]:%Y-%m} … {close_df.index[pts[-1]]:%Y-%m}\n")

    # Resume from checkpoint — skip dates already computed in a prior run.
    done = _load_ckpt(ckpt)
    if not os.path.exists(ckpt):
        with open(ckpt, "w", encoding="utf-8") as fh:
            fh.write(CKPT_HEADER)
    _emit(f"  checkpoint: {len(done)} dates already done, {len([i for i in pts if i not in done])} to do")

    from forecast.kronos_forecaster import KronosForecaster
    kf = KronosForecaster()
    _emit(f"Kronos variant={os.environ.get('KRONOS_VARIANT','small')} "
          f"ctx={kf.max_context} samples={sample_count}\n")

    for di, i in enumerate([p for p in pts if p not in done], 1):
        date = close_df.index[i]
        realized = (close_df.iloc[i + horizon] / close_df.iloc[i] - 1.0)
        fscore = _factor_scores(close_df, i)
        kpred = {}
        for t in tickers:
            hist = ohlcv[t].loc[:date]
            if len(hist) < 60 or np.isnan(realized.get(t, np.nan)):
                continue
            try:
                kpred[t] = kf.expected_return(hist, horizon, sample_count=sample_count)
            except Exception as exc:
                _emit(f"    ! {t} kronos failed: {exc}")
        kpred = pd.Series(kpred).dropna()
        common = kpred.index.intersection(realized.dropna().index).intersection(fscore.dropna().index)
        if len(common) < 4:
            _emit(f"  {date:%Y-%m-%d}  too few tickers, skip")
            continue
        r = realized.loc[common]
        ick = _spearman(kpred.loc[common], r)
        icf = _spearman(fscore.loc[common], r)
        hit = float((np.sign(kpred.loc[common]) == np.sign(r)).mean())
        with open(ckpt, "a", encoding="utf-8") as fh:
            fh.write(f"{i},{date:%Y-%m-%d},{ick:.4f},{icf:.4f},{hit:.4f},{len(common)}\n")
            fh.flush(); os.fsync(fh.fileno())
        _emit(f"  {date:%Y-%m-%d}  Kronos IC={ick:+.3f}  Factor IC={icf:+.3f}  "
              f"dir-hit={hit*100:.0f}%  (n={len(common)})")

    summarize(ckpt)


def summarize(ckpt="kronos_ckpt.csv"):
    rows = list(_load_ckpt(ckpt).values())
    ic_k = np.array([float(r[2]) for r in rows])
    ic_f = np.array([float(r[3]) for r in rows])
    hits = np.array([float(r[4]) for r in rows])
    _emit("\n================  HEAD-TO-HEAD (month horizon)  ================")
    _summ("Kronos    ", ic_k)
    _summ("Factor    ", ic_f)
    if len(hits):
        _emit(f"Kronos directional hit-rate: {hits.mean()*100:.1f}%  (50% = coin flip)")
    _emit(f"Rebalance dates: {len(ic_k)}")


def _summ(name, arr):
    arr = np.asarray([x for x in arr if x == x])
    if not len(arr):
        _emit(f"{name} no data")
        return
    t = arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 and arr.std(ddof=1) else float("nan")
    _emit(f"{name} mean IC={arr.mean():+.3f}  IC t-stat={t:+.2f}  (n={len(arr)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=12)
    ap.add_argument("--dates", type=int, default=20)
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--out", default="kronos_eval_out.txt")
    ap.add_argument("--ckpt", default="kronos_ckpt.csv")
    ap.add_argument("--summarize", action="store_true", help="print summary from the checkpoint and exit")
    a = ap.parse_args()
    if a.summarize:
        _OUT = open(a.out, "w", encoding="utf-8")
        summarize(a.ckpt)
    else:
        run_eval(n_tickers=a.tickers, n_dates=a.dates, horizon=a.horizon,
                 sample_count=a.samples, out_path=a.out, ckpt=a.ckpt)
