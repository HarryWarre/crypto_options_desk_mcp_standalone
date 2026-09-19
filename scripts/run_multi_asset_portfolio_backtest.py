"""Multi-asset portfolio backtest engine across BTC, ETH, SOL, DOGE, MNT, XRP.

Simulates simultaneous options trading across multiple assets, records individual
trade executions, tracks overall portfolio equity, win rate, and drawdown.
"""

from __future__ import annotations

import json
import os
import pandas as pd
from datetime import datetime
from options_lib.strategy.iron_condor_backtest import BacktestConfig, IronCondorBacktestEngine, BacktestResult

ASSETS = ["BTC", "ETH", "SOL", "DOGE", "MNT", "XRP"]

def run_portfolio_backtest(
    days: int = 75,
    short_delta: float = 0.15,
    wing_delta: float = 0.03,
    tp_pct: float = 0.50,
    sl_mult: float = 0.8,
    max_concurrent: int = 4,
) -> dict:
    all_trades = []
    asset_metrics = {}
    
    total_gross_profit = 0.0
    total_gross_loss = 0.0
    
    print("\n" + "=" * 75)
    print(f"RUNNING 60-DAY MULTI-ASSET IRON CONDOR BACKTEST (6 TICKERS)")
    print(f"Settings: Short Delta={short_delta} | Wings={wing_delta} | TP={int(tp_pct*100)}% | SL={sl_mult}x Credit")
    print("=" * 75)
    print(f"{'Asset':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL':<12} | {'Profit Factor':<14} | {'Max DD':<10}")
    print("-" * 75)
    
    for asset in ASSETS:
        path = f"data/multi_asset_parquet/{asset}/{asset.lower()}-options-{days}d.parquet"
        if not os.path.exists(path):
            print(f"File not found for {asset}: {path}")
            continue
            
        df = pd.read_parquet(path)
        
        cfg = BacktestConfig(
            initial_capital=10000.0,
            target_short_delta=short_delta,
            target_wing_delta=wing_delta,
            min_dte=5,
            max_dte=30,
            iv_rv_threshold=0.0,
            target_profit_pct=tp_pct,
            max_loss_multiplier=sl_mult,
            max_concurrent_positions=max_concurrent,
        )
        engine = IronCondorBacktestEngine(cfg)
        res = engine.run(df)
        
        asset_metrics[asset] = {
            "trades": res.total_trades,
            "wins": res.winning_trades,
            "losses": res.losing_trades,
            "win_rate": res.win_rate_pct,
            "net_pnl": res.total_net_pnl,
            "profit_factor": res.profit_factor,
            "max_dd_pct": res.max_drawdown_pct,
        }
        
        for t in res.trades:
            pnl = t.realized_pnl
            if pnl > 0:
                total_gross_profit += pnl
            else:
                total_gross_loss += abs(pnl)
                
            all_trades.append({
                "asset": asset,
                "trade_id": t.trade_id,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat() if t.exit_time else "",
                "spot_entry": t.spot_entry,
                "spot_exit": t.spot_exit,
                "entry_credit": t.entry_credit,
                "exit_debit": t.exit_debit,
                "realized_pnl": t.realized_pnl,
                "exit_reason": t.exit_reason,
                "holding_hours": t.holding_hours,
            })
            
        print(f"{asset:<6} | {res.total_trades:<8} | {res.win_rate_pct:6.1f}%    | ${res.total_net_pnl:>10.2f} | {res.profit_factor:>10.2f}     | {res.max_drawdown_pct:6.2f}%")

    # Aggregate Portfolio
    total_trades = len(all_trades)
    winning_trades = sum(1 for t in all_trades if t["realized_pnl"] > 0)
    losing_trades = sum(1 for t in all_trades if t["realized_pnl"] <= 0)
    overall_win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
    overall_net_pnl = total_gross_profit - total_gross_loss
    overall_pf = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else 99.0
    
    print("-" * 75)
    print(f"PORTFOLIO TOTALS:")
    print(f"  Total Trades Across 6 Assets: {total_trades}")
    print(f"  Winning Trades: {winning_trades} | Losing Trades: {losing_trades}")
    print(f"  Overall Win Rate: {overall_win_rate:.1f}%")
    print(f"  Total Gross Profit: ${total_gross_profit:,.2f}")
    print(f"  Total Gross Loss: ${total_gross_loss:,.2f}")
    print(f"  Total Net PnL: ${overall_net_pnl:,.2f}")
    print(f"  Overall Profit Factor: {overall_pf:.2f}")
    print("=" * 75)
    
    portfolio_summary = {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(overall_win_rate, 2),
        "total_net_pnl": round(overall_net_pnl, 2),
        "profit_factor": round(overall_pf, 2),
        "asset_metrics": asset_metrics,
        "trades": all_trades,
    }
    
    # Save results to json
    os.makedirs("data", exist_ok=True)
    out_json = "data/multi_asset_portfolio_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(portfolio_summary, f, indent=2)
    print(f"Saved portfolio backtest output to {out_json}")
    
    return portfolio_summary

if __name__ == "__main__":
    run_portfolio_backtest()
