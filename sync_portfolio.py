"""
TradeCore — T212 Portfolio Sync
================================
Rebuilds portfolio_state.json from actual T212 live positions.
Run this any time the state file gets out of sync with reality.

Usage:
    cd /opt/tradecore/tradecore
    /opt/tradecore/venv/bin/python3 sync_portfolio.py
"""

import json
import os
import logging
from datetime import datetime
from execution.t212_broker import T212Broker, yf_to_t212
from data.price_feed import get_latest_price
from database.queries import get_open_trades

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(__file__), "portfolio_state.json")

# Reverse map — T212 ticker back to yfinance ticker
def _build_reverse_map() -> dict:
    """Build a reverse map from T212 ticker -> yfinance ticker."""
    try:
        map_file = os.path.join(os.path.dirname(__file__), "config", "t212_tickers.json")
        with open(map_file) as f:
            data = json.load(f)
            ticker_map = data.get("ticker_map", {})
            return {v: k for k, v in ticker_map.items()}
    except Exception as e:
        logger.error(f"Failed to load ticker map: {e}")
        return {}


def load_current_state() -> dict:
    """Load existing portfolio state."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "cash": 0.0,
        "starting_capital": 300.0,
        "positions": {},
        "last_updated": str(datetime.now())
    }


def sync_from_t212():
    """
    Pull live positions from T212 and rebuild portfolio_state.json.
    Preserves cash, starting_capital, and trade_ids where possible.
    """
    broker = T212Broker()

    # Test connection first
    if not broker.test_connection():
        logger.error("Cannot connect to T212 — aborting sync")
        return

    # Get live positions from T212
    t212_positions = broker.get_open_positions()
    if not t212_positions:
        logger.warning("No open positions returned from T212 — check API")
        return

    logger.info(f"T212 returned {len(t212_positions)} open positions")

    # Get account cash
    balance = broker.get_account_balance()
    cash = balance.get("free", 0.0)
    logger.info(f"T212 cash: £{cash:.2f}")

    # Build reverse ticker map
    reverse_map = _build_reverse_map()

    # Load current state to preserve starting_capital and trade_ids
    current_state = load_current_state()
    starting_capital = current_state.get("starting_capital", 300.0)
    existing_positions = current_state.get("positions", {})

    # Get open trades from database to match trade_ids
    try:
        open_trades = get_open_trades()
        trade_id_map = {t["ticker"]: t["id"] for t in open_trades}
    except Exception as e:
        logger.warning(f"Could not load trade IDs from DB: {e}")
        trade_id_map = {}

    # Rebuild positions from T212 data
    new_positions = {}
    for pos in t212_positions:
        t212_ticker = pos.get("ticker", "")
        yf_ticker = reverse_map.get(t212_ticker)

        if not yf_ticker:
            logger.warning(f"No yfinance mapping for T212 ticker: {t212_ticker} — skipping")
            continue

        quantity = float(pos.get("quantity", 0))
        avg_price = float(pos.get("averagePrice", 0))
        current_price = get_latest_price(yf_ticker) or avg_price
        invested = quantity * avg_price

        # Preserve existing highest_price if we already had this position
        existing = existing_positions.get(yf_ticker, {})
        highest_price = existing.get("highest_price", avg_price)
        if current_price > highest_price:
            highest_price = current_price

        # Get trade_id from DB or existing state
        trade_id = trade_id_map.get(yf_ticker) or existing.get("trade_id", 0)

        new_positions[yf_ticker] = {
            "shares": round(quantity, 6),
            "entry_price": round(avg_price, 4),
            "highest_price": round(highest_price, 4),
            "trade_id": trade_id,
            "invested": round(invested, 2)
        }

        pnl = (current_price - avg_price) * quantity
        pnl_pct = ((current_price - avg_price) / avg_price) * 100
        logger.info(f"  {yf_ticker}: {quantity:.4f} shares @ £{avg_price:.2f} | "
                   f"Current £{current_price:.2f} | P&L: £{pnl:.2f} ({pnl_pct:+.1f}%)")

    # Build new state
    new_state = {
        "cash": round(cash, 2),
        "starting_capital": starting_capital,
        "positions": new_positions,
        "last_updated": str(datetime.now())
    }

    # Calculate portfolio value
    portfolio_value = cash + sum(
        pos["shares"] * (get_latest_price(ticker) or pos["entry_price"])
        for ticker, pos in new_positions.items()
    )

    # Save
    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, indent=2)

    logger.info(f"")
    logger.info(f"=== SYNC COMPLETE ===")
    logger.info(f"Positions synced: {len(new_positions)}")
    logger.info(f"Cash: £{cash:.2f}")
    logger.info(f"Portfolio value: £{portfolio_value:.2f}")
    logger.info(f"State saved to {STATE_FILE}")
    logger.info(f"")

    # Print summary
    print("\n" + "=" * 50)
    print("  T212 Portfolio Sync Complete")
    print("=" * 50)
    print(f"  Positions: {len(new_positions)}")
    for ticker, pos in new_positions.items():
        current_price = get_latest_price(ticker) or pos["entry_price"]
        pnl = (current_price - pos["entry_price"]) * pos["shares"]
        print(f"  {ticker:<8} {pos['shares']:.4f} shares | "
              f"Entry £{pos['entry_price']:.2f} | "
              f"P&L £{pnl:+.2f}")
    print(f"  Cash: £{cash:.2f}")
    print(f"  Portfolio: £{portfolio_value:.2f}")
    print("=" * 50)


if __name__ == "__main__":
    sync_from_t212()