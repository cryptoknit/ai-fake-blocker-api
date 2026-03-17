"""
pionex_client.py — All Pionex REST API calls (auth, orders, balances, prices)

Pionex uses HMAC-SHA256 request signing.
Docs: https://pionex-doc.gitbook.io/apidocs
"""

import hashlib
import hmac
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests

import config
from logger import logger

BASE_URL = "https://api.pionex.com"


def _sign(params: dict, secret: str) -> str:
    """Return HMAC-SHA256 hex signature for the given query-string params."""
    query = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _timestamp() -> int:
    return int(time.time() * 1000)


def _request(method: str, path: str, params: Optional[dict] = None,
             body: Optional[dict] = None, signed: bool = False) -> Any:
    params = params or {}
    if signed:
        params["timestamp"] = _timestamp()
        params["signature"] = _sign(params, config.API_SECRET)

    url = BASE_URL + path
    headers = {"PIONEX-KEY": config.API_KEY}

    resp = requests.request(
        method, url,
        params=params if method == "GET" else None,
        json=body if method != "GET" else None,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("result"):
        raise RuntimeError(f"Pionex API error on {path}: {data}")

    return data.get("data", data)


# ── Market data ───────────────────────────────────────────────────────────────

def get_ticker(symbol: str) -> dict:
    """Return latest ticker for *symbol* (last price, bid, ask, volume)."""
    data = _request("GET", "/api/v1/market/tickers", params={"symbol": symbol})
    tickers = data.get("tickers", [])
    if not tickers:
        raise ValueError(f"No ticker data returned for {symbol}")
    return tickers[0]


def get_price(symbol: str) -> float:
    """Return current last-traded price for *symbol*."""
    ticker = get_ticker(symbol)
    return float(ticker["close"])


# ── Account ───────────────────────────────────────────────────────────────────

def get_balances() -> dict[str, float]:
    """Return a mapping of asset → free balance."""
    data = _request("GET", "/api/v1/account/balances", signed=True)
    return {b["coinType"]: float(b["free"]) for b in data.get("balances", [])}


# ── Orders ────────────────────────────────────────────────────────────────────

def place_order(symbol: str, side: str, price: float,
                quantity: float, order_type: str = "LIMIT") -> dict:
    """Place a single order.  Returns the raw order dict from the API."""
    body = {
        "symbol": symbol,
        "side": side.upper(),        # BUY or SELL
        "type": order_type.upper(),
        "price": str(price),
        "size": str(quantity),
        "timestamp": _timestamp(),
    }
    body["signature"] = _sign(body, config.API_SECRET)
    logger.info("Placing %s %s order: price=%s qty=%s", side, order_type, price, quantity)
    return _request("POST", "/api/v1/trade/order", body=body, signed=False)


def cancel_order(symbol: str, order_id: str) -> dict:
    """Cancel an open order by ID."""
    params = {"symbol": symbol, "orderId": order_id}
    logger.info("Cancelling order %s on %s", order_id, symbol)
    return _request("DELETE", "/api/v1/trade/order", params=params, signed=True)


def get_open_orders(symbol: str) -> list[dict]:
    """Return all open orders for *symbol*."""
    data = _request("GET", "/api/v1/trade/openOrders",
                    params={"symbol": symbol}, signed=True)
    return data.get("orders", [])


def get_order(symbol: str, order_id: str) -> dict:
    """Fetch a single order by ID."""
    data = _request("GET", "/api/v1/trade/order",
                    params={"symbol": symbol, "orderId": order_id}, signed=True)
    return data
