"""
pionex_client.py — All Pionex REST API calls (auth, orders, balances, prices)

Auth: HMAC-SHA256.  The signature message is:
    {path}?{url-encoded sorted query params including key & timestamp}

Docs: https://pionex-doc.gitbook.io/apidocs
"""

import hashlib
import hmac
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from requests.exceptions import ConnectionError, ReadTimeout, HTTPError

import config
from logger import logger

BASE_URL = "https://api.pionex.com"

# Retry settings for transient failures (network errors, 5xx)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 4, 8]   # seconds between attempts


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _timestamp() -> int:
    return int(time.time() * 1000)


def _sign(path: str, params: dict) -> str:
    """
    Return HMAC-SHA256 hex signature.

    Message = path + "?" + url-encoded alphabetically-sorted params
    (params must already include 'key' and 'timestamp', but NOT 'signature').
    """
    query = urlencode(sorted(params.items()))
    message = path + "?" + query
    return hmac.new(
        config.API_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def _auth_params(path: str, extra: Optional[dict] = None) -> dict:
    """Build a complete signed query-param dict for the given path."""
    params: dict = {"key": config.API_KEY, "timestamp": _timestamp()}
    if extra:
        params.update(extra)
    params["signature"] = _sign(path, params)
    return params


# ── Core request dispatcher ───────────────────────────────────────────────────

def _request(
    method: str,
    path: str,
    *,
    query: Optional[dict] = None,
    body: Optional[dict] = None,
    signed: bool = False,
) -> Any:
    """
    Dispatch an HTTP request with optional HMAC signing and retry logic.

    - `query` → always sent as URL query parameters
    - `body`  → sent as JSON request body (POST only)
    - `signed=True` → injects key/timestamp/signature into query params
    """
    params: dict = dict(query or {})
    if signed:
        params = _auth_params(path, params)

    url = BASE_URL + path
    headers: dict = {}
    if body is not None:
        headers["Content-Type"] = "application/json"

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.request(
                method,
                url,
                params=params,
                json=body,
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("result"):
                code = data.get("code", "?")
                msg  = data.get("message", str(data))
                raise RuntimeError(f"Pionex API error [{code}] on {method} {path}: {msg}")

            return data.get("data", data)

        except (ConnectionError, ReadTimeout) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF[attempt]
                logger.warning("Network error (%s), retrying in %ds…", exc, wait)
                time.sleep(wait)
            else:
                logger.error("Request failed after %d attempts: %s", _MAX_RETRIES, exc)

        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status >= 500 and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF[attempt]
                logger.warning("Server error %d, retrying in %ds…", status, wait)
                time.sleep(wait)
                last_exc = exc
            else:
                raise

    raise last_exc


# ── Market data ───────────────────────────────────────────────────────────────

def get_ticker(symbol: str) -> dict:
    """Return latest ticker dict (close, bid, ask, volume, …) for *symbol*."""
    data = _request("GET", "/api/v1/market/tickers", query={"symbol": symbol})
    tickers = data.get("tickers", [])
    if not tickers:
        raise ValueError(f"No ticker data returned for {symbol!r}")
    return tickers[0]


def get_price(symbol: str) -> float:
    """Return current last-traded price for *symbol* as a float."""
    return float(get_ticker(symbol)["close"])


# ── Account ───────────────────────────────────────────────────────────────────

def get_balances() -> dict[str, float]:
    """Return {asset: free_balance} for every non-zero balance in the account."""
    data = _request("GET", "/api/v1/account/balances", signed=True)
    return {
        b["coinType"]: float(b["free"])
        for b in data.get("balances", [])
        if float(b.get("free", 0)) > 0
    }


# ── Orders ────────────────────────────────────────────────────────────────────

def place_order(
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    order_type: str = "LIMIT",
) -> dict:
    """
    Place a single order.  Returns the raw order dict from the API.

    Auth params (key/timestamp/signature) go in the query string.
    The order payload goes in the JSON body — it is NOT part of the signature.
    """
    path = "/api/v1/trade/order"
    json_body = {
        "symbol": symbol,
        "side": side.upper(),       # BUY | SELL
        "type": order_type.upper(),
        "price": str(price),
        "size": str(quantity),
    }
    logger.info(
        "Placing %s %s  price=%.6f  qty=%.6f  symbol=%s",
        order_type, side, price, quantity, symbol,
    )
    return _request("POST", path, body=json_body, signed=True)


def cancel_order(symbol: str, order_id: str) -> dict:
    """Cancel an open order by ID.  Returns the cancelled order dict."""
    logger.info("Cancelling order %s on %s", order_id, symbol)
    return _request(
        "DELETE",
        "/api/v1/trade/order",
        query={"symbol": symbol, "orderId": order_id},
        signed=True,
    )


def get_open_orders(symbol: str) -> list[dict]:
    """Return all open orders for *symbol*."""
    data = _request(
        "GET",
        "/api/v1/trade/openOrders",
        query={"symbol": symbol},
        signed=True,
    )
    return data.get("orders", [])


def get_order(symbol: str, order_id: str) -> dict:
    """Fetch a single order by ID and return its dict."""
    return _request(
        "GET",
        "/api/v1/trade/order",
        query={"symbol": symbol, "orderId": order_id},
        signed=True,
    )
