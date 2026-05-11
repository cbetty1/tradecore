import sqlite3
import logging
import os
from config.settings import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Return a connection to the TradeCore database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allows dict-style row access
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialise_db():
    """Create all tables if they do not already exist."""
    from database.models import CREATE_STATEMENTS
    try:
        with get_connection() as conn:
            for statement in CREATE_STATEMENTS:
                conn.execute(statement)
        logger.info("Database initialised successfully.")
    except Exception as e:
        logger.error(f"Database initialisation failed: {e}")
        raise