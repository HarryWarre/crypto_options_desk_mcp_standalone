"""Fast, Vectorized Historical Backtest Engine for Directional Vertical Credit Spreads.

Simulates Bull Put Spreads and Bear Call Spreads across historical Parquet snapshots:
1. Dynamic Regime Detection: Trend direction via 20-period underlying price momentum.
2. 2-Leg Selection:
   - Bull Put Spread: Short Put ~0.18 Delta, Long Put Wing ~0.05 Delta (when trend >= 0).
   - Bear Call Spread: Short Call ~0.18 Delta, Long Call Wing ~0.05 Delta (when trend < 0).
3. Lifecycle Management:
   - 50% Take Profit early exit.
   - Stop loss at 1.5x - 2.0x credit.
   - Roll / close when DTE <= 1.0.
4. Comprehensive Quantitative Metrics (Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown).
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
class VerticalSpreadBacktestConfig:
    """Configuration for Vertical Credit Spreads Backtest."""

    initial_capital: float = 10000.0
    target_short_delta: float = 0.18
    target_wing_delta: float = 0.05
    min_dte: int = 5
    max_dte: int = 16
    target_profit_pct: float = 0.50
    max_loss_multiplier: float = 1.8
    roll_dte: float = 1.0
    slippage_bps: float = 5.0
    fee_per_contract: float = 1.5
    max_concurrent_positions: int = 4
    trend_window_hours: int = 48  # Lookback to detect trend
    dynamic_sizing: bool = True
    risk_pct_per_trade: float = 0.02
    max_margin_utilization: float = 0.60
    asset: str = "BTC"
    fixed_qty: float | None = None


@dataclass
class VerticalSpreadTradeRecord:
    """Represents an individual vertical credit spread trade."""

    trade_id: str
    spread_type: str  # "BULL_PUT" or "BEAR_CALL"
    entry_time: datetime
    exit_time: datetime | None
    expiry: datetime
    dte_at_entry: float
    spot_entry: float
    spot_exit: float | None

    short_strike: float
    wing_strike: float
    short_entry_price: float
    wing_entry_price: float

    entry_credit: float
    qty: float
    exit_debit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class VerticalSpreadBacktestResult:
    """Summary metrics from Vertical Credit Spreads backtest."""

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
    trades: list[VerticalSpreadTradeRecord] = field(default_factory=list)
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


class VerticalSpreadBacktestEngine:
    """Replay Engine for Directional Vertical Credit Spreads."""

    def __init__(self, config: VerticalSpreadBacktestConfig | None = None):
        self.config = config or VerticalSpreadBacktestConfig()

    def run(self, df: pd.DataFrame) -> VerticalSpreadBacktestResult:
        if df.empty:
            return VerticalSpreadBacktestResult(
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

        open_positions: list[VerticalSpreadTradeRecord] = []
        closed_trades: list[VerticalSpreadTradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

        price_history: list[tuple[datetime, float]] = []

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])
            price_history.append((ts, spot))

            cutoff = ts - timedelta(hours=self.config.trend_window_hours)
            price_history = [p for p in price_history if p[0] >= cutoff]

            # 1. Manage existing positions
            remaining_positions: list[VerticalSpreadTradeRecord] = []
            for pos in open_positions:
                eval_pos, _ = self._evaluate_position(pos, mark_lookup, ts, spot)
                if eval_pos.exit_time is not None:
                    capital += eval_pos.realized_pnl
                    closed_trades.append(eval_pos)
                else:
                    remaining_positions.append(eval_pos)
            open_positions = remaining_positions

            # 2. Enter new position if eligible
            can_enter = (
                len(open_positions) < self.config.max_concurrent_positions
                and (last_entry_time is None or (ts - last_entry_time).total_seconds() >= 6 * 3600)
            )

            if can_enter and len(price_history) >= 2:
                trend = self._determine_trend(price_history)
                candidate = self._find_candidate(chain, ts, spot, trend, capital)
                if candidate is not None:
                    # Avoid identical duplicate strike
                    already_open = any(
                        p.expiry == candidate.expiry and p.short_strike == candidate.short_strike
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

        # Force close remaining
        if open_positions:
            last_ts = timestamps[-1]
            _, last_lookup = grouped[last_ts]
            for pos in open_positions:
                pos, _ = self._evaluate_position(pos, last_lookup, last_ts, spot, force_close=True)
                capital += pos.realized_pnl
                closed_trades.append(pos)
            open_positions.clear()

        return self._build_results(closed_trades, equity_curve, capital - self.config.initial_capital, max_dd_usd, max_dd_pct)

    def _determine_trend(self, price_history: list[tuple[datetime, float]]) -> str:
        """Simple momentum trend: price vs historical lookback mean."""
        spots = [p[1] for p in price_history]
        mean_spot = float(np.mean(spots))
        current_spot = spots[-1]
        return "BULLISH" if current_spot >= mean_spot else "BEARISH"

    def _find_candidate(
        self, chain: pd.DataFrame, ts: datetime, spot: float, trend: str, capital: float = 10000.0
    ) -> VerticalSpreadTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0
        valid = chain[(chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)]
        if valid.empty:
            return None

        expiries = sorted(valid["expiry"].unique())
        target_expiry = expiries[0]
        sub = valid[valid["expiry"] == target_expiry]

        slip = self.config.slippage_bps / 10000.0

        if trend == "BULLISH":
            # Bull Put Spread: sell short put (~0.18 delta), buy long put wing (~0.05 delta)
            puts = sub[(sub["option_type"] == "put") & (sub["strike"] < spot)].copy()
            if len(puts) < 2:
                return None

            short_candidates = puts.iloc[(puts["delta"].abs() - self.config.target_short_delta).abs().argsort()[:1]]
            if short_candidates.empty:
                return None
            sp_row = short_candidates.iloc[0]
            sp_strike = float(sp_row["strike"])

            wing_pool = puts[puts["strike"] < sp_strike]
            if wing_pool.empty:
                return None
            lp_row = wing_pool.iloc[(wing_pool["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]].iloc[0]
            lp_strike = float(lp_row["strike"])

            sp_price = float(sp_row["mark_price"]) * (1.0 - slip)
            lp_price = float(lp_row["mark_price"]) * (1.0 + slip)
            spread_raw = sp_price - lp_price
            if spread_raw <= 0:
                return None

            fee = min(spot * 0.0006, max(0.0001, spread_raw * 0.08))
            net_credit = spread_raw - fee

            if net_credit <= 0:
                return None

            wing_width = abs(sp_strike - lp_strike)
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
                notional = self.config.initial_capital / self.config.max_concurrent_positions
                qty = self.config.fixed_qty if self.config.fixed_qty is not None else max(0.001, round(notional / spot, 4))

            if qty <= 0:
                return None

            return VerticalSpreadTradeRecord(
                trade_id=f"bp_{len(sub)}_{int(sp_strike)}",
                spread_type="BULL_PUT",
                entry_time=ts,
                exit_time=None,
                expiry=target_expiry,
                dte_at_entry=float(sp_row["dte"]),
                spot_entry=spot,
                spot_exit=None,
                short_strike=sp_strike,
                wing_strike=lp_strike,
                short_entry_price=sp_price,
                wing_entry_price=lp_price,
                entry_credit=net_credit,
                qty=qty,
            )
        else:
            # Bear Call Spread: sell short call (~0.18 delta), buy long call wing (~0.05 delta)
            calls = sub[(sub["option_type"] == "call") & (sub["strike"] > spot)].copy()
            if len(calls) < 2:
                return None

            short_candidates = calls.iloc[(calls["delta"].abs() - self.config.target_short_delta).abs().argsort()[:1]]
            if short_candidates.empty:
                return None
            sc_row = short_candidates.iloc[0]
            sc_strike = float(sc_row["strike"])

            wing_pool = calls[calls["strike"] > sc_strike]
            if wing_pool.empty:
                return None
            lc_row = wing_pool.iloc[(wing_pool["delta"].abs() - self.config.target_wing_delta).abs().argsort()[:1]].iloc[0]
            lc_strike = float(lc_row["strike"])

            sc_price = float(sc_row["mark_price"]) * (1.0 - slip)
            lc_price = float(lc_row["mark_price"]) * (1.0 + slip)
            spread_raw = sc_price - lc_price
            if spread_raw <= 0:
                return None

            fee = min(spot * 0.0006, max(0.0001, spread_raw * 0.08))
            net_credit = spread_raw - fee

            if net_credit <= 0:
                return None

            wing_width = abs(lc_strike - sc_strike)
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
                notional = self.config.initial_capital / self.config.max_concurrent_positions
                qty = self.config.fixed_qty if self.config.fixed_qty is not None else max(0.001, round(notional / spot, 4))

            if qty <= 0:
                return None

            return VerticalSpreadTradeRecord(
                trade_id=f"bc_{len(sub)}_{int(sc_strike)}",
                spread_type="BEAR_CALL",
                entry_time=ts,
                exit_time=None,
                expiry=target_expiry,
                dte_at_entry=float(sc_row["dte"]),
                spot_entry=spot,
                spot_exit=None,
                short_strike=sc_strike,
                wing_strike=lc_strike,
                short_entry_price=sc_price,
                wing_entry_price=lc_price,
                entry_credit=net_credit,
                qty=qty,
            )

    def _evaluate_position(
        self,
        pos: VerticalSpreadTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[VerticalSpreadTradeRecord, float]:
        opt_type = "put" if pos.spread_type == "BULL_PUT" else "call"

        short_mark = mark_lookup.get((pos.expiry, opt_type, pos.short_strike), None)
        wing_mark = mark_lookup.get((pos.expiry, opt_type, pos.wing_strike), None)

        if short_mark is None or wing_mark is None:
            # Intrinsic fallback
            if opt_type == "put":
                short_mark = max(0.0, pos.short_strike - spot)
                wing_mark = max(0.0, pos.wing_strike - spot)
            else:
                short_mark = max(0.0, spot - pos.short_strike)
                wing_mark = max(0.0, spot - pos.wing_strike)

        slip = self.config.slippage_bps / 10000.0
        fee = min(spot * 0.0006, max(0.0001, (short_mark - wing_mark) * 0.08))
        exit_cost = (short_mark * (1.0 + slip)) - (wing_mark * (1.0 - slip)) + fee
        dte = (pos.expiry - ts).total_seconds() / 86400.0

        if force_close:
            pnl = (pos.entry_credit - exit_cost) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_cost
            pos.realized_pnl = pnl
            pos.exit_reason = "FORCE_CLOSE"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 1. Expiration
        if dte <= 0.05:
            if exit_cost <= 0.01:
                pnl = pos.entry_credit * pos.qty
                pos.exit_reason = "EXPIRED_OTM"
            else:
                pnl = (pos.entry_credit - exit_cost) * pos.qty
                pos.exit_reason = "EXPIRED_IN_SPREAD"
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_cost
            pos.realized_pnl = pnl
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 2. 50% Take Profit
        if exit_cost <= pos.entry_credit * (1.0 - self.config.target_profit_pct):
            pnl = (pos.entry_credit - exit_cost) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_cost
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_50"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 3. Stop loss
        unrealized = (pos.entry_credit - exit_cost) * pos.qty
        if unrealized < -pos.entry_credit * pos.qty * self.config.max_loss_multiplier:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_cost
            pos.realized_pnl = unrealized
            pos.exit_reason = "STOP_LOSS"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, unrealized

        return pos, 0.0

    def _calc_unrealized(
        self, pos: VerticalSpreadTradeRecord, mark_lookup: dict[tuple[Any, str, float], float]
    ) -> float:
        opt_type = "put" if pos.spread_type == "BULL_PUT" else "call"
        short_mark = mark_lookup.get((pos.expiry, opt_type, pos.short_strike), pos.short_entry_price)
        wing_mark = mark_lookup.get((pos.expiry, opt_type, pos.wing_strike), pos.wing_entry_price)
        current_spread = short_mark - wing_mark
        return (pos.entry_credit - current_spread) * pos.qty

    def _build_results(
        self,
        trades: list[VerticalSpreadTradeRecord],
        equity_curve: list[dict[str, Any]],
        net_pnl: float,
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> VerticalSpreadBacktestResult:
        total = len(trades)
        if total == 0:
            return VerticalSpreadBacktestResult(
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

        return VerticalSpreadBacktestResult(
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
