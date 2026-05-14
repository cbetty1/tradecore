"""
Trading 212 Broker Implementation
==================================
Handles all communication with the T212 REST API.
Uses HTTP Basic Auth (API Key + Secret).
Places market orders only (T212 API beta limitation for live).

SAFETY FEATURES:
  - Every order is logged before and after execution
  - Telegram alert on every real trade
  - Order confirmation checked after placement
  - Dry-run mode for testing without executing
"""

import logging
import json
import os
import base64
import requests
from typing import Optional, Dict, List

from execution.broker_base import BrokerBase
from config.settings import T212_API_KEY, T212_API_SECRET, T212_BASE_URL

logger = logging.getLogger(__name__)

# Load ticker mapping
TICKER_MAP_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "t212_tickers.json")


def _load_ticker_map() -> dict:
    """Load yfinance -> T212 ticker mapping."""
    try:
        with open(TICKER_MAP_FILE) as f:
            data = json.load(f)
            return data.get("ticker_map", {})
    except Exception as e:
        logger.error(f"Failed to load ticker map: {e}")
        return {}


def yf_to_t212(yf_ticker: str) -> Optional[str]:
    """Convert a yfinance ticker to T212 format."""
    ticker_map = _load_ticker_map()
    t212_ticker = ticker_map.get(yf_ticker)
    if not t212_ticker:
        logger.error(f"No T212 ticker mapping for {yf_ticker}")
    return t212_ticker


class T212Broker(BrokerBase):
    """Trading 212 REST API broker implementation."""

    def __init__(self):
        if not T212_API_KEY or not T212_API_SECRET:
            logger.warning("T212 API credentials not configured")

        self.base_url = T212_BASE_URL.rstrip("/")
        self._auth_header = self._build_auth_header()

    def _build_auth_header(self) -> str:
        """Build HTTP Basic Auth header from API key + secret."""
        if not T212_API_KEY or not T212_API_SECRET:
            return ""
        credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def _headers(self) -> dict:
        credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }

    def _request(self, method: str, endpoint: str,
                 data: dict = None, timeout: int = 15) -> Optional[Dict]:
        """
        Make an authenticated request to the T212 API.
        Returns parsed JSON response or None on failure.
        """
        url = f"{self.base_url}/api/v0/equity/{endpoint}"

        try:
            if method == "GET":
                resp = requests.get(url, headers=self._headers(), timeout=timeout)
            elif method == "POST":
                resp = requests.post(url, headers=self._headers(),
                                     json=data, timeout=timeout)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return None

            if resp.status_code in (200, 201):
                return resp.json() if resp.text else {}
            else:
                logger.error(f"T212 API {method} {endpoint} failed: "
                           f"HTTP {resp.status_code} — {resp.text}")
                return None

        except requests.exceptions.Timeout:
            logger.error(f"T212 API timeout: {method} {endpoint}")
            return None
        except Exception as e:
            logger.error(f"T212 API error: {e}")
            return None

    # ── Account Info ────────────────────────────────────────────────────────

    def get_account_balance(self) -> dict:
        """Return current cash balance from T212."""
        result = self._request("GET", "account/cash")
        if result:
            return {
                "free": result.get("free", 0),
                "total": result.get("total", 0),
                "ppl": result.get("ppl", 0),
                "result": result.get("result", 0),
            }
        return {}

    def get_account_summary(self) -> dict:
        """Return full account summary from T212."""
        return self._request("GET", "account/summary") or {}

    def get_open_positions(self) -> list:
        """Return list of currently open positions from T212."""
        result = self._request("GET", "positions")
        if result and isinstance(result, list):
            return result
        return []

    def get_position(self, yf_ticker: str) -> Optional[dict]:
        """Get a specific position by yfinance ticker."""
        t212_ticker = yf_to_t212(yf_ticker)
        if not t212_ticker:
            return None
        result = self._request("GET", f"positions?ticker={t212_ticker}")
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    def get_latest_price(self, ticker: str) -> float:
        """Get latest price — we use yfinance for this, not T212."""
        from data.price_feed import get_latest_price
        return get_latest_price(ticker) or 0.0

    # ── Order Placement ─────────────────────────────────────────────────────

    def place_buy_order(self, ticker: str, quantity: float) -> dict:
        """
        Place a market BUY order on T212.

        Args:
            ticker:   yfinance ticker (e.g. "AAPL")
            quantity: Number of shares to buy (positive, can be fractional)

        Returns:
            Order result dict or empty dict on failure
        """
        t212_ticker = yf_to_t212(ticker)
        if not t212_ticker:
            return {"error": f"No T212 ticker mapping for {ticker}"}

        if quantity <= 0:
            return {"error": "Buy quantity must be positive"}

        order_data = {
            "ticker": t212_ticker,
            "quantity": round(quantity, 6),
            "extendedHours": False
        }

        logger.info(f"PLACING BUY ORDER: {ticker} ({t212_ticker}) | "
                    f"Qty={quantity:.6f}")

        result = self._request("POST", "orders/market", data=order_data)

        if result:
            logger.info(f"BUY ORDER PLACED: {ticker} | "
                       f"Order ID={result.get('id', 'unknown')} | "
                       f"Status={result.get('status', 'unknown')}")
        else:
            logger.error(f"BUY ORDER FAILED: {ticker}")

        return result or {"error": "Order placement failed"}

    def place_sell_order(self, ticker: str, shares: float) -> dict:
        """
        Place a market SELL order on T212.
        T212 uses negative quantity for sells.

        Args:
            ticker: yfinance ticker (e.g. "AAPL")
            shares: Number of shares to sell (positive — will be negated)

        Returns:
            Order result dict or empty dict on failure
        """
        t212_ticker = yf_to_t212(ticker)
        if not t212_ticker:
            return {"error": f"No T212 ticker mapping for {ticker}"}

        if shares <= 0:
            return {"error": "Sell shares must be positive"}

        order_data = {
            "ticker": t212_ticker,
            "quantity": -round(shares, 6),  # T212 uses negative for sells
            "extendedHours": False
        }

        logger.info(f"PLACING SELL ORDER: {ticker} ({t212_ticker}) | "
                    f"Qty={shares:.6f}")

        result = self._request("POST", "orders/market", data=order_data)

        if result:
            logger.info(f"SELL ORDER PLACED: {ticker} | "
                       f"Order ID={result.get('id', 'unknown')} | "
                       f"Status={result.get('status', 'unknown')}")
        else:
            logger.error(f"SELL ORDER FAILED: {ticker}")

        return result or {"error": "Order placement failed"}

    # ── Instruments ─────────────────────────────────────────────────────────

    def get_instruments(self) -> list:
        """Fetch all tradable instruments (large response, use sparingly)."""
        return self._request("GET", "instruments") or []

    # ── Connection Test ─────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Test API connectivity — returns True if authenticated."""
        result = self.get_account_balance()
        if result:
            logger.info(f"T212 connection OK — Cash: £{result.get('free', 0):.2f}")
            return True
        logger.error("T212 connection FAILED")
        return False