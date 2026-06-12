import logging
from datetime import datetime, timedelta
import yfinance as yf
from database.db import get_connection

logger = logging.getLogger(__name__)

CHECK_DAYS = [3, 7, 14]


def run_outcome_tracker():
    """For each checkpoint (3/7/14 days), find signals from that many days ago
    and record how the price moved since the signal."""
    logger.info("EdgeScanner outcome tracker running...")
    results_written = 0

    with get_connection() as conn:
        for days in CHECK_DAYS:
            target_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            # Find signals from ~that date (any time that day)
            rows = conn.execute("""
                SELECT ticker, score, price, scanned_at
                FROM edge_scanner_results
                WHERE DATE(scanned_at) = ?
            """, (target_date,)).fetchall()

            for ticker, score, signal_price, scanned_at in rows:
                # Skip if already tracked for this checkpoint
                existing = conn.execute("""
                    SELECT id FROM edge_scanner_outcomes
                    WHERE ticker = ? AND signal_date = ? AND days_elapsed = ?
                """, (ticker, target_date, days)).fetchone()
                if existing:
                    continue

                # Fetch current price
                try:
                    current_price = yf.Ticker(ticker).fast_info.last_price
                    if not current_price or current_price <= 0:
                        continue
                except Exception as e:
                    logger.warning(f"Price fetch failed for {ticker}: {e}")
                    continue

                pct_change = ((current_price - signal_price) / signal_price) * 100

                conn.execute("""
                    INSERT OR IGNORE INTO edge_scanner_outcomes
                    (ticker, signal_date, signal_score, signal_price, outcome_price,
                     pct_change, days_elapsed, checked_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker, target_date, score, signal_price,
                    round(current_price, 4), round(pct_change, 2),
                    days, datetime.now().isoformat()
                ))
                results_written += 1

        conn.commit()

    logger.info(f"Outcome tracker complete — {results_written} new records written")
    return results_written


def get_weekly_summary():
    """Returns a formatted string summarising outcome performance for Telegram."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT days_elapsed,
                   COUNT(*) as total,
                   ROUND(AVG(pct_change), 2) as avg_pct,
                   SUM(CASE WHEN pct_change > 0 THEN 1 ELSE 0 END) as winners
            FROM edge_scanner_outcomes
            GROUP BY days_elapsed
            ORDER BY days_elapsed
        """).fetchall()

        # Top 5 performers overall
        top = conn.execute("""
            SELECT ticker, signal_date, signal_score, pct_change, days_elapsed
            FROM edge_scanner_outcomes
            ORDER BY pct_change DESC
            LIMIT 5
        """).fetchall()

    if not rows:
        return "📊 EdgeScanner Outcomes: No data yet."

    lines = ["📊 *EdgeScanner Outcome Tracker*\n"]
    for days, total, avg_pct, winners in rows:
        win_rate = round((winners / total) * 100) if total > 0 else 0
        lines.append(f"*{days}d checkpoint:* {total} signals | {win_rate}% winners | avg {avg_pct:+.1f}%")

    if top:
        lines.append("\n🏆 *Top performers:*")
        for ticker, sig_date, score, pct, days in top:
            lines.append(f"  {ticker} — score {score} → {pct:+.1f}% over {days}d (signal: {sig_date})")

    return "\n".join(lines)