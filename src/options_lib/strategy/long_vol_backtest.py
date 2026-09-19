"""Fast, Vectorized Historical Backtest Engine for Long Volatility Straddle & Strangle Strategy.

Simulates Long Volatility Expansion Plays:
1. Implied Volatility Discount Screener:
   Identifies periods where Realized Volatility (RV) >= Implied Volatility (IV) * 1.00.
2. Long Straddle Construction:
   Enters simultaneous Long ATM Call + Long ATM Put with defined risk capped at Net Debit.
3. Convex Payoff Lifecycle:
   - 35% Take Profit on Net Debit.
   - 25% Stop Loss on Net Debit decay.
   - Expiration harvest exit when DTE <= 1.0 day to avoid terminal zero-value decay.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import py_vollib.black_scholes as bs

from options_lib.risk.portfolio_risk_engine import calculate_backtest_position_size


@dataclass
class LongVolBacktestConfig:
    """Configuration for Long Volatility Backtest."""

    initial_capital: float = 10000.0
    min_dte: int = 5
    max_dte: int = 18
    min_rv_iv_ratio: float = 1.00      # Realized vol >= Implied vol * ratio
    target_profit_pct: float = 0.35    # Take profit at 35% ROI
    max_loss_pct: float = 0.25         # Stop loss at 25% loss
    exit_dte: float = 1.0              # Exit before last 24h
    slippage_bps: float = 5.0
    max_concurrent_positions: int = 3
    cooldown_hours: float = 6.0
    dynamic_sizing: bool = True
    risk_pct_per_trade: float = 0.02
    risk_per_trade_pct: float | None = None
    max_margin_utilization: float = 0.60
    asset: str = "BTC"
    fixed_qty: float | None = None


@dataclass
class LongVolTradeRecord:
    """Represents an individual Long Straddle/Strangle trade."""

    trade_id: str
    entry_time: datetime
    exit_time: datetime | None
    expiry: datetime
    dte_at_entry: float
    spot_entry: float
    spot_exit: float | None

    call_strike: float
    put_strike: float
    call_entry_price: float
    put_entry_price: float

    entry_debit: float
    qty: float
    iv_at_entry: float
    rv_at_entry: float
    margin_per_unit: float = 0.0
    exit_credit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class LongVolBacktestResult:
    """Summary metrics from Long Volatility backtest."""

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
    trades: list[LongVolTradeRecord] = field(default_factory=list)
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


class LongVolBacktestEngine:
    """Replay Engine for Long Volatility Straddle Strategy."""

    def __init__(self, config: LongVolBacktestConfig | None = None):
        self.config = config or LongVolBacktestConfig()

    def _price_leg(
        self, option_type: str, spot: float, strike: float, dte: float, iv: float
    ) -> float:
        """Black-Scholes valuation fallback when contract is omitted from downsampled snapshot."""
        if dte <= 0.001:
            return max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
        try:
            t = max(0.001, dte / 365.0)
            flag = "c" if option_type == "call" else "p"
            val = float(bs.black_scholes(flag, spot, strike, t, 0.05, max(0.1, iv)))
            return max(0.0, val)
        except Exception:
            return max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)

    def run(self, df: pd.DataFrame) -> LongVolBacktestResult:
        if df.empty:
            return LongVolBacktestResult(
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
        spot_series = pd.Series({ts: grouped[ts][0]["underlying_price"].iloc[0] for ts in timestamps})
        ret = spot_series.pct_change()
        rv_series = ret.rolling(24, min_periods=5).std() * np.sqrt(365 * 12)  # ~48h realized vol

        capital = self.config.initial_capital
        peak_capital = capital
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        open_positions: list[LongVolTradeRecord] = []
        closed_trades: list[LongVolTradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])
            rv_val = rv_series.loc[ts] if ts in rv_series.index and pd.notnull(rv_series.loc[ts]) else 0.50

            # 1. Manage existing open positions
            remaining: list[LongVolTradeRecord] = []
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
                and (last_entry_time is None or (ts - last_entry_time).total_seconds() >= self.config.cooldown_hours * 3600)
            )

            if can_enter:
                candidate = self._find_candidate(
                    chain,
                    ts,
                    spot,
                    rv_val,
                    capital,
                    self._margin_used(open_positions),
                )
                if candidate is not None:
                    open_positions.append(candidate)
                    last_entry_time = ts

            # 3. Track equity
            unrealized = sum(self._calc_unrealized(p, mark_lookup, ts, spot) for p in open_positions)
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

        # Force close remaining at end
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
        self,
        chain: pd.DataFrame,
        ts: datetime,
        spot: float,
        rv_val: float,
        capital: float = 10000.0,
        current_margin_used: float = 0.0,
    ) -> LongVolTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0

        eligible = chain[(chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)]
        if eligible.empty:
            return None

        # Check IV Discount
        avg_iv = float(eligible["iv"].median())
        if rv_val < avg_iv * self.config.min_rv_iv_ratio:
            return None

        calls = eligible[eligible["option_type"] == "call"]
        puts = eligible[eligible["option_type"] == "put"]
        common = set(calls["strike"]).intersection(set(puts["strike"]))
        if not common:
            return None

        atm_strike = min(common, key=lambda s: abs(s - spot))
        if abs(atm_strike - spot) / spot > 0.03:
            return None

        c_row = calls[calls["strike"] == atm_strike].iloc[0]
        p_row = puts[puts["strike"] == atm_strike].iloc[0]

        slip = self.config.slippage_bps / 10000.0
        c_price = float(c_row["mark_price"]) * (1.0 + slip)
        p_price = float(p_row["mark_price"]) * (1.0 + slip)

        raw_debit = c_price + p_price
        if raw_debit <= 0:
            return None

        fee = min(spot * 0.0006 * 2, max(0.0002, raw_debit * 0.08))
        net_debit = raw_debit + fee

        max_loss_per_unit = max(1.0, net_debit)
        if self.config.fixed_qty is not None:
            qty = self.config.fixed_qty
        elif self.config.dynamic_sizing:
            qty = calculate_backtest_position_size(
                current_equity=capital,
                asset=self.config.asset,
                max_loss_per_unit=max_loss_per_unit,
                risk_pct=(
                    self.config.risk_per_trade_pct
                    if self.config.risk_per_trade_pct is not None
                    else self.config.risk_pct_per_trade
                ),
                max_margin_utilization=self.config.max_margin_utilization,
                current_margin_used=current_margin_used,
            )
        else:
            qty = 1.0

        if qty <= 0:
            return None
        iv_val = float(c_row.get("iv", avg_iv))

        return LongVolTradeRecord(
            trade_id=f"lv_{int(atm_strike)}_{int(c_row['dte'])}d",
            entry_time=ts,
            exit_time=None,
            expiry=c_row["expiry"],
            dte_at_entry=float(c_row["dte"]),
            spot_entry=spot,
            spot_exit=None,
            call_strike=atm_strike,
            put_strike=atm_strike,
            call_entry_price=c_price,
            put_entry_price=p_price,
            entry_debit=net_debit,
            qty=qty,
            iv_at_entry=iv_val,
            rv_at_entry=rv_val,
            margin_per_unit=max_loss_per_unit,
        )

    @staticmethod
    def _margin_used(positions: list[LongVolTradeRecord]) -> float:
        return sum(max(1.0, pos.margin_per_unit) * pos.qty for pos in positions)

    def _evaluate_position(
        self,
        pos: LongVolTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[LongVolTradeRecord, float]:
        dte = (pos.expiry - ts).total_seconds() / 86400.0

        c_mark = mark_lookup.get(
            (pos.expiry, "call", pos.call_strike),
            self._price_leg("call", spot, pos.call_strike, dte, pos.iv_at_entry),
        )
        p_mark = mark_lookup.get(
            (pos.expiry, "put", pos.put_strike),
            self._price_leg("put", spot, pos.put_strike, dte, pos.iv_at_entry),
        )

        slip = self.config.slippage_bps / 10000.0
        # Closing value: Sell Call, Sell Put
        current_spread_val = (c_mark * (1.0 - slip)) + (p_mark * (1.0 - slip))
        fee = min(spot * 0.0006 * 2, max(0.0002, abs(current_spread_val) * 0.08))
        net_closing_val = max(0.0, current_spread_val - fee)

        pnl = (net_closing_val - pos.entry_debit) * pos.qty

        if force_close:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "FORCE_CLOSE"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 1. 35% Take Profit on Net Debit
        if net_closing_val >= pos.entry_debit * (1.0 + self.config.target_profit_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_35"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 2. 25% Stop Loss
        if net_closing_val <= pos.entry_debit * (1.0 - self.config.max_loss_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "SL_25"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 3. Expiration Exit (DTE <= 1.0 day)
        if dte <= self.config.exit_dte:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "EXPIRY_EXIT"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        return pos, 0.0

    def _calc_unrealized(
        self,
        pos: LongVolTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
    ) -> float:
        dte = (pos.expiry - ts).total_seconds() / 86400.0
        c_mark = mark_lookup.get(
            (pos.expiry, "call", pos.call_strike),
            self._price_leg("call", spot, pos.call_strike, dte, pos.iv_at_entry),
        )
        p_mark = mark_lookup.get(
            (pos.expiry, "put", pos.put_strike),
            self._price_leg("put", spot, pos.put_strike, dte, pos.iv_at_entry),
        )
        slip = self.config.slippage_bps / 10000.0
        cur_spread = (c_mark * (1.0 - slip)) + (p_mark * (1.0 - slip))
        fee = min(spot * 0.0006 * 2, max(0.0002, abs(cur_spread) * 0.08))
        net_close = max(0.0, cur_spread - fee)
        return (net_close - pos.entry_debit) * pos.qty

    def _build_results(
        self,
        trades: list[LongVolTradeRecord],
        equity_curve: list[dict[str, Any]],
        net_pnl: float,
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> LongVolBacktestResult:
        total = len(trades)
        if total == 0:
            return LongVolBacktestResult(
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
                trades=[],
                equity_curve=equity_curve,
            )

        wins = [t for t in trades if t.realized_pnl > 0]
        losses = [t for t in trades if t.realized_pnl <= 0]
        win_rate = (len(wins) / total) * 100.0
        gross_profit = sum(t.realized_pnl for t in wins)
        gross_loss = sum(abs(t.realized_pnl) for t in losses)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.0

        pnls = [t.realized_pnl for t in trades]
        std = np.std(pnls) if len(pnls) > 1 else 0.0
        mean_pnl = np.mean(pnls) if pnls else 0.0
        sharpe = (mean_pnl / std * math.sqrt(total)) if std > 0 else 0.0

        return LongVolBacktestResult(
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=win_rate,
            total_net_pnl=net_pnl,
            profit_factor=profit_factor,
            max_drawdown_usd=max_dd_usd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            expectancy_per_trade=mean_pnl,
            trades=trades,
            equity_curve=equity_curve,
        )
