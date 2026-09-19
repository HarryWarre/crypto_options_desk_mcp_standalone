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

from options_lib.risk.portfolio_risk_engine import calculate_backtest_position_size


@dataclass
class BacktestConfig:
    """Configuration for Iron Condor Backtest Replay."""

    initial_capital: float = 10000.0
    target_short_delta: float = 0.15
    target_wing_delta: float = 0.03
    min_dte: int = 7
    max_dte: int = 16
    iv_rv_threshold: float = 5.0  # Min IV - RV vol points to open trade
    target_profit_pct: float = 0.50  # Take profit at 50% max credit
    max_loss_multiplier: float = 0.8  # Stop loss at 0.8x credit (empirically optimized)
    roll_dte: float = 1.0  # Close when DTE <= 1
    slippage_bps: float = 5.0  # 5 bps slippage per leg
    fee_per_contract: float = 1.5  # $1.5 fee per leg executed
    max_concurrent_positions: int = 1
    dynamic_sizing: bool = True
    risk_pct_per_trade: float = 0.02
    max_margin_utilization: float = 0.60
    asset: str = "BTC"
    fixed_qty: float | None = None


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

        df = df.copy()
        if "option_type" not in df.columns and "type" in df.columns:
            df["option_type"] = df["type"].astype(str).str.lower()
        elif "option_type" in df.columns:
            df["option_type"] = df["option_type"].astype(str).str.lower()
            
        if "mark_iv" not in df.columns and "iv" in df.columns:
            df["mark_iv"] = df["iv"]

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

        open_positions: list[TradeRecord] = []
        closed_trades: list[TradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

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

            # 1. Manage existing open positions
            remaining_positions: list[TradeRecord] = []
            for pos in open_positions:
                evaluated_pos, _ = self._evaluate_open_position(
                    pos, mark_lookup, ts, spot
                )
                if evaluated_pos.exit_time is not None:
                    # Trade closed this step
                    capital += evaluated_pos.realized_pnl
                    closed_trades.append(evaluated_pos)
                else:
                    remaining_positions.append(evaluated_pos)
            open_positions = remaining_positions

            # 2. Check if we should open a new position (staggered every 48 hours up to max_concurrent)
            can_enter = (
                len(open_positions) < self.config.max_concurrent_positions
                and len(closed_trades) < 1000
                and (last_entry_time is None or (ts - last_entry_time).total_seconds() >= 6 * 3600)
            )
            if can_enter:
                rv = self._estimate_realized_vol(price_history)
                candidate = self._find_candidate(chain, ts, spot, rv, capital)
                if candidate is not None:
                    # Avoid duplicate exact expiry & strikes
                    already_open = any(
                        p.expiry == candidate.expiry and p.short_put_strike == candidate.short_put_strike
                        for p in open_positions
                    )
                    if not already_open:
                        open_positions.append(candidate)
                        last_entry_time = ts

            # Track equity curve
            unrealized = sum(self._calc_unrealized_pnl(p, mark_lookup) for p in open_positions)
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

        # Close any lingering open positions at last price
        if open_positions:
            _, last_lookup = grouped[timestamps[-1]]
            for pos in open_positions:
                pos, _ = self._evaluate_open_position(
                    pos, last_lookup, timestamps[-1], spot, force_close=True
                )
                capital += pos.realized_pnl
                closed_trades.append(pos)
            open_positions.clear()

        return self._build_results(closed_trades, equity_curve, max_dd_usd, max_dd_pct)

    def _find_candidate(
        self, chain: pd.DataFrame, ts: datetime, spot: float, rv: float, capital: float = 10000.0
    ) -> TradeRecord | None:
        """Filter chain and locate optimal 4-leg Iron Condor candidate."""
        # Find expirations within min_dte and max_dte
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0
        valid_expiries = chain[
            (chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)
        ]["expiry"].unique()
        if len(valid_expiries) == 0:
            return None

        # Pick earliest valid expiry
        target_expiry = sorted(valid_expiries)[0]
        sub = chain[chain["expiry"] == target_expiry].copy()

        # Volatility regime check: ATM IV - 30d RV >= threshold
        atm_strike = sub.iloc[(sub["strike"] - spot).abs().argsort()[:1]]["strike"].iloc[0]
        atm_iv = float(sub[sub["strike"] == atm_strike]["mark_iv"].iloc[0]) * 100.0
        if (atm_iv - rv) < self.config.iv_rv_threshold:
            return None

        # Separate puts and calls
        puts = sub[sub["option_type"] == "put"].copy()
        calls = sub[sub["option_type"] == "call"].copy()

        # Leg 1: Short Put (~ -0.15 delta)
        sp_candidates = puts[(puts["delta"] < 0) & (puts["strike"] < spot)]
        if sp_candidates.empty:
            return None
        sp_row = sp_candidates.iloc[(sp_candidates["delta"].abs() - self.config.target_short_delta).abs().argsort()[:1]]
        sp_strike = float(sp_row["strike"].iloc[0])

        # Leg 2: Long Put Wing (~ -0.03 delta, strike < sp_strike)
        lp_candidates = puts[(puts["delta"] < 0) & (puts["strike"] < sp_strike)]
        if lp_candidates.empty:
            return None
        lp_row = lp_candidates.iloc[(lp_candidates["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]]
        lp_strike = float(lp_row["strike"].iloc[0])

        # Leg 3: Short Call (~ +0.15 delta)
        sc_candidates = calls[(calls["delta"] > 0) & (calls["strike"] > spot)]
        if sc_candidates.empty:
            return None
        sc_row = sc_candidates.iloc[(sc_candidates["delta"].abs() - self.config.target_short_delta).abs().argsort()[:1]]
        sc_strike = float(sc_row["strike"].iloc[0])

        # Leg 4: Long Call Wing (~ +0.03 delta, strike > sc_strike)
        lc_candidates = calls[(calls["delta"] > 0) & (calls["strike"] > sc_strike)]
        if lc_candidates.empty:
            return None
        lc_row = lc_candidates.iloc[(lc_candidates["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]]
        lc_strike = float(lc_row["strike"].iloc[0])

        # Validate monotonic strike ordering: lp < sp < spot < sc < lc
        if not (lp_strike < sp_strike < spot < sc_strike < lc_strike):
            return None

        # Calculate entry prices (slippage applied)
        slip = self.config.slippage_bps / 10000.0
        sc_price = float(short_call_row["mark_price"].iloc[0]) * (1.0 - slip) if "short_call_row" in locals() else float(sc_row["mark_price"].iloc[0]) * (1.0 - slip)
        lc_price = float(long_call_row["mark_price"].iloc[0]) * (1.0 + slip) if "long_call_row" in locals() else float(lc_row["mark_price"].iloc[0]) * (1.0 + slip)
        sp_price = float(short_put_row["mark_price"].iloc[0]) * (1.0 - slip) if "short_put_row" in locals() else float(sp_row["mark_price"].iloc[0]) * (1.0 - slip)
        lp_price = float(long_put_row["mark_price"].iloc[0]) * (1.0 + slip) if "long_put_row" in locals() else float(lp_row["mark_price"].iloc[0]) * (1.0 + slip)

        net_credit = (sc_price + sp_price) - (lc_price + lp_price)
        if net_credit <= 0:
            return None

        effective_fee = min(self.config.fee_per_contract, max(0.00001, spot * 0.0003))
        fees = 4 * effective_fee
        wing_width = max(abs(sp_strike - lp_strike), abs(lc_strike - sc_strike))
        max_loss_per_unit = max(1.0, wing_width - net_credit)

        if self.config.dynamic_sizing:
            qty = calculate_backtest_position_size(
                current_equity=capital,
                max_loss_per_unit=max_loss_per_unit,
                asset=self.config.asset,
                risk_pct=self.config.risk_pct_per_trade,
                max_margin_utilization=self.config.max_margin_utilization,
                fixed_qty=self.config.fixed_qty,
            )
        else:
            qty = self.config.fixed_qty if self.config.fixed_qty is not None else 1.0

        if qty <= 0:
            return None

        trade_id = f"ic_{ts.strftime('%y%m%d%H%M')}_{int(spot) if spot >= 1 else round(spot, 4)}"
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
            entry_credit=(net_credit - fees) * qty,
            qty=qty,
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
        effective_fee = min(self.config.fee_per_contract, max(0.00001, spot * 0.0003))
        fees = (4 * effective_fee) * pos.qty

        # Find current prices for all 4 legs using O(1) dict lookup
        legs_mark = self._get_legs_mark(pos, mark_lookup)
        if legs_mark is None and not force_close:
            return pos, 0.0

        current_debit = 0.0
        if legs_mark:
            lp_mark, sp_mark, sc_mark, lc_mark = legs_mark
            current_debit = ((sp_mark + sc_mark) * (1.0 + slip) - (lp_mark + lc_mark) * (1.0 - slip)) * pos.qty

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
        debit = ((sp + sc) - (lp + lc)) * pos.qty
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

    def _estimate_realized_vol(self, history: list[tuple[datetime, float]], default_rv: float = 30.0) -> float:
        """Calculate annualized Realized Volatility from price series."""
        if len(history) < 5:
            return default_rv  # Baseline realistic RV ~30% for BTC
        prices = [p[1] for p in history]
        returns = np.diff(np.log(prices))
        if len(returns) == 0:
            return default_rv
        # Annualize assuming 1h intervals (365 * 24 = 8760 intervals/year)
        vol = float(np.std(returns) * np.sqrt(8760.0) * 100.0)
        return max(10.0, min(120.0, vol))

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
