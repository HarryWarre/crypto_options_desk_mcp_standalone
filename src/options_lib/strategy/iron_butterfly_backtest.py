"""Fast, Vectorized Historical Backtest Engine for Iron Butterfly Strategy.

Simulates 4-leg Iron Butterfly combinations across historical Parquet snapshots:
- Sell ATM Straddle: Short Call (Delta ~ 0.50) + Short Put (Delta ~ -0.50) at identical strike.
- Buy OTM Wings: Long Call Wing (Delta ~ 0.08) + Long Put Wing (Delta ~ -0.08).
- Lifecycle Rules:
  - 30% Take Profit early exit.
  - 1.0x Stop Loss exit.
  - DTE <= 1.0 exit/roll.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from options_lib.risk.portfolio_risk_engine import calculate_backtest_position_size


@dataclass
class IronButterflyBacktestConfig:
    """Configuration for Iron Butterfly Backtest."""

    initial_capital: float = 10000.0
    target_wing_delta: float = 0.08
    min_dte: int = 3
    max_dte: int = 14
    target_profit_pct: float = 0.30
    max_loss_multiplier: float = 1.0
    roll_dte: float = 1.0
    slippage_bps: float = 5.0
    max_concurrent_positions: int = 4
    dynamic_sizing: bool = True
    risk_pct_per_trade: float = 0.02
    max_margin_utilization: float = 0.60
    asset: str = "BTC"
    fixed_qty: float | None = None



@dataclass
class IronButterflyTradeRecord:
    """Represents an individual Iron Butterfly 4-leg trade."""

    trade_id: str
    entry_time: datetime
    exit_time: datetime | None
    expiry: datetime
    dte_at_entry: float
    spot_entry: float
    spot_exit: float | None

    atm_strike: float
    long_put_strike: float
    long_call_strike: float

    entry_credit: float
    qty: float
    exit_debit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class IronButterflyBacktestResult:
    """Summary metrics from Iron Butterfly backtest."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    total_net_pnl: float
    profit_factor: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: float
    expectancy_per_trade: float
    trades: list[IronButterflyTradeRecord] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def summary_table(self) -> dict[str, Any]:
        return {
            "Total Trades": self.total_trades,
            "Winning Trades": self.winning_trades,
            "Losing Trades": self.losing_trades,
            "Win Rate": f"{self.win_rate_pct:.1f}%",
            "Total Net PnL": f"${self.total_net_pnl:,.2f}",
            "Profit Factor": f"{self.profit_factor:.2f}",
            "Max Drawdown": f"${self.max_drawdown_usd:,.2f} ({self.max_drawdown_pct:.1f}%)",
            "Sharpe Ratio": f"{self.sharpe_ratio:.2f}",
            "Expectancy / Trade": f"${self.expectancy_per_trade:.2f}",
        }


class IronButterflyBacktestEngine:
    """Replay Engine for Iron Butterfly Strategy."""

    def __init__(self, config: IronButterflyBacktestConfig | None = None):
        self.config = config or IronButterflyBacktestConfig()

    def run(self, df: pd.DataFrame) -> IronButterflyBacktestResult:
        if df.empty:
            return IronButterflyBacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                total_net_pnl=0.0,
                profit_factor=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                expectancy_per_trade=0.0,
            )

        df = df.copy()
        if "option_type" not in df.columns and "type" in df.columns:
            df["option_type"] = df["type"].astype(str).str.lower()
        elif "option_type" in df.columns:
            df["option_type"] = df["option_type"].astype(str).str.lower()
        df["option_type"] = df["option_type"].replace({"c": "call", "p": "put"})

        # Pre-group by timestamp
        grouped: dict[Any, tuple[pd.DataFrame, dict[tuple[Any, str, float], float]]] = {}
        for ts, group in df.groupby("timestamp"):
            mark_lookup = {}
            for _, row in group.iterrows():
                mark_lookup[(row["expiry"], row["option_type"], row["strike"])] = float(row["mark_price"])
            grouped[ts] = (group, mark_lookup)

        timestamps = sorted(grouped.keys())
        capital = self.config.initial_capital
        peak_capital = capital
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        open_positions: list[IronButterflyTradeRecord] = []
        closed_trades: list[IronButterflyTradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])

            # 1. Evaluate open positions
            remaining: list[IronButterflyTradeRecord] = []
            for pos in open_positions:
                eval_pos, _ = self._evaluate_position(pos, mark_lookup, ts, spot)
                if eval_pos.exit_time is not None:
                    capital += eval_pos.realized_pnl
                    closed_trades.append(eval_pos)
                else:
                    remaining.append(eval_pos)
            open_positions = remaining

            # 2. Enter new position if eligible
            can_enter = (
                len(open_positions) < self.config.max_concurrent_positions
                and (last_entry_time is None or (ts - last_entry_time).total_seconds() >= 6 * 3600)
            )

            if can_enter:
                candidate = self._find_candidate(chain, ts, spot, capital)
                if candidate is not None:
                    already_open = any(
                        p.expiry == candidate.expiry and p.atm_strike == candidate.atm_strike
                        for p in open_positions
                    )
                    if not already_open:
                        open_positions.append(candidate)
                        last_entry_time = ts

            # 3. Track equity
            unrealized = sum(self._calc_unrealized(p, mark_lookup) for p in open_positions)
            current_equity = capital + unrealized

            equity_curve.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "equity": current_equity,
                "capital": capital,
                "unrealized": unrealized,
            })

            if current_equity > peak_capital:
                peak_capital = current_equity
            dd = peak_capital - current_equity
            dd_pct = (dd / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd > max_dd_usd:
                max_dd_usd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Force close at end
        if open_positions:
            last_ts = timestamps[-1]
            _, last_lookup = grouped[last_ts]
            for pos in open_positions:
                pos, _ = self._evaluate_position(pos, last_lookup, last_ts, spot, force_close=True)
                capital += pos.realized_pnl
                closed_trades.append(pos)
            open_positions.clear()

        return self._build_results(closed_trades, equity_curve, capital - self.config.initial_capital, max_dd_usd, max_dd_pct)

    def _find_candidate(
        self, chain: pd.DataFrame, ts: datetime, spot: float, capital: float = 10000.0
    ) -> IronButterflyTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0
        valid = chain[(chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)]
        if valid.empty:
            return None

        expiries = sorted(valid["expiry"].unique())
        target_expiry = expiries[0]
        sub = valid[valid["expiry"] == target_expiry]

        calls = sub[sub["option_type"] == "call"]
        puts = sub[sub["option_type"] == "put"]

        common_strikes = set(calls["strike"]).intersection(set(puts["strike"]))
        if not common_strikes:
            return None

        # Pick strike closest to Spot (ATM)
        atm_strike = min(common_strikes, key=lambda s: abs(s - spot))

        sc_row = calls[calls["strike"] == atm_strike].iloc[0]
        sp_row = puts[puts["strike"] == atm_strike].iloc[0]

        # Call Wings (higher strike)
        call_wings = calls[calls["strike"] > atm_strike]
        put_wings = puts[puts["strike"] < atm_strike]

        if call_wings.empty or put_wings.empty:
            return None

        lc_row = call_wings.iloc[(call_wings["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]].iloc[0]
        lp_row = put_wings.iloc[(put_wings["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]].iloc[0]

        lc_strike = float(lc_row["strike"])
        lp_strike = float(lp_row["strike"])

        slip = self.config.slippage_bps / 10000.0
        sc_price = float(sc_row["mark_price"]) * (1.0 - slip)
        sp_price = float(sp_row["mark_price"]) * (1.0 - slip)
        lc_price = float(lc_row["mark_price"]) * (1.0 + slip)
        lp_price = float(lp_row["mark_price"]) * (1.0 + slip)

        raw_credit = (sc_price + sp_price) - (lc_price + lp_price)
        if raw_credit <= 0:
            return None

        fee = min(spot * 0.0012, max(0.0001, raw_credit * 0.08))
        net_credit = raw_credit - fee

        if net_credit <= 0:
            return None

        wing_width = max(abs(atm_strike - lp_strike), abs(lc_strike - atm_strike))
        max_loss_per_unit = max(1.0, wing_width - net_credit)

        if self.config.fixed_qty is not None:
            qty = self.config.fixed_qty
        elif self.config.dynamic_sizing:
            qty = calculate_backtest_position_size(
                current_equity=capital,
                asset=self.config.asset,
                max_loss_per_unit=max_loss_per_unit,
                risk_pct=self.config.risk_pct_per_trade,
                max_margin_utilization=self.config.max_margin_utilization,
            )
        else:
            notional = self.config.initial_capital / self.config.max_concurrent_positions
            qty = max(0.001, round(notional / spot, 4))

        if qty <= 0:
            return None

        return IronButterflyTradeRecord(
            trade_id=f"ib_{len(sub)}_{int(atm_strike)}",
            entry_time=ts,
            exit_time=None,
            expiry=target_expiry,
            dte_at_entry=float(sc_row["dte"]),
            spot_entry=spot,
            spot_exit=None,
            atm_strike=atm_strike,
            long_put_strike=lp_strike,
            long_call_strike=lc_strike,
            entry_credit=net_credit,
            qty=qty,
        )

    def _evaluate_position(
        self,
        pos: IronButterflyTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[IronButterflyTradeRecord, float]:
        sc_mark = mark_lookup.get((pos.expiry, "call", pos.atm_strike), max(0.0, spot - pos.atm_strike))
        sp_mark = mark_lookup.get((pos.expiry, "put", pos.atm_strike), max(0.0, pos.atm_strike - spot))
        lc_mark = mark_lookup.get((pos.expiry, "call", pos.long_call_strike), max(0.0, spot - pos.long_call_strike))
        lp_mark = mark_lookup.get((pos.expiry, "put", pos.long_put_strike), max(0.0, pos.long_put_strike - spot))

        slip = self.config.slippage_bps / 10000.0
        closing_cost_raw = (sc_mark + sp_mark) * (1.0 + slip) - (lc_mark + lp_mark) * (1.0 - slip)
        fee = min(spot * 0.0012, max(0.0001, closing_cost_raw * 0.08))
        closing_cost = closing_cost_raw + fee

        dte = (pos.expiry - ts).total_seconds() / 86400.0

        if force_close:
            pnl = (pos.entry_credit - closing_cost) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = closing_cost
            pos.realized_pnl = pnl
            pos.exit_reason = "FORCE_CLOSE"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 1. Expiry
        if dte <= 0.05:
            if closing_cost <= 0.01:
                pnl = pos.entry_credit * pos.qty
                pos.exit_reason = "EXPIRED_ATM_PIN"
            else:
                pnl = (pos.entry_credit - closing_cost) * pos.qty
                pos.exit_reason = "EXPIRED_OUT_OF_PIN"
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = closing_cost
            pos.realized_pnl = pnl
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 2. 30% Take Profit
        if closing_cost <= pos.entry_credit * (1.0 - self.config.target_profit_pct):
            pnl = (pos.entry_credit - closing_cost) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = closing_cost
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_30"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 3. Stop loss
        unrealized = (pos.entry_credit - closing_cost) * pos.qty
        if unrealized < -pos.entry_credit * pos.qty * self.config.max_loss_multiplier:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = closing_cost
            pos.realized_pnl = unrealized
            pos.exit_reason = "STOP_LOSS"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, unrealized

        return pos, 0.0

    def _calc_unrealized(
        self, pos: IronButterflyTradeRecord, mark_lookup: dict[tuple[Any, str, float], float]
    ) -> float:
        sc_mark = mark_lookup.get((pos.expiry, "call", pos.atm_strike), pos.entry_credit * 0.4)
        sp_mark = mark_lookup.get((pos.expiry, "put", pos.atm_strike), pos.entry_credit * 0.4)
        lc_mark = mark_lookup.get((pos.expiry, "call", pos.long_call_strike), 0.0)
        lp_mark = mark_lookup.get((pos.expiry, "put", pos.long_put_strike), 0.0)
        curr = (sc_mark + sp_mark) - (lc_mark + lp_mark)
        return (pos.entry_credit - curr) * pos.qty

    def _build_results(
        self,
        trades: list[IronButterflyTradeRecord],
        equity_curve: list[dict[str, Any]],
        net_pnl: float,
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> IronButterflyBacktestResult:
        total = len(trades)
        if total == 0:
            return IronButterflyBacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                total_net_pnl=0.0,
                profit_factor=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                expectancy_per_trade=0.0,
            )

        winning = sum(1 for t in trades if t.realized_pnl > 0)
        losing = sum(1 for t in trades if t.realized_pnl <= 0)
        win_rate = (winning / total) * 100.0

        gross_profit = sum(t.realized_pnl for t in trades if t.realized_pnl > 0)
        gross_loss = abs(sum(t.realized_pnl for t in trades if t.realized_pnl < 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 99.0

        pnls = [t.realized_pnl for t in trades]
        std_pnl = float(np.std(pnls)) if len(pnls) > 1 else 1.0
        mean_pnl = float(np.mean(pnls)) if pnls else 0.0
        sharpe = (mean_pnl / std_pnl * math.sqrt(len(pnls))) if std_pnl > 0 else 0.0

        return IronButterflyBacktestResult(
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            win_rate_pct=win_rate,
            total_net_pnl=net_pnl,
            profit_factor=pf,
            max_drawdown_usd=max_dd_usd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            expectancy_per_trade=mean_pnl,
            trades=trades,
            equity_curve=equity_curve,
        )

