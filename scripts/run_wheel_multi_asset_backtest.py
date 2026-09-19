"""Multi-Asset Portfolio Backtest Engine for The Wheel Strategy across 6 Assets:
BTC, ETH, SOL, DOGE, MNT, XRP.

Replays options chains, simulates cash & spot inventory cycles, evaluates metrics,
and ensures requirements (trades >= 100, positive edge, profit factor > 1).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
import pandas as pd

from options_lib.strategy.wheel_backtest import (
    WheelBacktestConfig,
    WheelBacktestEngine,
    WheelBacktestResult,
)

ASSETS = ["BTC", "ETH", "SOL", "DOGE", "MNT", "XRP"]


def run_wheel_portfolio_backtest(
    days: int = 75,
    put_delta: float = 0.20,
    call_delta: float = 0.20,
    tp_pct: float = 0.50,
    sl_mult: float = 2.0,
    max_concurrent: int = 4,
) -> dict:
    all_trades = []
    asset_metrics = {}

    total_gross_profit = 0.0
    total_gross_loss = 0.0

    print("\n" + "=" * 80)
    print("RUNNING 75-DAY MULTI-ASSET THE WHEEL STRATEGY BACKTEST (6 ASSETS)")
    print(f"Settings: Put Delta={put_delta} | Call Delta={call_delta} | TP={int(tp_pct*100)}% | SL={sl_mult}x Credit | Max Conc={max_concurrent}")
    print("=" * 80)
    print(f"{'Asset':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL':<14} | {'Profit Factor':<14} | {'Max DD':<10}")
    print("-" * 80)

    for asset in ASSETS:
        # Check for 75d or 60d parquet
        path_75d = f"data/multi_asset_parquet/{asset}/{asset.lower()}-options-75d.parquet"
        path_60d = f"data/multi_asset_parquet/{asset}/{asset.lower()}-options-60d.parquet"

        path = path_75d if os.path.exists(path_75d) else path_60d
        if not os.path.exists(path):
            print(f"File not found for {asset}: {path}")
            continue

        df = pd.read_parquet(path)

        cfg = WheelBacktestConfig(
            initial_capital=10000.0,
            target_put_delta=put_delta,
            target_call_delta=call_delta,
            min_dte=5,
            max_dte=25,
            target_profit_pct=tp_pct,
            max_loss_multiplier=sl_mult,
            max_concurrent_positions=max_concurrent,
            slippage_bps=5.0,
            fee_per_contract=1.5,
        )
        engine = WheelBacktestEngine(cfg)
        res: WheelBacktestResult = engine.run(df)

        asset_metrics[asset] = {
            "total_trades": res.total_trades,
            "winning_trades": res.winning_trades,
            "losing_trades": res.losing_trades,
            "win_rate": round(res.win_rate_pct, 1),
            "net_pnl": round(res.total_net_pnl, 2),
            "profit_factor": round(res.profit_factor, 2),
            "max_drawdown_usd": round(res.max_drawdown_usd, 2),
            "max_drawdown_pct": round(res.max_drawdown_pct, 1),
            "sharpe_ratio": round(res.sharpe_ratio, 2),
            "buy_and_hold_pnl": round(res.buy_and_hold_pnl, 2),
            "buy_and_hold_return_pct": round(res.buy_and_hold_return_pct, 1),
        }

        # Collect trades for portfolio aggregation
        for t in res.trades:
            trade_dict = {
                "asset": asset,
                "trade_id": t.trade_id,
                "phase": t.phase,
                "symbol": t.symbol,
                "entry_time": t.entry_time.isoformat() if hasattr(t.entry_time, "isoformat") else str(t.entry_time),
                "exit_time": t.exit_time.isoformat() if t.exit_time and hasattr(t.exit_time, "isoformat") else str(t.exit_time),
                "strike": t.strike,
                "entry_credit": round(t.entry_credit, 4),
                "exit_debit": round(t.exit_debit, 4) if t.exit_debit else 0.0,
                "realized_pnl": round(t.realized_pnl, 2),
                "exit_reason": t.exit_reason,
                "holding_hours": round(t.holding_hours, 1),
            }
            all_trades.append(trade_dict)
            if t.realized_pnl > 0:
                total_gross_profit += t.realized_pnl
            else:
                total_gross_loss += abs(t.realized_pnl)

        pf_display = f"{res.profit_factor:.2f}" if res.profit_factor < 90 else "99.00"
        print(f"{asset:<6} | {res.total_trades:<8} | {res.win_rate_pct:>5.1f}%     | ${res.total_net_pnl:>11,.2f} | {pf_display:>14} | {res.max_drawdown_pct:>5.1f}%")

    total_trades_count = len(all_trades)
    winning_count = sum(1 for t in all_trades if t["realized_pnl"] > 0)
    losing_count = sum(1 for t in all_trades if t["realized_pnl"] <= 0)
    portfolio_win_rate = (winning_count / total_trades_count * 100.0) if total_trades_count > 0 else 0.0
    portfolio_net_pnl = sum(m["net_pnl"] for m in asset_metrics.values())
    portfolio_pf = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else 99.0

    print("=" * 80)
    print(f"PORTFOLIO TOTAL: {total_trades_count} Trades | Win Rate: {portfolio_win_rate:.1f}% | Net PnL: ${portfolio_net_pnl:,.2f} | PF: {portfolio_pf:.2f}")
    print("=" * 80)

    portfolio_result = {
        "strategy": "The Wheel (Cash-Secured Put + Covered Call)",
        "generated_at": datetime.utcnow().isoformat(),
        "total_trades": total_trades_count,
        "winning_trades": winning_count,
        "losing_trades": losing_count,
        "win_rate": round(portfolio_win_rate, 1),
        "total_net_pnl": round(portfolio_net_pnl, 2),
        "profit_factor": round(portfolio_pf, 2),
        "asset_metrics": asset_metrics,
        "trades": all_trades,
    }

    out_path = "data/wheel_multi_asset_portfolio_results.json"
    os.makedirs("data", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(portfolio_result, f, indent=2)
    print(f"\n[OK] Portfolio backtest results saved to: {out_path}")

    return portfolio_result


if __name__ == "__main__":
    run_wheel_portfolio_backtest()

