"""
EdgeScanner Auto-Promoter
=========================
Nightly: checks edge_scanner_outcomes for qualifying stocks and promotes
         them to the live watchlist (config/watchlist.json).
Sunday:  reviews previously promoted stocks and demotes underperformers.

Promotion criteria:
  - Minimum 3 signals in last 14 days
  - Minimum 66% win rate on those signals (2 of 3)
  - Minimum +15% return since first signal
  - Not already on live watchlist
  - Live watchlist under hard cap (60 stocks)

Demotion criteria (Sunday review):
  - No signals fired in last 14 days
  - OR win rate below 40% over last 5 signals
  - Never demote if stock has an open live position
"""

import json
import logging
import os
from datetime import datetime, timedelta

from database.db import get_connection

logger = logging.getLogger(__name__)

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "watchlist.json")
WATCHLIST_CAP = 60

# Promotion thresholds
MIN_SIGNALS = 3
MIN_WIN_RATE = 0.66
MIN_RETURN_PCT = 15.0
LOOKBACK_DAYS = 14

# Demotion thresholds
DEMOTION_NO_SIGNAL_DAYS = 14
DEMOTION_MIN_WIN_RATE = 0.40
DEMOTION_SIGNAL_LOOKBACK = 5


def _load_watchlist() -> list:
    with open(WATCHLIST_FILE) as f:
        return json.load(f)["watchlist"]


def _save_watchlist(watchlist: list):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump({"watchlist": watchlist}, f, indent=2)


def _get_live_tickers() -> set:
    return {s["ticker"] for s in _load_watchlist()}


def _get_open_position_tickers() -> set:
    """Return tickers with currently open live positions."""
    try:
        from execution.order_manager import load_portfolio_state
        state = load_portfolio_state()
        return set(state.get("positions", {}).keys())
    except Exception as e:
        logger.warning(f"Could not load portfolio state: {e}")
        return set()


def _get_promotion_candidates() -> list:
    """
    Query edge_scanner_outcomes for stocks meeting promotion criteria.
    Returns list of dicts with ticker + supporting stats.
    """
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    candidates = []

    try:
        with get_connection() as conn:
            # Get all tickers with signals in the lookback window
            tickers = conn.execute(
                """SELECT DISTINCT ticker FROM edge_scanner_outcomes
                   WHERE signal_date >= ?""",
                (cutoff,)
            ).fetchall()

            for row in tickers:
                ticker = row["ticker"]

                # Get all outcomes in window
                outcomes = conn.execute(
                    """SELECT pct_change, signal_price FROM edge_scanner_outcomes
                       WHERE ticker = ? AND signal_date >= ?
                       ORDER BY signal_date ASC""",
                    (ticker, cutoff)
                ).fetchall()

                if len(outcomes) < MIN_SIGNALS:
                    continue

                # Win rate check
                wins = sum(1 for o in outcomes if o["pct_change"] and o["pct_change"] > 0)
                win_rate = wins / len(outcomes)
                if win_rate < MIN_WIN_RATE:
                    continue

                # Return since first signal
                first_price = outcomes[0]["signal_price"]
                latest_outcome = conn.execute(
                    """SELECT outcome_price FROM edge_scanner_outcomes
                       WHERE ticker = ? AND outcome_price IS NOT NULL
                       ORDER BY signal_date DESC LIMIT 1""",
                    (ticker,)
                ).fetchone()

                if not latest_outcome or not latest_outcome["outcome_price"] or not first_price:
                    continue

                total_return = ((latest_outcome["outcome_price"] - first_price) / first_price) * 100
                if total_return < MIN_RETURN_PCT:
                    continue

                candidates.append({
                    "ticker": ticker,
                    "signals": len(outcomes),
                    "win_rate": round(win_rate * 100, 1),
                    "total_return": round(total_return, 1)
                })

    except Exception as e:
        logger.error(f"Promotion candidate query failed: {e}")

    return candidates


def run_promotion_check():
    """
    Nightly promotion check — called after edge scan at 20:52.
    Promotes qualifying stocks to live watchlist.
    """
    logger.info("=== EDGESCANNER PROMOTION CHECK ===")

    watchlist = _load_watchlist()
    live_tickers = {s["ticker"] for s in watchlist}

    if len(watchlist) >= WATCHLIST_CAP:
        logger.info(f"Watchlist at cap ({WATCHLIST_CAP}) — no promotions possible")
        return

    candidates = _get_promotion_candidates()
    promoted = []

    for c in candidates:
        ticker = c["ticker"]

        if ticker in live_tickers:
            continue

        if len(watchlist) >= WATCHLIST_CAP:
            logger.info(f"Watchlist cap reached ({WATCHLIST_CAP}) — stopping promotions")
            break

        # Promote
        watchlist.append({"ticker": ticker, "name": ticker, "source": "EdgeScanner"})
        live_tickers.add(ticker)
        promoted.append(c)
        logger.info(
            f"PROMOTED: {ticker} | Signals={c['signals']} | "
            f"WinRate={c['win_rate']}% | Return={c['total_return']}%"
        )

    if promoted:
        _save_watchlist(watchlist)
        from notifications.telegram import send_promotion_alert
        send_promotion_alert(promoted)
    else:
        logger.info("Promotion check complete — no new promotions")


def run_demotion_review():
    """
    Sunday demotion review — removes underperforming promoted stocks.
    Never demotes stocks with open live positions.
    """
    logger.info("=== EDGESCANNER DEMOTION REVIEW ===")

    watchlist = _load_watchlist()
    open_positions = _get_open_position_tickers()
    cutoff_no_signal = (datetime.now() - timedelta(days=DEMOTION_NO_SIGNAL_DAYS)).strftime("%Y-%m-%d")
    demoted = []
    new_watchlist = []

    for stock in watchlist:
        ticker = stock["ticker"]

        # Only review EdgeScanner-promoted stocks
        if stock.get("source") != "EdgeScanner":
            new_watchlist.append(stock)
            continue

        # Never demote if position is open
        if ticker in open_positions:
            logger.info(f"Skipping demotion check for {ticker} — open position")
            new_watchlist.append(stock)
            continue

        try:
            with get_connection() as conn:
                # Check for recent signals
                recent = conn.execute(
                    """SELECT COUNT(*) as count FROM edge_scanner_outcomes
                       WHERE ticker = ? AND signal_date >= ?""",
                    (ticker, cutoff_no_signal)
                ).fetchone()["count"]

                if recent == 0:
                    demoted.append({"ticker": ticker, "reason": "No signals in 14 days"})
                    logger.info(f"DEMOTED: {ticker} — no signals in 14 days")
                    continue

                # Check win rate on last N signals
                last_signals = conn.execute(
                    """SELECT pct_change FROM edge_scanner_outcomes
                       WHERE ticker = ? AND pct_change IS NOT NULL
                       ORDER BY signal_date DESC LIMIT ?""",
                    (ticker, DEMOTION_SIGNAL_LOOKBACK)
                ).fetchall()

                if len(last_signals) >= DEMOTION_SIGNAL_LOOKBACK:
                    wins = sum(1 for r in last_signals if r["pct_change"] > 0)
                    win_rate = wins / len(last_signals)
                    if win_rate < DEMOTION_MIN_WIN_RATE:
                        reason = f"Win rate {win_rate*100:.0f}% below 40% threshold"
                        demoted.append({"ticker": ticker, "reason": reason})
                        logger.info(f"DEMOTED: {ticker} — {reason}")
                        continue

        except Exception as e:
            logger.error(f"Demotion check failed for {ticker}: {e}")

        new_watchlist.append(stock)

    if demoted:
        _save_watchlist(new_watchlist)
        from notifications.telegram import send_demotion_alert
        send_demotion_alert(demoted)
    else:
        logger.info("Demotion review complete — no demotions")