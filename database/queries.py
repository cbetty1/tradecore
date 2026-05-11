import logging
from database.db import get_connection

logger = logging.getLogger(__name__)


# ── Signals ──────────────────────────────────────────────────────────────────

def insert_signal(ticker, signal_type, direction, confidence, price, regime=None, notes=None):
    """Insert a new signal record."""
    sql = """
        INSERT INTO signals (ticker, signal_type, direction, confidence, price_at_signal, regime, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(sql, (ticker, signal_type, direction, confidence, price, regime, notes))
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to insert signal: {e}")
        raise


def get_recent_signals(limit=50):
    """Fetch the most recent signals."""
    sql = "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?"
    with get_connection() as conn:
        return conn.execute(sql, (limit,)).fetchall()


# ── Trades ───────────────────────────────────────────────────────────────────

def insert_trade(signal_id, ticker, direction, quantity, price, currency="GBP", paper=1, notes=None):
    """Insert a new trade record."""
    total_value = quantity * price
    sql = """
        INSERT INTO trades (signal_id, ticker, direction, quantity, price, total_value, currency, paper, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(sql, (signal_id, ticker, direction, quantity, price, total_value, currency, paper, notes))
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to insert trade: {e}")
        raise


def get_open_trades(paper=1):
    """Fetch all currently open trades."""
    sql = "SELECT * FROM trades WHERE status = 'OPEN' AND paper = ? ORDER BY opened_at DESC"
    with get_connection() as conn:
        return conn.execute(sql, (paper,)).fetchall()


def close_trade(trade_id, pnl):
    """Mark a trade as closed with its final P&L."""
    sql = """
        UPDATE trades SET status = 'CLOSED', closed_at = datetime('now'), pnl = ?
        WHERE id = ?
    """
    try:
        with get_connection() as conn:
            conn.execute(sql, (pnl, trade_id))
    except Exception as e:
        logger.error(f"Failed to close trade: {e}")
        raise


# ── Portfolio Snapshots ───────────────────────────────────────────────────────

def insert_snapshot(snapshot_date, total_value, cash_balance, invested_value, daily_pnl=None, total_pnl=None):
    """Insert a daily portfolio snapshot."""
    sql = """
        INSERT OR REPLACE INTO portfolio_snapshots
        (snapshot_date, total_value, cash_balance, invested_value, daily_pnl, total_pnl)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    try:
        with get_connection() as conn:
            conn.execute(sql, (snapshot_date, total_value, cash_balance, invested_value, daily_pnl, total_pnl))
    except Exception as e:
        logger.error(f"Failed to insert snapshot: {e}")
        raise


def get_snapshots(limit=30):
    """Fetch recent portfolio snapshots for equity curve."""
    sql = "SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT ?"
    with get_connection() as conn:
        return conn.execute(sql, (limit,)).fetchall()