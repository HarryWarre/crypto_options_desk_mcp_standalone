"""Unit tests for Deribit Client and Deribit Broker Adapter."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from options_lib.deribit_client import (
    DeribitAccountSummary,
    DeribitClient,
    DeribitClientError,
    DeribitInstrument,
    DeribitOrder,
    DeribitPosition,
)
from options_lib.paper_broker import (
    DeribitBrokerAdapter,
    OrderType,
    PaperAccount,
    PaperOrder,
)
from options_lib.paper_broker.deribit_adapter import normalize_deribit_instrument


def test_normalize_deribit_instrument():
    assert normalize_deribit_instrument("BTC-26SEP26-80000-C-USDT") == "BTC-26SEP26-80000-C"
    assert normalize_deribit_instrument("ETH-30OCT26-2500-P-USDC") == "ETH-30OCT26-2500-P"
    assert normalize_deribit_instrument("BTC-26SEP26-80000-C") == "BTC-26SEP26-80000-C"


def test_deribit_models_parsing():
    inst_dict = {
        "instrument_name": "BTC-25SEP26-80000-C",
        "kind": "option",
        "base_currency": "BTC",
        "quote_currency": "USD",
        "strike": 80000.0,
        "option_type": "call",
        "expiration_timestamp": 1789800000000,
        "tick_size": 0.0005,
        "min_trade_amount": 0.1,
    }
    inst = DeribitInstrument.from_dict(inst_dict)
    assert inst.instrument_name == "BTC-25SEP26-80000-C"
    assert inst.strike == 80000.0
    assert inst.option_type == "call"

    order_dict = {
        "order_id": "ETH-12345",
        "instrument_name": "ETH-25SEP26-2600-P",
        "direction": "buy",
        "order_type": "limit",
        "order_state": "filled",
        "amount": 1.5,
        "filled_amount": 1.5,
        "price": 0.05,
        "average_price": 0.05,
        "fee": 0.0002,
    }
    order = DeribitOrder.from_dict(order_dict)
    assert order.is_filled
    assert order.amount == 1.5
    assert order.direction == "buy"

    pos_dict = {
        "instrument_name": "BTC-25SEP26-70000-P",
        "kind": "option",
        "size": -0.5,
        "average_price": 0.02,
        "mark_price": 0.015,
        "floating_profit_loss": 0.0025,
        "delta": -0.15,
    }
    pos = DeribitPosition.from_dict(pos_dict)
    assert pos.direction == "sell"
    assert pos.size == 0.5
    assert pos.floating_profit_loss == 0.0025


@patch("urllib.request.urlopen")
def test_deribit_client_auth(mock_urlopen):
    # Mock auth response
    auth_resp = {
        "jsonrpc": "2.0",
        "result": {
            "access_token": "mock_token_12345",
            "refresh_token": "mock_refresh_token",
            "expires_in": 900,
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(auth_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    client = DeribitClient(client_id="test_id", client_secret="test_secret", testnet=True)
    token = client.authenticate()
    assert token == "mock_token_12345"
    assert client.is_authenticated


@patch("urllib.request.urlopen")
def test_deribit_client_error(mock_urlopen):
    err_resp = {
        "jsonrpc": "2.0",
        "error": {
            "code": 10004,
            "message": "invalid_credentials",
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(err_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    client = DeribitClient(client_id="bad_id", client_secret="bad_secret")
    with pytest.raises(DeribitClientError) as exc_info:
        client.authenticate(force=True)
    assert exc_info.value.code == 10004


def test_deribit_broker_adapter():
    mock_client = MagicMock(spec=DeribitClient)
    adapter = DeribitBrokerAdapter(client=mock_client)

    # Test Buy Order
    mock_client.buy.return_value = DeribitOrder(
        order_id="der_buy_01",
        instrument_name="BTC-25SEP26-85000-C",
        direction="buy",
        order_type="limit",
        order_state="filled",
        amount=0.5,
        filled_amount=0.5,
        price=0.03,
        average_price=0.03,
        fee=0.0001,
    )

    order = PaperOrder(
        symbol="BTC-25SEP26-85000-C-USDT",
        side="Buy",
        qty=0.5,
        price=0.03,
        order_type=OrderType.LIMIT,
        strategy_id="ic_test",
    )

    result = adapter.execute_order(order)
    assert result.is_filled
    assert result.order_id == "der_buy_01"
    assert result.filled_qty == 0.5
    assert result.filled_price == 0.03
    mock_client.buy.assert_called_once_with(
        instrument_name="BTC-25SEP26-85000-C",
        amount=0.5,
        order_type="limit",
        price=0.03,
        label="ic_test",
    )

    # Test Account Sync
    mock_client.get_account_summary.return_value = DeribitAccountSummary(
        currency="BTC",
        equity=102.5,
        balance=100.0,
        margin_balance=100.0,
        initial_margin=2.5,
        maintenance_margin=1.5,
    )
    mock_client.get_positions.return_value = [
        DeribitPosition(
            instrument_name="BTC-25SEP26-85000-C",
            kind="option",
            direction="buy",
            size=0.5,
            average_price=0.03,
            mark_price=0.035,
            floating_profit_loss=0.0025,
        )
    ]

    paper_acc = PaperAccount(account_id="test_acc", initial_capital=100.0)
    adapter.sync_account(paper_acc, currency="BTC")

    assert paper_acc.cash_balance == 100.0
    assert len(paper_acc.positions) == 1
    assert "BTC-25SEP26-85000-C" in paper_acc.positions
    assert paper_acc.positions["BTC-25SEP26-85000-C"].unrealized_pnl == 0.0025

