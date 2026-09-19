"""Grid search and parameter optimizer for Iron Condor Bot.

Replays options snapshots across different configurations:
- Delta levels (0.10, 0.15, 0.20)
- Take-profit thresholds (40%, 50%, 60%)
- Stop-loss multipliers (1.5x, 2.0x, 2.5x)
- IV - RV regime thresholds (0, 3, 5)

Outputs a markdown comparison table identifying the configuration with positive
expectancy, high Sharpe ratio, and low drawdown.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from options_lib.data.deribit_downloader import load_parquet_snapshots
from options_lib.strategy.iron_condor_backtest import (
    BacktestConfig,
    IronCondorBacktestEngine,
)


def run_grid_search(parquet_file: str = "data/deribit_parquet/deribit-btc-options.parquet"):
    path = Path(parquet_file)
    if not path.exists():
        print(f"File {parquet_file} does not exist. Run conversion first.")
        return

    print(f"Loading options snapshots from {parquet_file}...")
    df = load_parquet_snapshots(path, asset="BTC")
    print(f"Loaded {len(df):,} quote rows across {df['timestamp'].nunique():,} snapshots.\n")

    short_deltas = [0.12, 0.15, 0.18]
    tp_pcts = [0.40, 0.50, 0.60]
    sl_mults = [1.5, 2.0, 2.5]
    iv_rv_thresholds = [0.0, 3.0, 5.0]

    combinations = list(itertools.product(short_deltas, tp_pcts, sl_mults, iv_rv_thresholds))
    print(f"Running grid search across {len(combinations)} parameter sets...\n")

    results = []

    for short_d, tp, sl, iv_rv in combinations:
        cfg = BacktestConfig(
            initial_capital=10000.0,
            target_short_delta=short_d,
            target_wing_delta=0.03,
            min_dte=7,
            max_dte=30,
            iv_rv_threshold=iv_rv,
            target_profit_pct=tp,
            max_loss_multiplier=sl,
            roll_dte=1.0,
        )
        engine = IronCondorBacktestEngine(cfg)
        res = engine.run(df)

        if res.total_trades > 0:
            results.append({
                "short_delta": short_d,
                "tp_pct": tp,
                "sl_mult": sl,
                "iv_rv": iv_rv,
                "trades": res.total_trades,
                "win_rate": res.win_rate_pct,
                "net_pnl": res.total_net_pnl,
                "profit_factor": res.profit_factor,
                "max_dd_pct": res.max_drawdown_pct,
                "sharpe": res.sharpe_ratio,
                "expectancy": res.expectancy_per_trade,
            })

    if not results:
        print("No trades generated across any configurations.")
        return

    # Sort by Net PnL descending, then Sharpe
    results.sort(key=lambda x: (x["net_pnl"], x["sharpe"]), reverse=True)

    print("=" * 110)
    print("TOP 10 IRON CONDOR CONFIGURATIONS (SORTED BY NET PNL & SHARPE)")
    print("=" * 110)
    header = f"{'Delta':<7} {'TP %':<6} {'SL x':<6} {'IV-RV':<7} {'Trades':<7} {'Win Rate':<10} {'Net PnL':<12} {'PF':<6} {'Max DD %':<10} {'Sharpe':<8} {'Expectancy':<10}"
    print(header)
    print("-" * 110)

    for r in results[:10]:
        print(
            f"{r['short_delta']:<7.2f} {int(r['tp_pct']*100)}%    {r['sl_mult']:<6.1f} {r['iv_rv']:<7.1f} "
            f"{r['trades']:<7} {r['win_rate']:<9.1f}% ${r['net_pnl']:<11,.2f} {r['profit_factor']:<6.2f} "
            f"{r['max_dd_pct']:<9.1f}% {r['sharpe']:<8.2f} ${r['expectancy']:<9.2f}"
        )

    print("=" * 110)
    best = results[0]
    print("\nBEST RECOMMENDED CONFIGURATION:")
    print(f"  - Target Short Delta: {best['short_delta']}")
    print(f"  - Target Profit: {int(best['tp_pct']*100)}% Max Credit")
    print(f"  - Stop Loss: {best['sl_mult']}x Max Credit")
    print(f"  - IV - RV Threshold: {best['iv_rv']} vol points")
    print(f"  -> Win Rate: {best['win_rate']:.1f}% | Net PnL: ${best['net_pnl']:,.2f} | Expectancy: ${best['expectancy']:.2f}/trade")


if __name__ == "__main__":
    run_grid_search()

