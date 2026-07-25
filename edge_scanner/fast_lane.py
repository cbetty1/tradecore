import json
import logging
from datetime import datetime, timedelta
from database.db import get_connection
from notifications.telegram import send_message

logger = logging.getLogger(__name__)

WATCHLIST_PATH = "config/watchlist.json"
MIN_SCORE = 60.0
TEMP_TTL_HOURS = 72

T212_TICKERS_PATH = "config/t212_tickers.json"

def load_t212_tickers():
    with open(T212_TICKERS_PATH) as f:
        data = json.load(f)
        return data.get("ticker_map", data)


def load_watchlist():
    with open(WATCHLIST_PATH) as f:
        return json.load(f)


def save_watchlist(data):
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_todays_top_scorers() -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT ticker, score, price_change_pct, rsi
            FROM edge_scanner_results
            WHERE scanned_at >= ?
              AND score >= ?
              AND price_change_pct >= 5.0
              AND (rsi IS NULL OR rsi < 65)
            ORDER BY score DESC, price_change_pct DESC
        """, (today, MIN_SCORE)).fetchall()
    return [{"ticker": r[0], "score": r[1], "price_change_pct": r[2], "rsi": r[3]} for r in rows]


def cleanup_expired_temp_entries():
    data = load_watchlist()
    cutoff = (datetime.now() - timedelta(hours=TEMP_TTL_HOURS)).isoformat()
    before = len(data["watchlist"])
    data["watchlist"] = [
        s for s in data["watchlist"]
        if not (s.get("temp") and s.get("added_at", "") < cutoff)
    ]
    removed = before - len(data["watchlist"])
    if removed > 0:
        save_watchlist(data)
        logger.info(f"Fast lane cleanup — removed {removed} expired temp entries")


def run_fast_lane():
    logger.info("=== FAST LANE STARTING ===")
    cleanup_expired_temp_entries()
    scorers = get_todays_top_scorers()
    if not scorers:
        logger.info("Fast lane — no scorers above threshold today")
        return
    data = load_watchlist()
    existing_tickers = {s["ticker"] for s in data["watchlist"]}
    t212_tickers = load_t212_tickers()
    added = []
    for s in scorers:
        ticker = s["ticker"]
        if ticker in existing_tickers:
            logger.info(f"Fast lane — {ticker} already in watchlist, skipping")
            continue
        if ticker not in t212_tickers:
            logger.warning(f"Fast lane — {ticker} skipped, no T212 ticker mapping")
            continue
        entry = {
            "ticker": ticker,
            "name": ticker,
            "exchange": "NASDAQ",
            "currency": "USD",
            "source": "EdgeScanner",
            "temp": True,
            "added_at": datetime.now().isoformat()
        }
        data["watchlist"].append(entry)
        existing_tickers.add(ticker)
        added.append(s)
        logger.info(f"Fast lane — added {ticker} (score={s['score']}, +{s['price_change_pct']:.1f}%)")
    if added:
        save_watchlist(data)
        lines = ["⚡ FAST LANE ACTIVATED"]
        for s in added:
            lines.append(f"📡 {s['ticker']} — score {s['score']} | +{s['price_change_pct']:.1f}% today | RSI {s['rsi']:.0f}")
        lines.append("Stocks added to watchlist — watching for buy signal")
        send_message("\n".join(lines))
        logger.info(f"Fast lane — {len(added)} stocks added to watchlist")
    else:
        logger.info("Fast lane — all scorers already in watchlist")
    logger.info("=== FAST LANE COMPLETE ===")


def run_morning_fast_lane():
    """07:30 job — add last night's top scorers for today's US open."""
    logger.info("=== MORNING FAST LANE STARTING ===")
    cleanup_expired_temp_entries()
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT ticker, score, price_change_pct, rsi
            FROM edge_scanner_results
            WHERE scanned_at >= ?
              AND scanned_at < ?
              AND score >= ?
              AND price_change_pct > 0
            ORDER BY score DESC
        """, (yesterday, today, MIN_SCORE)).fetchall()
    scorers = [{"ticker": r[0], "score": r[1], "price_change_pct": r[2], "rsi": r[3]} for r in rows]
    if not scorers:
        logger.info("Morning fast lane — no qualifying scorers from last night")
        return
    data = load_watchlist()
    existing_tickers = {s["ticker"] for s in data["watchlist"]}
    t212_tickers = load_t212_tickers()
    added = []
    for s in scorers:
        ticker = s["ticker"]
        if ticker in existing_tickers:
            continue
        if ticker not in t212_tickers:
            logger.warning(f"Morning fast lane — {ticker} skipped, no T212 ticker mapping")
            continue
        entry = {
            "ticker": ticker,
            "name": ticker,
            "exchange": "NASDAQ",
            "currency": "USD",
            "source": "EdgeScanner",
            "temp": True,
            "added_at": datetime.now().isoformat()
        }
        data["watchlist"].append(entry)
        existing_tickers.add(ticker)
        added.append(s)
        logger.info(f"Morning fast lane — added {ticker} (score={s['score']}, +{s['price_change_pct']:.1f}%)")
    if added:
        save_watchlist(data)
        lines = ["🌅 MORNING FAST LANE"]
        for s in added:
            lines.append(f"📡 {s['ticker']} — score {s['score']} | +{s['price_change_pct']:.1f}% yesterday | RSI {s['rsi']:.0f}")
        lines.append("Ready for US open at 14:30")
        send_message("\n".join(lines))
        logger.info(f"Morning fast lane — {len(added)} stocks added")
    logger.info("=== MORNING FAST LANE COMPLETE ===")