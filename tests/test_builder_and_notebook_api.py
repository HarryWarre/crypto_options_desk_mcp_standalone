"""Integration tests for Strategy Builder and Trade Notebook API endpoints."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from options_app.api import create_app
from position_monitoring.notebook import TradeNotebookStore
from position_monitoring.smart_monitor import SmartPositionMonitor


class FakeOptionContract:
    def __init__(self, symbol, option_type, strike, expiry, bid=100.0, ask=120.0, mark_price=110.0, mark_iv=0.65, underlying_price=60000.0):
        self.symbol = symbol
        self.option_type = option_type
        self.strike = strike
        self.expiry = expiry
        self.bid = bid
        self.ask = ask
        self.mark_price = mark_price
        self.mark_iv = mark_iv
        self.underlying_price = underlying_price
        self.open_interest = 10.0
        self.volume_24h = 5.0


class FakeUniverse:
    def __init__(self, asset="BTC", spot=60000.0, contracts=None):
        self.spot_prices = {asset: spot}
        self.contracts_by_asset = {asset: tuple(contracts or [])}
        self.valuation_time = datetime.now(UTC)


class FakeMarketAdapter:
    def __init__(self, spot=60000.0):
        self.spot = spot
        exp = datetime.now(UTC) + timedelta(days=14)
        self.contracts = [
            FakeOptionContract("BTC-EXP-55000-P", "put", 55000.0, exp, bid=500.0, ask=550.0, mark_price=525.0),
            FakeOptionContract("BTC-EXP-58000-P", "put", 58000.0, exp, bid=1100.0, ask=1150.0, mark_price=1125.0),
            FakeOptionContract("BTC-EXP-60000-C", "call", 60000.0, exp, bid=1800.0, ask=1900.0, mark_price=1850.0),
            FakeOptionContract("BTC-EXP-65000-C", "call", 65000.0, exp, bid=600.0, ask=650.0, mark_price=625.0),
        ]

    async def load_universe(self, assets=None, valuation_time=None):
        return FakeUniverse("BTC", self.spot, self.contracts)


@pytest.fixture
def test_app():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_nb.sqlite3"
        store = TradeNotebookStore(db_path=db_path)
        monitor = SmartPositionMonitor()
        adapter = FakeMarketAdapter(spot=60000.0)
        app = create_app(
            adapter=adapter,
            notebook_store=store,
            smart_monitor=monitor,
        )
        yield app


@pytest.mark.asyncio
async def test_api_builder_templates(test_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/builder/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert "templates" in data
        assert "iron_condor" in data["templates"]
        assert "bull_call_vertical" in data["templates"]


@pytest.mark.asyncio
async def test_api_options_chain(test_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/options/chain/BTC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset"] == "BTC"
        assert data["spot"] == 60000.0
        assert len(data["contracts"]) == 4
        assert len(data["expiries"]) == 1


@pytest.mark.asyncio
async def test_api_builder_populate(test_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/builder/populate",
            json={"strategy_type": "bull_call_vertical", "asset": "BTC"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_type"] == "bull_call_vertical"
        assert len(data["legs"]) == 2


@pytest.mark.asyncio
async def test_api_builder_evaluate(test_app):
    now = datetime.now(UTC)
    expiry_str = (now + timedelta(days=14)).isoformat()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/builder/evaluate",
            json={
                "strategy_type": "bull_call_vertical",
                "legs": [
                    {
                        "option_type": "call",
                        "strike": 60000.0,
                        "expiry": expiry_str,
                        "iv": 0.65,
                        "spot": 60000.0,
                        "position": 1,
                        "mid_price": 2000.0,
                    },
                    {
                        "option_type": "call",
                        "strike": 65000.0,
                        "expiry": expiry_str,
                        "iv": 0.65,
                        "spot": 60000.0,
                        "position": -1,
                        "mid_price": 800.0,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_type"] == "bull_call_vertical"
        assert data["net_premium"] == 1200.0
        assert data["max_loss"] == -1200.0
        assert data["max_profit"] == 3800.0
        assert "greeks" in data
        assert "payoff_curve" in data


@pytest.mark.asyncio
async def test_api_trade_notebook_crud_and_smart_monitor(test_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Create notebook position
        create_resp = await client.post(
            "/api/v1/notebook/positions",
            json={
                "asset": "BTC",
                "strategy_type": "bull_call_vertical",
                "legs": [
                    {
                        "symbol": "BTC-EXP-60000-C",
                        "option_type": "call",
                        "strike": 60000.0,
                        "position": 1,
                        "quantity": 1,
                        "entry_price": 1850.0,
                        "expiry": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
                    },
                    {
                        "symbol": "BTC-EXP-65000-C",
                        "option_type": "call",
                        "strike": 65000.0,
                        "position": -1,
                        "quantity": 1,
                        "entry_price": 625.0,
                        "expiry": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
                    },
                ],
                "entry_spot": 60000.0,
                "target_profit_pct": 50.0,
                "stop_loss_pct": 50.0,
                "notes": "Scanner signal trade",
                "source": "scanner",
            },
        )
        assert create_resp.status_code == 201
        pos = create_resp.json()["position"]
        pos_id = pos["id"]
        assert pos["status"] == "open"
        assert pos["asset"] == "BTC"

        # 2. List positions
        list_resp = await client.get("/api/v1/notebook/positions")
        assert list_resp.status_code == 200
        positions = list_resp.json()["positions"]
        assert len(positions) == 1

        # 3. Get single position
        get_resp = await client.get(f"/api/v1/notebook/positions/{pos_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["position"]["id"] == pos_id

        # 4. Update position
        put_resp = await client.put(
            f"/api/v1/notebook/positions/{pos_id}",
            json={"notes": "Updated note", "target_profit_pct": 60.0},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["position"]["notes"] == "Updated note"

        # 5. Smart Monitor pass
        mon_resp = await client.get("/api/v1/notebook/monitor")
        assert mon_resp.status_code == 200
        mon_data = mon_resp.json()
        assert "evaluations" in mon_data
        assert len(mon_data["evaluations"]) == 1
        eval_item = mon_data["evaluations"][0]
        assert eval_item["position_id"] == pos_id
        assert eval_item["decision"]["action"] in ["HOLD", "TAKE_PROFIT", "CUT_LOSS", "REVIEW"]
        assert eval_item["decision"]["action_vn"] in ["GIỮ", "CHỐT LỜI", "BỎ / CẮT LỖ", "XEM XÉT"]

        # 6. Close position
        close_resp = await client.post(
            f"/api/v1/notebook/positions/{pos_id}/close",
            json={"exit_spot": 62000.0, "exit_pnl": 500.0, "notes": "Target hit"},
        )
        assert close_resp.status_code == 200
        assert close_resp.json()["position"]["status"] == "closed"

        # 7. Delete position
        del_resp = await client.delete(f"/api/v1/notebook/positions/{pos_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_canonical_option_contracts_chain_and_populate():
    """Verify that canonical OptionContract (expiry_at, bid_price, ask_price, spot_price, Call/Put) works."""
    from bybit_api.options_market_data import OptionContract, NormalizedOptionUniverse, OptionAsset

    now = datetime.now(UTC)
    exp = now + timedelta(days=7)
    contracts = [
        OptionContract(
            asset="SOL",
            symbol="SOL-EXP-110-P-USDT",
            option_type="Put",
            strike=110.0,
            expiry_at=exp,
            expiry_code="EXP",
            spot_price=115.0,
            mark_price=2.5,
            mark_iv=0.60,
            bid_price=2.4,
            ask_price=2.6,
            bid_iv=0.59,
            ask_iv=0.61,
            delta=-0.35,
            gamma=0.04,
            theta=-0.15,
            vega=0.08,
            volume_24h=100.0,
            open_interest=500.0,
            quote_currency="USDT",
            settle_currency="USDT",
            quote_timestamp=now,
        ),
        OptionContract(
            asset="SOL",
            symbol="SOL-EXP-115-C-USDT",
            option_type="Call",
            strike=115.0,
            expiry_at=exp,
            expiry_code="EXP",
            spot_price=115.0,
            mark_price=4.0,
            mark_iv=0.60,
            bid_price=3.8,
            ask_price=4.2,
            bid_iv=0.59,
            ask_iv=0.61,
            delta=0.50,
            gamma=0.05,
            theta=-0.20,
            vega=0.10,
            volume_24h=200.0,
            open_interest=800.0,
            quote_currency="USDT",
            settle_currency="USDT",
            quote_timestamp=now,
        ),
        OptionContract(
            asset="SOL",
            symbol="SOL-EXP-120-C-USDT",
            option_type="Call",
            strike=120.0,
            expiry_at=exp,
            expiry_code="EXP",
            spot_price=115.0,
            mark_price=1.8,
            mark_iv=0.62,
            bid_price=1.7,
            ask_price=1.9,
            bid_iv=0.61,
            ask_iv=0.63,
            delta=0.30,
            gamma=0.04,
            theta=-0.12,
            vega=0.07,
            volume_24h=150.0,
            open_interest=600.0,
            quote_currency="USDT",
            settle_currency="USDT",
            quote_timestamp=now,
        ),
    ]

    class CanonicalMarketAdapter:
        async def load_universe(self, assets=None, valuation_time=None):
            return NormalizedOptionUniverse(
                assets=(OptionAsset(base_coin="SOL", status="ONLINE", contract_count=3),),
                contracts=tuple(contracts),
                issues=(),
                valuation_time=now,
            )

    app = create_app(adapter=CanonicalMarketAdapter())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Test chain endpoint
        chain_resp = await client.get("/api/v1/options/chain/SOL")
        assert chain_resp.status_code == 200
        chain_data = chain_resp.json()
        assert chain_data["asset"] == "SOL"
        assert chain_data["spot"] == 115.0
        assert len(chain_data["contracts"]) == 3
        assert len(chain_data["expiries"]) == 1
        assert chain_data["expiries"][0] == exp.strftime("%Y-%m-%d")
        assert chain_data["contracts"][0]["option_type"] == "put"
        assert chain_data["contracts"][0]["bid"] == 2.4
        assert chain_data["contracts"][0]["ask"] == 2.6

        # Test populate endpoint
        pop_resp = await client.post(
            "/api/v1/builder/populate",
            json={"strategy_type": "bull_call_vertical", "asset": "SOL"},
        )
        assert pop_resp.status_code == 200
        pop_data = pop_resp.json()
        assert pop_data["strategy_type"] == "bull_call_vertical"
        assert pop_data["spot"] == 115.0
        assert len(pop_data["legs"]) == 2
        assert pop_data["legs"][0]["option_type"] == "call"
        assert pop_data["legs"][0]["strike"] == 115.0
        assert pop_data["legs"][1]["strike"] == 120.0

