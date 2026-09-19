"""Fast, Vectorized Historical Backtest Engine for The Wheel Strategy.

Simulates the complete lifecycle across historical Parquet options snapshots:
- Phase 1 (Cash-Secured Put): Sells OTM Puts (Delta ~ 0.15 - 0.25).
- Phase 2 (Assignment): Converts to Spot holding if underlying expires below strike.
- Phase 3 (Covered Call): Sells OTM Calls (Delta ~ 0.15 - 0.25) satisfying Strike >= Cost Basis.
- Phase 4 (Called Away): Realizes spot gain when underlying expires above strike, returning to Cash.

Computes: Total Trades, Win Rate, Net PnL, Profit Factor, Sharpe Ratio, Max Drawdown,
and benchmark comparison vs Buy & Hold.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class WheelBacktestConfig:
    """Configuration for The Wheel Strategy Backtest."""

    initial_capital: float = 10000.0
    target_put_delta: float = 0.20
    target_call_delta: float = 0.20
    min_dte: int = 5
    max_dte: int = 21
    target_profit_pct: float = 0.50  # Take profit at 50% max credit
    max_loss_multiplier: float = 1.5  # Stop loss on option premium
    roll_dte: float = 1.0  # Evaluate / roll when DTE <= 1
    slippage_bps: float = 5.0
    fee_per_contract: float = 1.5
    max_concurrent_positions: int = 2


@dataclass
class WheelTradeRecord:
    """Represents an individual option trade leg in The Wheel strategy."""

    trade_id: str
    phase: str  # "CSP" or "CC"
    symbol: str
    entry_time: datetime
    exit_time: datetime | None
    expiry: datetime
    dte_at_entry: float
    strike: float
    spot_entry: float
    spot_exit: float | None
    entry_credit: float
    qty: float
    exit_debit: float | None = None
    realized_pnl: float = 0.0
    exit_reason: str = "OPEN"
    holding_hours: float = 0.0


@dataclass
class WheelBacktestResult:
    """Summary statistics from The Wheel backtest run."""

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
    buy_and_hold_pnl: float
    buy_and_hold_return_pct: float
    total_return_pct: float
    trades: list[WheelTradeRecord] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def summary_table(self) -> dict[str, Any]:
        return {
            "Total Trades": self.total_trades,
            "Winning Trades": self.winning_trades,
            "Losing Trades": self.losing_trades,
            "Win Rate": f"{self.win_rate_pct:.1f}%",
            "Total Net PnL": f"${self.total_net_pnl:,.2f} ({self.total_return_pct:+.1f}%)",
            "Profit Factor": f"{self.profit_factor:.2f}",
            "Max Drawdown": f"${self.max_drawdown_usd:,.2f} ({self.max_drawdown_pct:.1f}%)",
            "Sharpe Ratio": f"{self.sharpe_ratio:.2f}",
            "Buy & Hold PnL": f"${self.buy_and_hold_pnl:,.2f} ({self.buy_and_hold_return_pct:+.1f}%)",
            "Expectancy / Trade": f"${self.expectancy_per_trade:.2f}",
        }


class WheelBacktestEngine:
    """Vectorized / Chunked Replay Engine for The Wheel."""

    def __init__(self, config: WheelBacktestConfig | None = None):
        self.config = config or WheelBacktestConfig()

    def run(self, df: pd.DataFrame) -> WheelBacktestResult:
        if df.empty:
            return WheelBacktestResult(
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
                buy_and_hold_pnl=0.0,
                buy_and_hold_return_pct=0.0,
                total_return_pct=0.0,
            )

        df = df.copy()
        if "option_type" not in df.columns and "type" in df.columns:
            df["option_type"] = df["type"].astype(str).str.lower()
        elif "option_type" in df.columns:
            df["option_type"] = df["option_type"].astype(str).str.lower()

        # Map 'c' -> 'call', 'p' -> 'put'
        df["option_type"] = df["option_type"].replace({"c": "call", "p": "put"})

        # Group and index by timestamp for fast O(1) mark lookup
        grouped: dict[Any, tuple[pd.DataFrame, dict[tuple[Any, str, float], float]]] = {}
        for ts, group in df.groupby("timestamp"):
            mark_lookup = {}
            for _, row in group.iterrows():
                mark_lookup[(row["expiry"], row["option_type"], row["strike"])] = float(row["mark_price"])
            grouped[ts] = (group, mark_lookup)

        timestamps = sorted(grouped.keys())
        first_spot = float(grouped[timestamps[0]][0]["underlying_price"].iloc[0])
        last_spot = float(grouped[timestamps[-1]][0]["underlying_price"].iloc[0])

        capital = self.config.initial_capital
        cash = capital
        spot_holdings = 0.0
        acquisition_price = 0.0
        cost_basis = 0.0  # Effective cost basis after option premiums

        peak_equity = capital
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        open_positions: list[WheelTradeRecord] = []
        closed_trades: list[WheelTradeRecord] = []
        equity_curve: list[dict[str, Any]] = []
        last_entry_time: datetime | None = None

        phase = "CSP"  # Starts in Cash-Secured Put phase

        for ts in timestamps:
            chain, mark_lookup = grouped[ts]
            if chain.empty:
                continue

            spot = float(chain["underlying_price"].iloc[0])

            # 1. Manage active open positions
            remaining_positions: list[WheelTradeRecord] = []
            for pos in open_positions:
                eval_pos, exit_type, realized_pnl = self._evaluate_position(
                    pos, mark_lookup, ts, spot
                )

                if eval_pos.exit_time is not None:
                    # Trade closed
                    closed_trades.append(eval_pos)

                    if eval_pos.phase == "CSP":
                        if exit_type == "ASSIGNED":
                            # Assigned spot at strike price
                            cost = eval_pos.strike * eval_pos.qty
                            cash -= cost
                            cash += (eval_pos.entry_credit * eval_pos.qty)  # collect premium
                            spot_holdings += eval_pos.qty
                            acquisition_price = eval_pos.strike
                            cost_basis = eval_pos.strike - eval_pos.entry_credit
                            phase = "CC"
                        else:
                            # TP or Expired OTM or Stop loss
                            cash += realized_pnl
                    else:  # Covered Call
                        if exit_type == "CALLED_AWAY":
                            # Spot sold at call strike price
                            proceeds = eval_pos.strike * eval_pos.qty
                            cash += proceeds
                            spot_pnl = (eval_pos.strike - acquisition_price) * eval_pos.qty
                            cash += (eval_pos.entry_credit * eval_pos.qty)  # option premium
                            spot_holdings = max(0.0, spot_holdings - eval_pos.qty)
                            phase = "CSP"
                        else:
                            cash += realized_pnl
                else:
                    remaining_positions.append(eval_pos)

            open_positions = remaining_positions

            # 2. Open new position if eligible
            can_enter = (
                len(open_positions) < self.config.max_concurrent_positions
                and (last_entry_time is None or (ts - last_entry_time).total_seconds() >= 6 * 3600)
            )

            if can_enter:
                candidate = self._find_candidate(
                    chain, ts, spot, phase, spot_holdings, cost_basis, cash
                )
                if candidate is not None:
                    open_positions.append(candidate)
                    last_entry_time = ts

            # 3. Calculate current total equity
            unrealized_options = sum(
                self._calc_unrealized(p, mark_lookup) for p in open_positions
            )
            spot_value = spot_holdings * spot
            current_equity = cash + spot_value + unrealized_options

            equity_curve.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "equity": current_equity,
                "cash": cash,
                "spot_value": spot_value,
                "unrealized_options": unrealized_options,
                "phase": phase,
            })

            if current_equity > peak_equity:
                peak_equity = current_equity
            dd = peak_equity - current_equity
            dd_pct = (dd / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_dd_usd:
                max_dd_usd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Close any lingering positions at end of backtest
        if open_positions:
            last_ts = timestamps[-1]
            _, last_lookup = grouped[last_ts]
            for pos in open_positions:
                pos, _, pnl = self._evaluate_position(pos, last_lookup, last_ts, last_spot, force_close=True)
                cash += pnl
                closed_trades.append(pos)
            open_positions.clear()

        # Final equity includes liquidated spot at last spot price
        final_equity = cash + spot_holdings * last_spot
        total_net_pnl = final_equity - self.config.initial_capital

        buy_and_hold_pnl = (last_spot - first_spot) / first_spot * self.config.initial_capital
        buy_and_hold_ret = (last_spot - first_spot) / first_spot * 100.0
        total_ret = (total_net_pnl / self.config.initial_capital) * 100.0

        return self._build_results(
            closed_trades,
            equity_curve,
            total_net_pnl,
            total_ret,
            buy_and_hold_pnl,
            buy_and_hold_ret,
            max_dd_usd,
            max_dd_pct,
        )

    def _find_candidate(
        self,
        chain: pd.DataFrame,
        ts: datetime,
        spot: float,
        phase: str,
        spot_holdings: float,
        cost_basis: float,
        cash: float,
    ) -> WheelTradeRecord | None:
        chain = chain.copy()
        chain["dte"] = (chain["expiry"] - chain["timestamp"]).dt.total_seconds() / 86400.0
        valid = chain[(chain["dte"] >= self.config.min_dte) & (chain["dte"] <= self.config.max_dte)]
        if valid.empty:
            return None

        # Pick nearest expiry
        expiries = sorted(valid["expiry"].unique())
        target_expiry = expiries[0]
        sub = valid[valid["expiry"] == target_expiry]

        if phase == "CSP":
            # Search OTM Puts
            puts = sub[(sub["option_type"] == "put") & (sub["strike"] < spot)].copy()
            if puts.empty:
                return None

            puts["delta_diff"] = (puts["delta"].abs() - self.config.target_put_delta).abs()
            puts = puts.sort_values("delta_diff")
            best = puts.iloc[0]

            mark = float(best["mark_price"])
            strike = float(best["strike"])
            dte = float(best["dte"])

            if mark <= 0 or strike <= 0:
                return None

            # Slippage & fees
            slip = mark * (self.config.slippage_bps / 10000.0)
            entry_credit = max(0.01, mark - slip)

            # Sizing: fixed notional allocation per position based on initial capital
            notional_per_pos = self.config.initial_capital / max(1, self.config.max_concurrent_positions)
            qty = max(0.001, round(notional_per_pos / max(0.0001, strike), 4))

            return WheelTradeRecord(
                trade_id=f"csp_{len(sub)}_{int(strike)}",
                phase="CSP",
                symbol=str(best["symbol"]),
                entry_time=ts,
                exit_time=None,
                expiry=target_expiry,
                dte_at_entry=dte,
                strike=strike,
                spot_entry=spot,
                spot_exit=None,
                entry_credit=entry_credit,
                qty=qty,
            )
        else:
            # Search OTM Calls satisfying Cost-Basis Floor
            floor = max(cost_basis * 0.98, spot)
            calls = sub[(sub["option_type"] == "call") & (sub["strike"] >= floor)].copy()
            if calls.empty:
                calls = sub[(sub["option_type"] == "call") & (sub["strike"] > spot)].copy()
            if calls.empty:
                return None

            calls["delta_diff"] = (calls["delta"].abs() - self.config.target_call_delta).abs()
            calls = calls.sort_values("delta_diff")
            best = calls.iloc[0]

            mark = float(best["mark_price"])
            strike = float(best["strike"])
            dte = float(best["dte"])

            if mark <= 0:
                return None

            slip = mark * (self.config.slippage_bps / 10000.0)
            entry_credit = max(0.01, mark - slip)

            notional_per_pos = self.config.initial_capital / max(1, self.config.max_concurrent_positions)
            qty = spot_holdings if spot_holdings > 0 else max(0.001, round(notional_per_pos / max(0.0001, strike), 4))

            return WheelTradeRecord(
                trade_id=f"cc_{len(sub)}_{int(strike)}",
                phase="CC",
                symbol=str(best["symbol"]),
                entry_time=ts,
                exit_time=None,
                expiry=target_expiry,
                dte_at_entry=dte,
                strike=strike,
                spot_entry=spot,
                spot_exit=None,
                entry_credit=entry_credit,
                qty=qty,
            )

    def _evaluate_position(
        self,
        pos: WheelTradeRecord,
        mark_lookup: dict[tuple[Any, str, float], float],
        ts: datetime,
        spot: float,
        force_close: bool = False,
    ) -> tuple[WheelTradeRecord, str, float]:
        opt_type = "put" if pos.phase == "CSP" else "call"
        key = (pos.expiry, opt_type, pos.strike)
        current_mark = mark_lookup.get(key, None)

        if current_mark is None:
            # Intrinsic value fallback if missing from book
            if opt_type == "put":
                current_mark = max(0.0, pos.strike - spot)
            else:
                current_mark = max(0.0, spot - pos.strike)

        entry_credit = pos.entry_credit
        slip = current_mark * (self.config.slippage_bps / 10000.0)
        exit_debit = current_mark + slip + (self.config.fee_per_contract / max(0.01, pos.qty))

        dte = (pos.expiry - ts).total_seconds() / 86400.0

        if force_close:
            pnl = (entry_credit - exit_debit) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_debit
            pos.realized_pnl = pnl
            pos.exit_reason = "FORCE_CLOSE"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, "FORCE_CLOSE", pnl

        # 1. Take Profit at 50% max credit
        if current_mark <= entry_credit * (1.0 - self.config.target_profit_pct):
            pnl = (entry_credit - exit_debit) * pos.qty
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_debit
            pos.realized_pnl = pnl
            pos.exit_reason = "TP_50"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, "TP_50", pnl

        # 2. Expiration handling
        if dte <= 0.05:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0

            if pos.phase == "CSP":
                if spot < pos.strike:
                    # Assigned!
                    pos.exit_reason = "ASSIGNED"
                    pos.exit_debit = 0.0
                    pos.realized_pnl = entry_credit * pos.qty  # Kept premium
                    return pos, "ASSIGNED", pos.realized_pnl
                else:
                    # Expired OTM: 100% win
                    pos.exit_reason = "EXPIRED_OTM"
                    pos.exit_debit = 0.0
                    pos.realized_pnl = entry_credit * pos.qty
                    return pos, "EXPIRED_OTM", pos.realized_pnl
            else:  # CC
                if spot > pos.strike:
                    # Called away!
                    pos.exit_reason = "CALLED_AWAY"
                    pos.exit_debit = 0.0
                    pos.realized_pnl = entry_credit * pos.qty
                    return pos, "CALLED_AWAY", pos.realized_pnl
                else:
                    # Expired OTM: Kept spot + premium
                    pos.exit_reason = "EXPIRED_OTM"
                    pos.exit_debit = 0.0
                    pos.realized_pnl = entry_credit * pos.qty
                    return pos, "EXPIRED_OTM", pos.realized_pnl

        # 3. Stop loss rule
        unrealized = (entry_credit - exit_debit) * pos.qty
        if unrealized < -entry_credit * pos.qty * self.config.max_loss_multiplier:
            pos.exit_time = ts
            pos.spot_exit = spot
            pos.exit_debit = exit_debit
            pos.realized_pnl = unrealized
            pos.exit_reason = "STOP_LOSS"
            pos.holding_hours = (ts - pos.entry_time).total_seconds() / 3600.0
            return pos, "STOP_LOSS", unrealized

        return pos, "HOLD", 0.0

    def _calc_unrealized(
        self, pos: WheelTradeRecord, mark_lookup: dict[tuple[Any, str, float], float]
    ) -> float:
        opt_type = "put" if pos.phase == "CSP" else "call"
        mark = mark_lookup.get((pos.expiry, opt_type, pos.strike), pos.entry_credit)
        return (pos.entry_credit - mark) * pos.qty

    def _build_results(
        self,
        trades: list[WheelTradeRecord],
        equity_curve: list[dict[str, Any]],
        net_pnl: float,
        total_ret: float,
        bh_pnl: float,
        bh_ret: float,
        max_dd_usd: float,
        max_dd_pct: float,
    ) -> WheelBacktestResult:
        total = len(trades)
        if total == 0:
            return WheelBacktestResult(
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
                buy_and_hold_pnl=0.0,
                buy_and_hold_return_pct=0.0,
                total_return_pct=0.0,
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
        expectancy = mean_pnl

        return WheelBacktestResult(
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            win_rate_pct=win_rate,
            total_net_pnl=net_pnl,
            profit_factor=pf,
            max_drawdown_usd=max_dd_usd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            expectancy_per_trade=expectancy,
            buy_and_hold_pnl=bh_pnl,
            buy_and_hold_return_pct=bh_ret,
            total_return_pct=total_ret,
            trades=trades,
            equity_curve=equity_curve,
        )
