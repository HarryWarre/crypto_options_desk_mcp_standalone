"""Fast, Vectorized Historical Backtest Engine for Calendar Spread Strategy.

Simulates multi-tenor Calendar Spreads (Sell Near-Term, Buy Far-Term at ATM strike):
1. Pair Matching: Locates nearest available Far-Term (>20 DTE) and Near-Term (5-15 DTE) at common ATM strike.
2. Net Debit Execution: Long far-month contract + Short near-month contract.
3. Lifecycle Engine:
   - 30% Take Profit on Net Debit.
   - 35% Stop Loss on spread value decay.
   - Near-term roll / close when Near DTE <= 1.0.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class CalendarSpreadBacktestConfig:
    """Configuration for Calendar Spread Backtest."""

    initial_capital: float = 10000.0
    min_near_dte: int = 5
    max_near_dte: int = 15
    min_far_dte: int = 20
    max_far_dte: int = 60
    target_profit_pct: float = 0.30
    max_loss_pct: float = 0.35
    roll_dte: float = 1.0
    slippage_bps: float = 5.0
    max_concurrent_positions: int = 4


@dataclass
class CalendarSpreadTradeRecord:
    """Represents an individual Calendar Spread trade."""

    trade_id: str
    entry_time: datetime
    exit_time: datetime | None
    near_expiry: datetime
    far_expiry: datetime
    dte_at_entry: float
    spot_entry: float
    spot_exit: float | None

    strike: float
    option_type: str
    near_entry_price: float
    far_entry_price: float

    entry_debit: float
    qty: float
    exit_credit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class CalendarSpreadBacktestResult:
    """Summary metrics from Calendar Spread backtest."""

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
    trades: list[CalendarSpreadTradeRecord] = field(default_factory=list)
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


class CalendarSpreadBacktestEngine:
    """Replay Engine for Calendar Spread Strategy."""

    def __init__(self, config: CalendarSpreadBacktestConfig | None = None):
        self.config = config or CalendarSpreadBacktestConfig()

    def run(self, df: pd.DataFrame) -> CalendarSpreadBacktestResult:
        if df.empty:
            return CalendarSpreadBacktestResult(
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

        open_positions: list[CalendarSpreadTradeRecord] = []
        closed_trades: list[CalendarSpreadTradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])

            # 1. Manage existing open positions
            remaining: list[CalendarSpreadTradeRecord] = []
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
                candidate = self._find_candidate(chain, ts, spot)
                if candidate is not None:
                    already_open = any(
                        p.strike == candidate.strike and p.near_expiry == candidate.near_expiry
                        for p in open_positions
                    )
                    if not already_open:
                        open_positions.append(candidate)
                        last_entry_time = ts

            # 3. Track equity
            unrealized = sum(self._calc_unrealized(p, mark_lookup, spot) for p in open_positions)
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
        self, chain: pd.DataFrame, ts: datetime, spot: float
    ) -> CalendarSpreadTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0

        calls = chain[chain["option_type"] == "call"]
        if calls.empty:
            return None

        near_calls = calls[(calls["dte"] >= self.config.min_near_dte) & (calls["dte"] <= self.config.max_near_dte)]
        far_calls = calls[calls["dte"] >= self.config.min_far_dte]

        if near_calls.empty or far_calls.empty:
            # Fallback: pick shortest available and longest available if window differs
            all_dtes = sorted(calls["dte"].unique())
            if len(all_dtes) < 2:
                return None
            near_dtes = [d for d in all_dtes if d >= 4.0]
            if not near_dtes:
                return None
            shortest = near_dtes[0]
            longest = all_dtes[-1]
            if longest <= shortest:
                return None
            near_calls = calls[calls["dte"] == shortest]
            far_calls = calls[calls["dte"] == longest]

        # Find common strikes
        near_strikes = set(near_calls["strike"])
        far_strikes = set(far_calls["strike"])
        common = near_strikes.intersection(far_strikes)

        if not common:
            return None

        # Pick ATM strike closest to spot
        atm_strike = min(common, key=lambda s: abs(s - spot))

        near_row = near_calls[near_calls["strike"] == atm_strike].iloc[0]
        far_row = far_calls[far_calls["strike"] == atm_strike].iloc[0]

        near_expiry = near_row["expiry"]
        far_expiry = far_row["expiry"]

        slip = self.config.slippage_bps / 10000.0
        near_price = float(near_row["mark_price"]) * (1.0 - slip)  # Sold
        far_price = float(far_row["mark_price"]) * (1.0 + slip)    # Bought

        raw_debit = far_price - near_price
        if raw_debit <= 0:
            return None

        fee = min(spot * 0.0006, max(0.0001, raw_debit * 0.08))
        net_debit = raw_debit + fee

        notional = self.config.initial_capital / self.config.max_concurrent_positions
        qty = max(0.001, round(notional / spot, 4))

        return CalendarSpreadTradeRecord(
            trade_id=f"cs_{int(atm_strike)}_{int(near_row['dte'])}d",
            entry_time=ts,
            exit_time=None,
            near_expiry=near_expiry,
            far_expiry=far_expiry,
            dte_at_entry=float(near_row["dte"]),
            spot_entry=spot,
            spot_exit=None,
            strike=atm_strike,
            option_type="call",
            near_entry_price=near_price,
            far_entry_price=far_price,
            entry_debit=net_debit,
            qty=qty,
        )

    def _evaluate_position(
        self,
        pos: CalendarSpreadTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[CalendarSpreadTradeRecord, float]:
        near_mark = mark_lookup.get((pos.near_expiry, pos.option_type, pos.strike), max(0.0, spot - pos.strike))
        far_mark = mark_lookup.get((pos.far_expiry, pos.option_type, pos.strike), max(0.0, spot - pos.strike))

        slip = self.config.slippage_bps / 10000.0
        # Closing value: Sell far leg, Buy back near leg
        current_spread_val = (far_mark * (1.0 - slip)) - (near_mark * (1.0 + slip))
        fee = min(spot * 0.0006, max(0.0001, abs(current_spread_val) * 0.08))
        net_closing_val = max(0.0, current_spread_val - fee)

        near_dte = (pos.near_expiry - ts).total_seconds() / 86400.0
        pnl = (net_closing_val - pos.entry_debit) * pos.qty

        if force_close:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "FORCE_CLOSE"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 1. Near-term expiration: harvest maximum near theta
        if near_dte <= 0.05:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "NEAR_EXPIRY_HARVEST"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 2. 30% Take Profit
        if net_closing_val >= pos.entry_debit * (1.0 + self.config.target_profit_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_30"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 3. Stop loss (value dropped by 35%)
        if net_closing_val <= pos.entry_debit * (1.0 - self.config.max_loss_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "STOP_LOSS"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        return pos, 0.0

    def _calc_unrealized(
        self, pos: CalendarSpreadTradeRecord, mark_lookup: dict[tuple[Any, str, float], float], spot: float
    ) -> float:
        near_mark = mark_lookup.get((pos.near_expiry, pos.option_type, pos.strike), pos.near_entry_price)
        far_mark = mark_lookup.get((pos.far_expiry, pos.option_type, pos.strike), pos.far_entry_price)
        current_val = far_mark - near_mark
        return (current_val - pos.entry_debit) * pos.qty

    def _build_results(
        self,
        trades: list[CalendarSpreadTradeRecord],
        equity_curve: list[dict[str, Any]],
        net_pnl: float,
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> CalendarSpreadBacktestResult:
        total = len(trades)
        if total == 0:
            return CalendarSpreadBacktestResult(
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

        return CalendarSpreadBacktestResult(
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
