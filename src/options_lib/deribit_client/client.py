"""Deribit JSON-RPC 2.0 REST Client for Options and Futures."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from .models import (
    DeribitAccountSummary,
    DeribitInstrument,
    DeribitOrder,
    DeribitOrderType,
    DeribitPosition,
)

logger = logging.getLogger(__name__)


class DeribitClientError(Exception):
    """Raised when Deribit API returns an error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"Deribit API Error [{code}]: {message} (data={data})")
        self.code = code
        self.message = message
        self.data = data


class DeribitClient:
    """Client for Deribit JSON-RPC 2.0 API.

    Supports Testnet and Mainnet with automatic token refresh,
    options order execution, ticker streaming, and position tracking.
    """

    TESTNET_URL = "https://test.deribit.com/api/v2"
    MAINNET_URL = "https://www.deribit.com/api/v2"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        testnet: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self.testnet = testnet
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.timeout = timeout

        if not os.getenv("DERIBIT_TESTNET_CLIENT_ID"):
            from pathlib import Path
            env_path = Path(__file__).resolve().parents[3] / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())

        self.client_id = client_id or os.getenv("DERIBIT_TESTNET_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("DERIBIT_TESTNET_CLIENT_SECRET", "")

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry_timestamp: float = 0.0

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None and time.time() < (self._token_expiry_timestamp - 30)

    def authenticate(self, force: bool = False) -> str:
        """Authenticate using client credentials and obtain an access token."""
        if not force and self.is_authenticated and self._access_token:
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Deribit client_id and client_secret must be provided or set in environment variables."
            )

        params = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        resp = self._raw_request("public/auth", params=params, is_post=False)
        result = resp.get("result", {})

        self._access_token = result.get("access_token")
        self._refresh_token = result.get("refresh_token")
        expires_in = float(result.get("expires_in", 900))
        self._token_expiry_timestamp = time.time() + expires_in

        logger.info("Deribit authenticated successfully. Token expires in %ds.", expires_in)
        return self._access_token or ""

    def _raw_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        is_post: bool = False,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute raw HTTP request against Deribit API v2."""
        headers = headers or {}
        req_params = params or {}

        if is_post:
            url = f"{self.base_url}/{endpoint}"
            body_bytes = json.dumps(req_params).encode("utf-8")
            headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
        else:
            query_str = urllib.parse.urlencode(req_params)
            url = f"{self.base_url}/{endpoint}"
            if query_str:
                url = f"{url}?{query_str}"
            req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                err_info = err_json.get("error", {})
                raise DeribitClientError(
                    code=err_info.get("code", e.code),
                    message=err_info.get("message", e.reason),
                    data=err_info.get("data"),
                ) from e
            except json.JSONDecodeError:
                raise DeribitClientError(code=e.code, message=err_body) from e

        if "error" in data:
            err = data["error"]
            raise DeribitClientError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )

        return data

    def _call(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        private: bool = False,
        is_post: bool = False,
    ) -> Any:
        """Call a Deribit API method with auto-authentication for private calls."""
        headers: dict[str, str] = {}
        if private:
            token = self.authenticate()
            headers["Authorization"] = f"Bearer {token}"

        data = self._raw_request(endpoint, params=params, is_post=is_post, headers=headers)
        return data.get("result")

    # --- Market Data Endpoints ------------------------------------------------

    def get_instruments(
        self,
        currency: str = "BTC",
        kind: str = "option",
        expired: bool = False,
    ) -> list[DeribitInstrument]:
        """Fetch all active instruments for a given currency and kind."""
        res = self._call(
            "public/get_instruments",
            params={"currency": currency.upper(), "kind": kind.lower(), "expired": str(expired).lower()},
        )
        return [DeribitInstrument.from_dict(item) for item in (res or [])]

    def get_ticker(self, instrument_name: str) -> dict[str, Any]:
        """Get live ticker data for an instrument."""
        return self._call("public/ticker", params={"instrument_name": instrument_name})

    def get_book_summary_by_currency(
        self,
        currency: str = "BTC",
        kind: str = "option",
    ) -> list[dict[str, Any]]:
        """Fetch real-time book summary for all contracts of a currency in a single call."""
        res = self._call(
            "public/get_book_summary_by_currency",
            params={"currency": currency.upper(), "kind": kind.lower()},
        )
        return res or []

    def get_order_book(self, instrument_name: str, depth: int = 5) -> dict[str, Any]:
        """Get live orderbook depth with mark price and Greeks."""
        return self._call(
            "public/get_order_book",
            params={"instrument_name": instrument_name, "depth": depth},
        )

    # --- Trading Endpoints ----------------------------------------------------

    def buy(
        self,
        instrument_name: str,
        amount: float,
        order_type: str = "market",
        price: float | None = None,
        label: str = "",
        time_in_force: str = "good_til_cancelled",
    ) -> DeribitOrder:
        """Submit a buy order."""
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type.lower(),
            "time_in_force": time_in_force,
        }
        if price is not None and order_type.lower() == DeribitOrderType.LIMIT.value:
            params["price"] = price
        if label:
            params["label"] = label

        res = self._call("private/buy", params=params, private=True)
        order_dict = res.get("order", res)
        return DeribitOrder.from_dict(order_dict)

    def sell(
        self,
        instrument_name: str,
        amount: float,
        order_type: str = "market",
        price: float | None = None,
        label: str = "",
        time_in_force: str = "good_til_cancelled",
    ) -> DeribitOrder:
        """Submit a sell order."""
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type.lower(),
            "time_in_force": time_in_force,
        }
        if price is not None and order_type.lower() == DeribitOrderType.LIMIT.value:
            params["price"] = price
        if label:
            params["label"] = label

        res = self._call("private/sell", params=params, private=True)
        order_dict = res.get("order", res)
        return DeribitOrder.from_dict(order_dict)

    def cancel(self, order_id: str) -> DeribitOrder:
        """Cancel an open order by ID."""
        res = self._call("private/cancel", params={"order_id": order_id}, private=True)
        return DeribitOrder.from_dict(res)

    def cancel_all(
        self,
        currency: str | None = None,
        kind: str | None = None,
    ) -> int:
        """Cancel all open orders."""
        params: dict[str, Any] = {}
        if currency:
            params["currency"] = currency.upper()
        if kind:
            params["kind"] = kind.lower()
        res = self._call("private/cancel_all", params=params, private=True)
        return int(res or 0)

    def get_order_state(self, order_id: str) -> DeribitOrder:
        """Retrieve state and fills of a specific order."""
        res = self._call("private/get_order_state", params={"order_id": order_id}, private=True)
        return DeribitOrder.from_dict(res)

    def get_open_orders_by_currency(
        self,
        currency: str = "BTC",
        kind: str = "option",
    ) -> list[DeribitOrder]:
        """Fetch all currently active open orders."""
        res = self._call(
            "private/get_open_orders_by_currency",
            params={"currency": currency.upper(), "kind": kind.lower()},
            private=True,
        )
        return [DeribitOrder.from_dict(item) for item in (res or [])]

    # --- Account & Position Endpoints -----------------------------------------

    def get_positions(
        self,
        currency: str = "BTC",
        kind: str = "option",
    ) -> list[DeribitPosition]:
        """Retrieve all active open positions for a currency."""
        res = self._call(
            "private/get_positions",
            params={"currency": currency.upper(), "kind": kind.lower()},
            private=True,
        )
        return [DeribitPosition.from_dict(item) for item in (res or [])]

    def get_account_summary(self, currency: str = "BTC") -> DeribitAccountSummary:
        """Retrieve equity, margin balance and portfolio summary."""
        res = self._call(
            "private/get_account_summary",
            params={"currency": currency.upper()},
            private=True,
        )
        return DeribitAccountSummary.from_dict(res)

