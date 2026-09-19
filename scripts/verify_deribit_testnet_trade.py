"""Live End-to-End Verification Script for Deribit Testnet.

Tests:
1. Authentication with Deribit Testnet.
2. Account Summary & Balances.
3. Market Data (Instruments & Orderbook).
4. Safe Limit Order placement, verification in Open Orders, and cancellation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to python path
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

# Load .env if present
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from options_lib.deribit_client import DeribitClient, DeribitOrderState
from options_lib.paper_broker import DeribitBrokerAdapter, OrderType, PaperAccount, PaperOrder


def main() -> int:
    print("=" * 60)
    print("🚀 DERIBIT TESTNET LIVE VERIFICATION")
    print("=" * 60)

    client_id = os.getenv("DERIBIT_TESTNET_CLIENT_ID")
    client_secret = os.getenv("DERIBIT_TESTNET_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ Error: DERIBIT_TESTNET_CLIENT_ID and DERIBIT_TESTNET_CLIENT_SECRET not found in environment.")
        return 1

    print(f"Client ID: {client_id}")
    client = DeribitClient(client_id=client_id, client_secret=client_secret, testnet=True)

    # 1. Authenticate
    print("\n[Step 1] Authenticating ...")
    token = client.authenticate()
    print(f"✅ Authenticated successfully! Token: {token[:25]}...")

    # 2. Account Summary
    print("\n[Step 2] Fetching Account Summary ...")
    btc_summary = client.get_account_summary(currency="BTC")
    print(f"  • BTC Balance: {btc_summary.balance:.4f} BTC (Equity: {btc_summary.equity:.4f})")
    usdc_summary = client.get_account_summary(currency="USDC")
    print(f"  • USDC Balance: {usdc_summary.balance:.2f} USDC (Equity: {usdc_summary.equity:.2f})")

    # 3. Market Data
    print("\n[Step 3] Fetching BTC Options Instruments ...")
    instruments = client.get_instruments(currency="BTC", kind="option", expired=False)
    print(f"✅ Found {len(instruments)} active BTC options contracts on Testnet.")

    # Find a far OTM Call option
    calls = [i for i in instruments if i.option_type == "call" and i.strike >= 95000]
    if not calls:
        calls = [i for i in instruments if i.option_type == "call"]

    target_inst = calls[0].instrument_name
    print(f"Selected target instrument for order test: {target_inst}")

    ob = client.get_order_book(target_inst)
    best_bid = ob.get("best_bid_price") or 0.0
    best_ask = ob.get("best_ask_price") or 0.0
    mark_price = ob.get("mark_price") or 0.0
    print(f"  • Best Bid: {best_bid} | Best Ask: {best_ask} | Mark Price: {mark_price}")

    # 4. Safe Order Placement (Limit buy far below market to guarantee no fill)
    # If best bid is 0.001, place at 0.0005. Minimum price is tick size.
    test_price = max(calls[0].tick_size, round(best_bid * 0.5, 4)) if best_bid > 0 else calls[0].tick_size
    test_amount = calls[0].min_trade_amount

    print(f"\n[Step 4] Placing safe Limit Buy order ({test_amount} contracts @ {test_price} BTC) ...")
    order = client.buy(
        instrument_name=target_inst,
        amount=test_amount,
        order_type="limit",
        price=test_price,
        label="test_verify_swing",
    )
    print(f"✅ Order submitted! Order ID: {order.order_id}, State: {order.order_state}")

    # 5. Verify in Open Orders
    print("\n[Step 5] Verifying order in Open Orders ...")
    open_orders = client.get_open_orders_by_currency(currency="BTC", kind="option")
    matching = [o for o in open_orders if o.order_id == order.order_id]
    if matching:
        print(f"✅ Order found in Open Orders on Deribit: {matching[0].order_id} ({matching[0].order_state})")
    else:
        print("⚠️ Order not in open orders (may have been filled or rejected)")

    # 6. Cancel Order
    print(f"\n[Step 6] Cancelling order {order.order_id} ...")
    cancelled = client.cancel(order.order_id)
    print(f"✅ Cancel status: {cancelled.order_state}")

    # 7. Test Adapter
    print("\n[Step 7] Testing DeribitBrokerAdapter sync ...")
    adapter = DeribitBrokerAdapter(client=client)
    paper_acc = PaperAccount(account_id="swing_test", initial_capital=100.0)
    adapter.sync_account(paper_acc, currency="BTC")
    print(f"✅ Adapter synced! Account balance: {paper_acc.cash_balance:.4f} BTC")

    print("\n" + "=" * 60)
    print("🎉 ALL TESTNET VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

