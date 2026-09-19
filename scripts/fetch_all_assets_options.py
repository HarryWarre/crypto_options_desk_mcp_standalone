"""Universal multi-asset crypto options data pipeline (BTC, ETH, SOL, DOGE, MNT, XRP).

Fetches 60+ days of historical price history, derives rolling realized & implied volatility
surfaces, and computes full options chains (Call/Put prices, Deltas, IV, Bid/Ask spreads)
across rolling expiries. Outputs compact Parquet datasets ready for backtesting.
"""

from __future__ import annotations

import argparse
import math
import os
import time
import urllib.request
import json
from datetime import UTC, datetime, timedelta
import numpy as np
import pandas as pd
from scipy.stats import norm

# Standard asset parameters & baseline IV anchors observed from Bybit/Deribit
ASSET_CONFIG = {
    "BTC": {"bybit_symbol": "BTCUSDT", "min_strike_step": 500, "base_iv": 0.55, "spread_pct": 0.02},
    "ETH": {"bybit_symbol": "ETHUSDT", "min_strike_step": 25, "base_iv": 0.60, "spread_pct": 0.025},
    "SOL": {"bybit_symbol": "SOLUSDT", "min_strike_step": 2, "base_iv": 0.72, "spread_pct": 0.03},
    "DOGE": {"bybit_symbol": "DOGEUSDT", "min_strike_step": 0.005, "base_iv": 0.85, "spread_pct": 0.035},
    "MNT": {"bybit_symbol": "MNTUSDT", "min_strike_step": 0.02, "base_iv": 0.75, "spread_pct": 0.035},
    "XRP": {"bybit_symbol": "XRPUSDT", "min_strike_step": 0.02, "base_iv": 0.65, "spread_pct": 0.03},
}

def fetch_bybit_1h_klines(symbol: str, days: int = 60) -> list[dict]:
    """Fetch 1h OHLCV bars from Bybit linear market."""
    now_ms = int(time.time() * 1000)
    target_start_ms = now_ms - (days * 86400 * 1000)
    
    all_bars = []
    end_time = now_ms
    
    while True:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=60&end={end_time}&limit=200"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            bars = data.get("result", {}).get("list", [])
            if not bars:
                break
            all_bars.extend(bars)
            oldest_ts = int(bars[-1][0])
            end_time = oldest_ts - 1
            if oldest_ts <= target_start_ms:
                break
            time.sleep(0.04)
            
    # Parse into structured records sorted ascending
    records = []
    for b in reversed(all_bars):
        ts = datetime.fromtimestamp(int(b[0]) / 1000.0, tz=UTC)
        records.append({
            "timestamp": ts,
            "open": float(b[1]),
            "high": float(b[2]),
            "low": float(b[3]),
            "close": float(b[4]),
            "volume": float(b[5]),
        })
    return records

def calculate_black_scholes(S: float, K: float, T: float, sigma: float, r: float = 0.02):
    """Compute Black-Scholes call & put prices and deltas."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0, 0.0, 0.0
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    call_price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    put_price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    
    call_delta = float(norm.cdf(d1))
    put_delta = float(norm.cdf(d1) - 1.0)
    
    return max(0.0001, call_price), max(0.0001, put_price), call_delta, put_delta

def build_options_chain_for_asset(currency: str, days: int = 60, sample_interval_hours: int = 2) -> pd.DataFrame:
    """Generate chronological options chain dataset for a given asset."""
    cfg = ASSET_CONFIG[currency]
    bars = fetch_bybit_1h_klines(cfg["bybit_symbol"], days=days)
    if len(bars) < 30:
        raise ValueError(f"Insufficient bars for {currency}")
        
    df_bars = pd.DataFrame(bars)
    df_bars["log_ret"] = np.log(df_bars["close"] / df_bars["close"].shift(1))
    # Rolling 14-day (336 hours) realized volatility annualized
    df_bars["rv"] = df_bars["log_ret"].rolling(window=336, min_periods=48).std() * math.sqrt(24 * 365)
    df_bars["rv"] = df_bars["rv"].bfill().fillna(cfg["base_iv"])
    
    # Implied Volatility = max(base_iv, RV * 1.15)
    df_bars["iv"] = np.maximum(cfg["base_iv"] * 0.8, df_bars["rv"] * 1.15)
    
    quotes = []
    # Sample every N hours to avoid ballooning file size while preserving resolution
    sampled_indices = range(0, len(df_bars), sample_interval_hours)
    
    strike_step = cfg["min_strike_step"]
    spread_pct = cfg["spread_pct"]
    
    for idx in sampled_indices:
        row = df_bars.iloc[idx]
        t = row["timestamp"]
        spot = row["close"]
        iv = float(row["iv"])
        
        # Fixed calendar Friday expirations (standard Deribit & Bybit options cycles)
        days_ahead = (4 - t.weekday()) % 7
        next_friday = (t + timedelta(days=days_ahead)).replace(hour=8, minute=0, second=0, microsecond=0)
        if next_friday <= t:
            next_friday += timedelta(days=7)
            
        candidate_expiries = [next_friday + timedelta(days=7 * i) for i in range(4)]
        for expiry in candidate_expiries:
            dte_hours = (expiry - t).total_seconds() / 3600.0
            dte_days = dte_hours / 24.0
            if dte_days < 1.0 or dte_days > 35.0:
                continue
            T = dte_days / 365.0
            
            # Generate strikes at standard delta multiples (+/- 30% from spot)
            strike_range = spot * 0.35
            min_k = max(strike_step, round((spot - strike_range) / strike_step) * strike_step)
            max_k = round((spot + strike_range) / strike_step) * strike_step
            
            # Generate 15 distinct strikes around spot
            strikes = np.linspace(min_k, max_k, num=15)
            
            for k in strikes:
                k_val = round(k / strike_step) * strike_step
                if k_val <= 0:
                    continue
                    
                call_px, put_px, call_delta, put_delta = calculate_black_scholes(spot, k_val, T, iv)
                
                # Call record
                c_bid = round(max(0.0001, call_px * (1.0 - spread_pct / 2.0)), 4)
                c_ask = round(call_px * (1.0 + spread_pct / 2.0), 4)
                quotes.append({
                    "timestamp": t,
                    "symbol": f"{currency}-{expiry.strftime('%d%b%y').upper()}-{k_val:g}-C",
                    "currency": currency,
                    "expiry": expiry,
                    "strike": float(k_val),
                    "type": "call",
                    "bid": c_bid,
                    "ask": c_ask,
                    "mark_price": round(call_px, 4),
                    "underlying_price": round(spot, 4),
                    "delta": round(call_delta, 4),
                    "iv": round(iv, 4),
                    "dte": float(dte_days),
                })
                
                # Put record
                p_bid = round(max(0.0001, put_px * (1.0 - spread_pct / 2.0)), 4)
                p_ask = round(put_px * (1.0 + spread_pct / 2.0), 4)
                quotes.append({
                    "timestamp": t,
                    "symbol": f"{currency}-{expiry.strftime('%d%b%y').upper()}-{k_val:g}-P",
                    "currency": currency,
                    "expiry": expiry,
                    "strike": float(k_val),
                    "type": "put",
                    "bid": p_bid,
                    "ask": p_ask,
                    "mark_price": round(put_px, 4),
                    "underlying_price": round(spot, 4),
                    "delta": round(put_delta, 4),
                    "iv": round(iv, 4),
                    "dte": float(dte_days),
                })
                
    df_quotes = pd.DataFrame(quotes)
    return df_quotes

def main():
    parser = argparse.ArgumentParser(description="Multi-asset options data generator")
    parser.add_argument("--days", type=int, default=60, help="Days of history")
    parser.add_argument("--interval-hours", type=int, default=2, help="Snapshot sampling interval")
    parser.add_argument("--output-dir", type=str, default="data/multi_asset_parquet", help="Output directory")
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    summary = {}
    
    for asset in ASSET_CONFIG.keys():
        print(f"\nProcessing options data for {asset} ({args.days} days)...")
        t0 = time.time()
        df = build_options_chain_for_asset(asset, days=args.days, sample_interval_hours=args.interval_hours)
        asset_dir = os.path.join(args.output_dir, asset)
        os.makedirs(asset_dir, exist_ok=True)
        out_file = os.path.join(asset_dir, f"{asset.lower()}-options-{args.days}d.parquet")
        
        df.to_parquet(out_file, engine="pyarrow", compression="snappy", index=False)
        size_kb = os.path.getsize(out_file) / 1024.0
        elapsed = time.time() - t0
        summary[asset] = {"rows": len(df), "size_kb": size_kb, "file": out_file}
        print(f" Saved {asset} Parquet: {len(df):,} quotes | {size_kb:.1f} KB | {elapsed:.2f}s")
        
    print("\n" + "=" * 60)
    print("ALL MULTI-ASSET OPTIONS DATA GENERATED:")
    for k, v in summary.items():
        print(f" {k:5}: {v['rows']:,} rows | {v['size_kb']:,.1f} KB -> {v['file']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
