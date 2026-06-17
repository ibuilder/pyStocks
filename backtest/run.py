"""One-command backtest CLI.

    python -m backtest.run                      # all horizons, default universe
    python -m backtest.run --horizon month      # one horizon
    python -m backtest.run --top-n 15 --cost-bps 8 --open
    python -m backtest.run --sp500              # backtest the S&P 500 universe

Produces an HTML tearsheet and prints a summary. Use --walk-forward to also run
the train/test re-fit comparison of current vs evidence-based weights.
"""
from __future__ import annotations

import argparse
import webbrowser

from stockpredict.config import HORIZONS, DEFAULT_WATCHLIST
from stockpredict.data import get_universe
from .datalake import load_history, DEFAULT_PERIOD
from .engine import run_backtest, walk_forward
from .report import render


def main(argv=None):
    ap = argparse.ArgumentParser(description="stockpredict backtest")
    ap.add_argument("--horizon", choices=list(HORIZONS) + ["all"], default="all")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument("--period", default=DEFAULT_PERIOD, help="history window, e.g. 10y, 15y, max")
    ap.add_argument("--sp500", action="store_true", help="use the S&P 500 universe")
    ap.add_argument("--walk-forward", action="store_true", help="add train/test weight re-fit")
    ap.add_argument("--open", action="store_true", help="open the tearsheet in a browser")
    args = ap.parse_args(argv)

    if args.sp500:
        from stockpredict.config import config
        config.universe_source = "sp500"
        tickers = get_universe()
    else:
        tickers = list(DEFAULT_WATCHLIST)

    print(f"Loading {args.period} history for {len(tickers)} tickers…")
    prices = load_history(tickers, period=args.period)
    print(f"  got {prices.shape[1]} tickers x {prices.shape[0]} days "
          f"({prices.index.min():%Y-%m-%d} to {prices.index.max():%Y-%m-%d})")

    horizons = list(HORIZONS) if args.horizon == "all" else [args.horizon]
    results, wf = {}, {}
    for h in horizons:
        print(f"Backtesting {h}…")
        res = run_backtest(prices, h, top_n=args.top_n, cost_bps=args.cost_bps)
        results[h] = res
        m = res.metrics
        print(f"  samples={m['periods']:>3}  strat CAGR={m['strat_cagr']*100:+5.1f}%  "
              f"bench={m['bench_cagr']*100:+5.1f}%  excess={m['excess_cagr']*100:+5.1f}%  "
              f"IC={m['ic_mean']:+.3f} (t={m['ic_t_stat']:.1f})")
        if args.walk_forward:
            wf[h] = walk_forward(prices, h, top_n=args.top_n, cost_bps=args.cost_bps)

    out = render(results, wf or None)
    print(f"\nTearsheet: {out}")
    if args.open:
        webbrowser.open(out.as_uri())
    return out


if __name__ == "__main__":
    main()
