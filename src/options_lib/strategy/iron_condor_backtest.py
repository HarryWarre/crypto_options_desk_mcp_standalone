"""Fast, low-memory Iron Condor Backtest Engine.

Replays options chains chronologically from downsampled snapshots (Parquet / Dataframe),
evaluating:
1. Volatility Regime condition (IV - RV spread check).
2. Delta-targeted 4-leg selection (Short Put ~ -0.15, Long Put Wing ~ -0.03,
   Short Call ~ +0.15, Long Call Wing ~ +0.03).
3. Lifecycle rules:
   - Early Take Profit at 50% max credit.
   - Stop Loss at 1.5x - 2.0x credit.
   - DTE roll when DTE <= 1 day.
4. Comprehensive Performance Metrics (Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    """Configuration for Iron Condor Backtest Replay."""

    initial_capital: float = 10000.0
    target_short_delta: float = 0.15
    target_wing_delta: float = 0.03
    min_dte: int = 7
    max_dte: int = 16
    iv_rv_threshold: float = 5.0  # Min IV - RV vol points to open trade
    target_profit_pct: float = 0.50  # 50% TP
    max_loss_multiplier: float = 2.0  # Stop loss at 2x credit
    roll_dte: float = 1.0  # Close when DTE <= 1
    slippage_bps: float = 5.0  # 5 bps slippage per leg
    fee_per_contract: float = 1.5  # $1.5 fee per leg executed
    max_concurrent_positions: int = 1


@dataclass
class TradeRecord:
    """Represents a completed or active Iron Condor trade in the backtest."""

    trade_id: str
    entry_time: datetime
    exit_time: datetime | None
    expiry: datetime
    dte_at_entry: float
    spot_entry: float
    spot_exit: float | None

    long_put_strike: float
    short_put_strike: float
    short_call_strike: float
    long_call_strike: float

    long_put_entry: float
    short_put_entry: float
    short_call_entry: float
    long_call_entry: float

    entry_credit: float
    qty: float
    exit_debit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class BacktestResult:
    """Overall summary statistics from backtest run."""

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
    trades: list[TradeRecord] = field(default_factory=list)
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
            "Expectancy / Trade": f"${self.expectancy_per_trade:,.2f}",
        }


class IronCondorBacktestEngine:
    """Engine executing chronological replay of Iron Condor strategy."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """Run backtest over a chronologically sorted options snapshot dataframe."""
        if df.empty:
            return BacktestResult(
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

        # Pre-group and index chains by timestamp for 100x lookup speed
        grouped = {}
        for ts, group in df.groupby("timestamp"):
            # Index by (expiry, option_type, strike) for O(1) mark lookup
            mark_lookup = {}
            for _, row in group.iterrows():
                mark_lookup[(row["expiry"], row["option_type"], row["strike"])] = row["mark_price"]
            grouped[ts] = (group, mark_lookup)

        timestamps = sorted(grouped.keys())
        capital = self.config.initial_capital
        peak_capital = capital
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        open_position: TradeRecord | None = None
        closed_trades: list[TradeRecord] = []
        equity_curve: list[dict[str, Any]] = []

        # Track underlying price history to estimate 30-day Realized Volatility
        price_history: list[tuple[datetime, float]] = []

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])
            price_history.append((ts, spot))

            # Keep only last 30 days of price history
            cutoff = ts - timedelta(days=30)
            price_history = [p for p in price_history if p[0] >= cutoff]

            # 1. Manage existing open position
            if open_position is not None:
                open_position, pnl_delta = self._evaluate_open_position(
                    open_position, mark_lookup, ts, spot
                )
                if open_position.exit_time is not None:
                    # Trade closed this step
                    capital += open_position.realized_pnl
                    closed_trades.append(open_position)
                    open_position = None

            # 2. Check if we should open a new position
            if open_position is None and len(closed_trades) < 1000:
                rv = self._estimate_realized_vol(price_history)
                candidate = self._find_candidate(chain, ts, spot, rv)
                if candidate is not None:
                    open_position = candidate

            # Track equity curve
            unrealized = 0.0
            if open_position is not None:
                unrealized = self._calc_unrealized_pnl(open_position, mark_lookup)
            current_equity = capital + unrealized
            equity_curve.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "equity": current_equity,
                "capital": capital,
                "unrealized": unrealized,
            })

            # Track drawdowns
            if current_equity > peak_capital:
                peak_capital = current_equity
            dd = peak_capital - current_equity
            dd_pct = (dd / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd > max_dd_usd:
                max_dd_usd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Close any lingering open position at last price
        if open_position is not None:
            _, last_lookup = grouped[timestamps[-1]]
            open_position, _ = self._evaluate_open_position(
                open_position, last_lookup, timestamps[-1], spot, force_close=True
            )
            capital += open_position.realized_pnl
            closed_trades.append(open_position)

        return self._build_results(closed_trades, equity_curve, max_dd_usd, max_dd_pct)

    def _find_candidate(
        self, chain: pd.DataFrame, ts: datetime, spot: float, rv: float
    ) -> TradeRecord | None:
        """Filter chain and locate optimal 4-leg Iron Condor candidate."""
        # Find expirations within min_dte and max_dte
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0
        valid_expiries = chain[
            (chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)
        ]
        if valid_expiries.empty:
            return None

        # Pick nearest expiry in window
        target_expiry = valid_expiries.sort_values("dte")["expiry"].iloc[0]
        sub = valid_expiries[valid_expiries["expiry"] == target_expiry]

        # Check IV - RV condition
        avg_iv = float(sub["mark_iv"].mean() * 100.0) if not sub.empty else 0.0
        if avg_iv - rv < self.config.iv_rv_threshold:
            return None  # Volatility premium too low to sell

        calls = sub[sub["option_type"] == "call"]
        puts = sub[sub["option_type"] == "put"]
        if calls.empty or puts.empty:
            return None

        # Target short legs (~0.15 delta) and wings (~0.03 delta)
        target_short = self.config.target_short_delta
        target_wing = self.config.target_wing_delta

        short_call_row = calls.iloc[(calls["delta"] - target_short).abs().argsort()[:1]]
        long_call_row = calls.iloc[(calls["delta"] - target_wing).abs().argsort()[:1]]

        short_put_row = puts.iloc[(puts["delta"].abs() - target_short).abs().argsort()[:1]]
        long_put_row = puts.iloc[(puts["delta"].abs() - target_wing).abs().argsort()[:1]]

        sc_strike = float(short_call_row["strike"].iloc[0])
        lc_strike = float(long_call_row["strike"].iloc[0])
        sp_strike = float(short_put_row["strike"].iloc[0])
        lp_strike = float(long_put_row["strike"].iloc[0])

        # Validate proper wing order: LP < SP < spot < SC < LC
        if not (lp_strike < sp_strike < spot < sc_strike < lc_strike):
            return None

        # Calculate entry prices (slippage applied)
        slip = self.config.slippage_bps / 10000.0
        sc_price = float(short_call_row["mark_price"].iloc[0]) * (1.0 - slip)
        lc_price = float(long_call_row["mark_price"].iloc[0]) * (1.0 + slip)
        sp_price = float(short_put_row["mark_price"].iloc[0]) * (1.0 - slip)
        lp_price = float(long_put_row["mark_price"].iloc[0]) * (1.0 + slip)

        net_credit = (sc_price + sp_price) - (lc_price + lp_price)
        if net_credit <= 0:
            return None

        fees = 4 * self.config.fee_per_contract
        trade_id = f"ic_{ts.strftime('%y%m%d%H%M')}_{int(spot)}"
        dte = float(sub["dte"].iloc[0])

        return TradeRecord(
            trade_id=trade_id,
            entry_time=ts,
            exit_time=None,
            expiry=target_expiry,
            dte_at_entry=dte,
            spot_entry=spot,
            spot_exit=None,
            long_put_strike=lp_strike,
            short_put_strike=sp_strike,
            short_call_strike=sc_strike,
            long_call_strike=lc_strike,
            long_put_entry=lp_price,
            short_put_entry=sp_price,
            short_call_entry=sc_price,
            long_call_entry=lc_price,
            entry_credit=net_credit - fees,
            qty=1.0,
        )

    def _evaluate_open_position(
        self,
        pos: TradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[TradeRecord, float]:
        """Check early take-profit, stop-loss, or expiration conditions."""
        slip = self.config.slippage_bps / 10000.0
        fees = 4 * self.config.fee_per_contract

        # Find current prices for all 4 legs using O(1) dict lookup
        legs_mark = self._get_legs_mark(pos, mark_lookup)
        if legs_mark is None and not force_close:
            return pos, 0.0

        current_debit = 0.0
        if legs_mark:
            lp_mark, sp_mark, sc_mark, lc_mark = legs_mark
            current_debit = (sp_mark + sc_mark) * (1.0 + slip) - (lp_mark + lc_mark) * (1.0 - slip)

        unrealized = (pos.entry_credit - current_debit) - fees
        max_credit = pos.entry_credit
        tp_target = max_credit * self.config.target_profit_pct
        stop_loss = -max_credit * self.config.max_loss_multiplier
        dte_now = (pos.expiry - ts).total_seconds() / 86400.0

        should_close = False
        reason = ""

        if force_close:
            should_close = True
            reason = "FORCE_CLOSE"
        elif unrealized >= tp_target:
            should_close = True
            reason = "TAKE_PROFIT_50"
        elif unrealized <= stop_loss:
            should_close = True
            reason = "STOP_LOSS"
        elif dte_now <= self.config.roll_dte:
            should_close = True
            reason = "EXPIRY_ROLL"

        if should_close:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = current_debit + fees
            pos.realized_pnl = unrealized
            pos.exit_reason = reason
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, unrealized

        return pos, 0.0

    def _calc_unrealized_pnl(
        self, pos: TradeRecord, mark_lookup: dict[tuple[Any, str, float], float]
    ) -> float:
        legs = self._get_legs_mark(pos, mark_lookup)
        if not legs:
            return 0.0
        lp, sp, sc, lc = legs
        debit = (sp + sc) - (lp + lc)
        return pos.entry_credit - debit

    def _get_legs_mark(
        self, pos: TradeRecord, mark_lookup: dict[tuple[Any, str, float], float]
    ) -> tuple[float, float, float, float] | None:
        """Fetch current mark price for the 4 strikes via O(1) dict lookup."""
        lp = mark_lookup.get((pos.expiry, "put", pos.long_put_strike))
        sp = mark_lookup.get((pos.expiry, "put", pos.short_put_strike))
        sc = mark_lookup.get((pos.expiry, "call", pos.short_call_strike))
        lc = mark_lookup.get((pos.expiry, "call", pos.long_call_strike))

        if any(v is None for v in (lp, sp, sc, lc)):
            return None
        return float(lp), float(sp), float(sc), float(lc)

    def _estimate_realized_vol(self, history: list[tuple[datetime, float]]) -> float:
        """Calculate annualized Realized Volatility from price series."""
        if len(history) < 10:
            return 45.0  # Safe default ~45% vol
        prices = [p[1] for p in history]
        returns = np.diff(np.log(prices))
        if len(returns) == 0:
            return 45.0
        # Annualize assuming 15m intervals (365 * 24 * 4 = 35040 intervals/year)
        vol = float(np.std(returns) * np.sqrt(35040.0) * 100.0)
        return max(10.0, min(150.0, vol))

    def _build_results(
        self,
        trades: list[TradeRecord],
        curve: list[dict[str, Any]],
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> BacktestResult:
        total = len(trades)
        if total == 0:
            return BacktestResult(
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
                equity_curve=curve,
            )

        pnls = [t.realized_pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_profit = sum(wins)
        total_loss = abs(sum(losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (99.0 if total_profit > 0 else 0.0)
        net_pnl = sum(pnls)
        win_rate = (len(wins) / total) * 100.0

        # Sharpe calculation
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls) if len(pnls) > 1 else 1.0
        sharpe = float((mean_pnl / std_pnl) * np.sqrt(52.0)) if std_pnl > 0 else 0.0

        return BacktestResult(
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round(win_rate, 2),
            total_net_pnl=round(net_pnl, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_usd=round(max_dd_usd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            expectancy_per_trade=round(net_pnl / total, 2),
            trades=trades,
            equity_curve=curve,
        )
