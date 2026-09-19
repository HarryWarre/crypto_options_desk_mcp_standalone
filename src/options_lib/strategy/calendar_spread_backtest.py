"""Fast, Vectorized Historical Backtest Engine for Calendar Spread Strategy.

Simulates multi-tenor Calendar Spreads (Sell Near-Term Week 1, Buy Far-Term Week 2 at ATM strike):
1. Pair Matching: Near-Term (4–9 DTE) and Far-Term (11–20 DTE) at common ATM strike.
2. Robust Valuation: Combines empirical orderbook mark prices with Black-Scholes pricing
   fallback for non-downsampled multi-tenor timestamps.
3. Lifecycle Engine:
   - 25% - 30% Take Profit on Net Debit.
   - Stop Loss on sustained spread value decay.
   - Near-term expiration harvest: Captures peak theta decay when Near DTE <= 0.5 day.
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
class CalendarSpreadBacktestConfig:
    """Configuration for Calendar Spread Backtest."""

    initial_capital: float = 10000.0
    min_near_dte: int = 4
    max_near_dte: int = 12
    min_far_dte: int = 16
    max_far_dte: int = 45
    target_profit_pct: float = 0.25   # Take profit at 25% ROI
    max_loss_pct: float = 0.30        # Stop loss at 30% loss
    roll_dte: float = 0.5             # Harvest near-term expiry
    slippage_bps: float = 5.0
    max_concurrent_positions: int = 3
    max_trend_sma_dist: float = 0.02  # Trend consolidation filter (<= 2.0% from SMA20)
    max_spot_drift_pct: float = 0.07  # Early stop if spot drifts >7% from strike
    max_realized_vol: float = 0.55    # Realized vol ceiling to avoid trend breakouts
    dynamic_sizing: bool = True
    risk_pct_per_trade: float = 0.02
    max_margin_utilization: float = 0.60
    asset: str = "BTC"
    fixed_qty: float | None = None


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

    def _price_leg(
        self, option_type: str, spot: float, strike: float, dte: float, iv: float = 0.65
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
        spot_series = pd.Series({ts: grouped[ts][0]["underlying_price"].iloc[0] for ts in timestamps})
        sma20 = spot_series.rolling(20, min_periods=5).mean()
        ret = spot_series.pct_change()
        vol_series = ret.rolling(24, min_periods=5).std() * np.sqrt(365 * 12)

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
            sma_val = sma20.loc[ts]
            dist_from_sma = abs(spot - sma_val) / sma_val if pd.notnull(sma_val) and sma_val > 0 else 0.0
            rv = vol_series.loc[ts] if ts in vol_series.index and pd.notnull(vol_series.loc[ts]) else 0.40

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
                and (dist_from_sma <= self.config.max_trend_sma_dist)
                and (rv <= self.config.max_realized_vol)
            )

            if can_enter:
                candidate = self._find_candidate(chain, ts, spot, capital)
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
    ) -> CalendarSpreadTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0

        calls = chain[chain["option_type"] == "call"]
        if calls.empty:
            return None

        # Week 1 near calls
        near_calls = calls[(calls["dte"] >= self.config.min_near_dte) & (calls["dte"] <= self.config.max_near_dte)]
        # Week 2 far calls
        far_calls = calls[(calls["dte"] >= self.config.min_far_dte) & (calls["dte"] <= self.config.max_far_dte)]

        if near_calls.empty or far_calls.empty:
            return None

        # Common strikes
        near_strikes = set(near_calls["strike"])
        far_strikes = set(far_calls["strike"])
        common = near_strikes.intersection(far_strikes)

        if not common:
            return None

        # ATM strike
        atm_strike = min(common, key=lambda s: abs(s - spot))
        if abs(atm_strike - spot) / spot > 0.025:
            return None

        near_row = near_calls[near_calls["strike"] == atm_strike].iloc[0]
        far_row = far_calls[far_calls["strike"] == atm_strike].iloc[0]

        near_expiry = near_row["expiry"]
        far_expiry = far_row["expiry"]

        slip = self.config.slippage_bps / 10000.0
        near_price = float(near_row["mark_price"]) * (1.0 - slip)  # Sold near-term
        far_price = float(far_row["mark_price"]) * (1.0 + slip)    # Bought far-term

        raw_debit = far_price - near_price
        if raw_debit <= 0:
            return None

        fee = min(spot * 0.0006, max(0.0001, raw_debit * 0.08))
        net_debit = raw_debit + fee

        max_loss_per_unit = max(1.0, net_debit)
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
        near_dte = (pos.near_expiry - ts).total_seconds() / 86400.0
        far_dte = (pos.far_expiry - ts).total_seconds() / 86400.0

        near_mark = mark_lookup.get(
            (pos.near_expiry, pos.option_type, pos.strike),
            self._price_leg(pos.option_type, spot, pos.strike, near_dte),
        )
        far_mark = mark_lookup.get(
            (pos.far_expiry, pos.option_type, pos.strike),
            self._price_leg(pos.option_type, spot, pos.strike, far_dte),
        )

        slip = self.config.slippage_bps / 10000.0
        # Closing value: Sell far leg, Buy back near leg
        current_spread_val = (far_mark * (1.0 - slip)) - (near_mark * (1.0 + slip))
        fee = min(spot * 0.0006, max(0.0001, abs(current_spread_val) * 0.08))
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

        # 1. Near-term expiration harvest: Peak theta captured
        if near_dte <= self.config.roll_dte:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "NEAR_EXPIRY_HARVEST"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 2. 25% Take Profit
        if net_closing_val >= pos.entry_debit * (1.0 + self.config.target_profit_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_25"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 3. Stop loss
        if net_closing_val <= pos.entry_debit * (1.0 - self.config.max_loss_pct):
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "STOP_LOSS"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        # 4. Early spot drift cut (protect against severe directional trend drag)
        if self.config.max_spot_drift_pct > 0 and abs(spot - pos.strike) / pos.strike >= self.config.max_spot_drift_pct:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_credit = net_closing_val
            pos.realized_pnl = pnl
            pos.exit_reason = "SPOT_DRIFT_CUT"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, pnl

        return pos, 0.0

    def _calc_unrealized(
        self,
        pos: CalendarSpreadTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
    ) -> float:
        near_dte = (pos.near_expiry - ts).total_seconds() / 86400.0
        far_dte = (pos.far_expiry - ts).total_seconds() / 86400.0

        near_mark = mark_lookup.get(
            (pos.near_expiry, pos.option_type, pos.strike),
            self._price_leg(pos.option_type, spot, pos.strike, near_dte),
        )
        far_mark = mark_lookup.get(
            (pos.far_expiry, pos.option_type, pos.strike),
            self._price_leg(pos.option_type, spot, pos.strike, far_dte),
        )
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

