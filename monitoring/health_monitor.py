"""
TradeCore Health Monitor
========================
Silent background health checks every 15 minutes.
Alerts via Telegram (⚙️ prefix) only when something is wrong.
Daily digest at 21:00 summarising the day's health.

Checks:
  - Data freshness (yfinance stale price detection)
  - T212 API connectivity
  - Scheduler heartbeat (did jobs fire on time?)
  - Database health (read/write + file size)
  - Memory / CPU usage
  - Process uptime
  - Kill switch status
  - T212 position sync (daily at 07:00 — catches state drift)
"""

import logging
import os
import time
import sqlite3
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config.settings import DB_PATH, T212_API_KEY

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
STALE_PRICE_MINUTES = 30        # Alert if price data older than this during market hours
DB_MAX_SIZE_MB = 500            # Alert if database exceeds this size
MEMORY_WARN_PCT = 85            # Alert if memory usage above this %
MISSED_JOB_MINUTES = 10         # Alert if a scheduled job is more than this late
CASH_DRIFT_THRESHOLD = 5.0      # Alert if cash differs by more than this amount

# ── State tracking ──────────────────────────────────────────────────────────
_start_time = time.time()
_job_last_run: Dict[str, datetime] = {}
_alerts_today: List[Dict] = []
_alert_cooldowns: Dict[str, datetime] = {}
COOLDOWN_MINUTES = 30           # Don't repeat same alert within this window


def record_job_run(job_name: str):
    """Call this from scheduler jobs so the monitor knows they fired."""
    _job_last_run[job_name] = datetime.now()


def _in_market_hours() -> bool:
    """Check if we're currently in London market hours."""
    now = datetime.now()
    hour, minute = now.hour, now.minute
    return (8 <= hour < 16) or (hour == 16 and minute <= 30)


def _should_alert(alert_key: str) -> bool:
    """Check cooldown — don't spam the same alert."""
    now = datetime.now()
    last = _alert_cooldowns.get(alert_key)
    if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
        return False
    _alert_cooldowns[alert_key] = now
    return True


def _send_health_alert(title: str, details: str, severity: str = "WARNING"):
    """Send a health alert via Telegram with ⚙️ prefix."""
    from notifications.telegram import send_message

    emoji = "⚙️" if severity == "WARNING" else "🚨"
    message = (
        f"{emoji} <b>TRADECORE HEALTH ALERT</b>\n"
        f"\n"
        f"<b>{title}</b>\n"
        f"{details}\n"
        f"\n"
        f"<i>{datetime.now().strftime('%H:%M:%S')} — {severity}</i>"
    )

    _alerts_today.append({
        "time": datetime.now().strftime("%H:%M"),
        "title": title,
        "severity": severity
    })

    try:
        send_message(message)
        logger.info(f"Health alert sent: {title}")
    except Exception as e:
        logger.error(f"Failed to send health alert: {e}")


def check_data_freshness() -> Dict:
    """Check if yfinance is returning price data at all."""
    result = {"status": "OK", "details": ""}

    if not _in_market_hours():
        result["details"] = "Outside market hours — skipped"
        return result

    try:
        from data.price_feed import get_latest_price

        price = get_latest_price("AAPL")

        if price is None or price <= 0:
            result["status"] = "FAIL"
            result["details"] = "get_latest_price returned None for AAPL"
            if _should_alert("stale_data"):
                _send_health_alert(
                    "Price Feed Down",
                    "Cannot fetch live price for AAPL.\n"
                    "Trades may execute on stale data.",
                    severity="CRITICAL"
                )
        else:
            result["details"] = f"AAPL = £{price:.2f}"

    except Exception as e:
        result["status"] = "FAIL"
        result["details"] = str(e)
        if _should_alert("stale_data"):
            _send_health_alert(
                "Price Feed Error",
                f"yfinance check failed: {e}",
                severity="CRITICAL"
            )

    return result


def check_t212_api() -> Dict:
    """Ping the Trading 212 API to confirm connectivity."""
    result = {"status": "OK", "details": ""}

    if not T212_API_KEY:
        result["status"] = "SKIP"
        result["details"] = "No T212 API key configured"
        return result

    try:
        from execution.t212_broker import T212Broker
        broker = T212Broker()
        if broker.test_connection():
            result["details"] = "Connected"
        else:
            result["status"] = "FAIL"
            result["details"] = "Authentication failed"
            if _should_alert("t212_auth"):
                _send_health_alert(
                    "T212 API Auth Failed",
                    "Cannot connect to Trading 212.\n"
                    "Check API key and secret.",
                    severity="CRITICAL"
                )

    except Exception as e:
        result["status"] = "FAIL"
        result["details"] = str(e)
        if _should_alert("t212_api"):
            _send_health_alert(
                "T212 API Error",
                f"Connection failed: {e}",
                severity="CRITICAL"
            )

    return result


def check_t212_sync() -> Dict:
    """
    Compare TradeCore portfolio state against actual T212 positions.
    Runs daily at 07:00 before the pre-market scan.
    Alerts if positions or cash diverge — never auto-fixes, always alerts.

    Divergence thresholds:
      - Ticker in state but not in T212
      - Ticker in T212 but not in state
      - Share quantity differs by more than 0.01
      - Cash differs by more than £5
    """
    result = {"status": "OK", "details": ""}

    try:
        from execution.t212_broker import T212Broker
        from execution.order_manager import load_portfolio_state

        broker = T212Broker()
        state = load_portfolio_state()

        # Get T212 positions
        t212_positions = broker.get_open_positions()
        t212_cash_data = broker.get_account_balance()

        if not t212_positions and not t212_cash_data:
            result["status"] = "SKIP"
            result["details"] = "Could not fetch T212 data"
            return result

        # Build T212 position map — ticker -> quantity
        # T212 tickers need converting back to yfinance format
        from execution.t212_broker import _load_ticker_map
        ticker_map = _load_ticker_map()
        reverse_map = {v: k for k, v in ticker_map.items()}

        t212_pos_map = {}
        for pos in t212_positions:
            if pos.get("quantityInPies", 0) > 0:
                continue
            t212_ticker = pos.get("instrument", {}).get("ticker", "")
            yf_ticker = reverse_map.get(t212_ticker, t212_ticker)
            t212_pos_map[yf_ticker] = float(pos.get("quantity", 0))
            
        state_positions = state.get("positions", {})
        state_cash = float(state.get("cash", 0))
        t212_cash = float(t212_cash_data.get("free", 0))

        divergences = []

        # Check tickers in state but not in T212
        for ticker in state_positions:
            if ticker not in t212_pos_map:
                divergences.append(f"  • {ticker} in state but NOT in T212")

        # Check tickers in T212 but not in state
        for ticker in t212_pos_map:
            if ticker not in state_positions:
                divergences.append(f"  • {ticker} in T212 but NOT in state")

        # Check quantity mismatches
        for ticker in state_positions:
            if ticker in t212_pos_map:
                state_qty = float(state_positions[ticker].get("shares", 0))
                t212_qty = t212_pos_map[ticker]
                diff = abs(state_qty - t212_qty)
                if diff > 0.01:
                    divergences.append(
                        f"  • {ticker} qty mismatch: state={state_qty:.4f} T212={t212_qty:.4f}"
                    )

        # Check cash mismatch
        cash_diff = abs(state_cash - t212_cash)
        if cash_diff > CASH_DRIFT_THRESHOLD:
            divergences.append(
                f"  • Cash mismatch: state=£{state_cash:.2f} T212=£{t212_cash:.2f}"
            )

        if divergences:
            result["status"] = "WARN"
            result["details"] = f"{len(divergences)} divergence(s) found"
            if _should_alert("t212_sync"):
                details_text = "\n".join(divergences)
                _send_health_alert(
                    "Portfolio State Drift Detected",
                    f"TradeCore state does not match T212:\n\n"
                    f"{details_text}\n\n"
                    f"<b>Action required:</b> manually reconcile portfolio_state.json",
                    severity="CRITICAL"
                )
            logger.warning(f"T212 sync check failed: {len(divergences)} divergences")
        else:
            result["details"] = (
                f"{len(state_positions)} positions match | "
                f"Cash: state=£{state_cash:.2f} T212=£{t212_cash:.2f}"
            )
            logger.info(f"T212 sync check: all OK — {result['details']}")

    except Exception as e:
        result["status"] = "FAIL"
        result["details"] = str(e)
        logger.error(f"T212 sync check error: {e}")

    return result


def check_database() -> Dict:
    """Check SQLite database health — can we read/write, and how big is it?"""
    result = {"status": "OK", "details": ""}

    try:
        db_path = os.path.abspath(DB_PATH)

        if not os.path.exists(db_path):
            result["status"] = "FAIL"
            result["details"] = "Database file not found"
            if _should_alert("db_missing"):
                _send_health_alert(
                    "Database Missing",
                    f"Cannot find {db_path}",
                    severity="CRITICAL"
                )
            return result

        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        result["details"] = f"{size_mb:.1f} MB"

        if size_mb > DB_MAX_SIZE_MB:
            result["status"] = "WARN"
            result["details"] += " (large)"
            if _should_alert("db_size"):
                _send_health_alert(
                    "Database Growing Large",
                    f"Size: {size_mb:.1f} MB (threshold: {DB_MAX_SIZE_MB} MB)",
                    severity="WARNING"
                )

        conn = sqlite3.connect(db_path)
        conn.execute("SELECT COUNT(*) FROM trades")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT
            )
        """)
        conn.execute("INSERT INTO health_checks (status) VALUES ('OK')")
        conn.commit()
        conn.execute("""
            DELETE FROM health_checks
            WHERE id NOT IN (
                SELECT id FROM health_checks ORDER BY id DESC LIMIT 100
            )
        """)
        conn.commit()
        conn.close()

    except Exception as e:
        result["status"] = "FAIL"
        result["details"] = str(e)
        if _should_alert("db_error"):
            _send_health_alert(
                "Database Error",
                f"Read/write test failed: {e}",
                severity="CRITICAL"
            )

    return result


def check_memory() -> Dict:
    """Check system memory and CPU usage."""
    result = {"status": "OK", "details": ""}

    try:
        memory = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=1)

        result["details"] = f"RAM: {memory.percent:.0f}% | CPU: {cpu_pct:.0f}%"

        if memory.percent > MEMORY_WARN_PCT:
            result["status"] = "WARN"
            if _should_alert("memory_high"):
                _send_health_alert(
                    "High Memory Usage",
                    f"RAM: {memory.percent:.0f}% used "
                    f"({memory.used // (1024*1024)} MB / "
                    f"{memory.total // (1024*1024)} MB)\n"
                    f"CPU: {cpu_pct:.0f}%",
                    severity="WARNING"
                )

    except Exception as e:
        result["status"] = "FAIL"
        result["details"] = str(e)

    return result


def check_scheduler_heartbeat() -> Dict:
    """Check if scheduled jobs have been running on time."""
    result = {"status": "OK", "details": ""}

    if not _job_last_run:
        result["details"] = "No job runs recorded yet"
        return result

    now = datetime.now()
    missed = []

    expected = {
        "position_monitor": 20,
        "heartbeat": 65,
    }

    for job_name, max_gap in expected.items():
        last = _job_last_run.get(job_name)
        if last:
            gap = (now - last).total_seconds() / 60
            if gap > max_gap and _in_market_hours():
                missed.append(f"{job_name} ({gap:.0f} mins ago)")

    if missed:
        result["status"] = "WARN"
        result["details"] = f"Overdue: {', '.join(missed)}"
        if _should_alert("missed_job"):
            _send_health_alert(
                "Scheduled Job Overdue",
                f"These jobs haven't run recently:\n" +
                "\n".join(f"  • {m}" for m in missed),
                severity="WARNING"
            )
    else:
        last_runs = [f"{k}: {v.strftime('%H:%M')}" for k, v in _job_last_run.items()]
        result["details"] = " | ".join(last_runs[-3:])

    return result


def check_uptime() -> Dict:
    """Report process uptime."""
    elapsed = time.time() - _start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)

    return {
        "status": "OK",
        "details": f"{hours}h {minutes}m"
    }


def check_kill_switch() -> Dict:
    """Check if the kill switch has been triggered."""
    result = {"status": "OK", "details": "Inactive"}

    try:
        from execution.order_manager import load_portfolio_state
        state = load_portfolio_state()

        if state.get("kill_switch_active", False):
            result["status"] = "CRITICAL"
            result["details"] = "KILL SWITCH ACTIVE — trading halted"
            if _should_alert("kill_switch"):
                _send_health_alert(
                    "Kill Switch Active",
                    "All trading is halted.\nReview the dashboard.",
                    severity="CRITICAL"
                )
    except Exception as e:
        result["details"] = f"Could not check: {e}"

    return result


# ── Main Health Check Runner ────────────────────────────────────────────────

def run_health_check() -> Dict:
    """
    Run all health checks silently.
    Only sends Telegram alerts when something is wrong.
    Returns full results dict for logging.
    """
    logger.info("=== HEALTH CHECK RUNNING ===")

    results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_freshness": check_data_freshness(),
        "t212_api": check_t212_api(),
        "database": check_database(),
        "memory": check_memory(),
        "scheduler": check_scheduler_heartbeat(),
        "uptime": check_uptime(),
        "kill_switch": check_kill_switch(),
    }

    statuses = [v["status"] for k, v in results.items() if k != "timestamp"]
    fails = statuses.count("FAIL") + statuses.count("CRITICAL")
    warns = statuses.count("WARN")

    if fails > 0:
        logger.warning(f"Health check: {fails} FAIL, {warns} WARN")
    elif warns > 0:
        logger.info(f"Health check: {warns} WARN, rest OK")
    else:
        logger.info("Health check: all OK")

    return results


def run_sync_check():
    """
    Standalone sync check — called from scheduler at 07:00.
    Compares TradeCore state against T212 and alerts on divergence.
    """
    logger.info("=== T212 SYNC CHECK RUNNING ===")
    result = check_t212_sync()
    logger.info(f"T212 sync check complete: {result['status']} — {result['details']}")
    return result


# ── Daily Digest ────────────────────────────────────────────────────────────

def send_daily_digest():
    """
    21:00 — Send daily health summary to Telegram.
    One message: green if clean day, amber/red if issues occurred.
    """
    from notifications.telegram import send_message

    logger.info("=== DAILY HEALTH DIGEST ===")

    results = run_health_check()

    alert_count = len(_alerts_today)

    if alert_count == 0:
        emoji = "✅"
        headline = "Clean day — no issues detected"
    else:
        emoji = "⚠️"
        headline = f"{alert_count} alert{'s' if alert_count != 1 else ''} today"

    uptime = results["uptime"]["details"]
    memory = results["memory"]["details"]
    db = results["database"]["details"]

    lines = [
        f"{emoji} <b>TRADECORE DAILY HEALTH DIGEST</b>",
        f"",
        f"<b>Status:</b> {headline}",
        f"<b>Uptime:</b> {uptime}",
        f"<b>System:</b> {memory}",
        f"<b>Database:</b> {db}",
    ]

    if _alerts_today:
        lines.append("")
        lines.append("<b>Alerts fired today:</b>")
        for alert in _alerts_today:
            severity_icon = "🔴" if alert["severity"] == "CRITICAL" else "🟡"
            lines.append(f"  {severity_icon} {alert['time']} — {alert['title']}")

    if _job_last_run:
        lines.append("")
        lines.append("<b>Last job runs:</b>")
        for job_name, last_time in sorted(_job_last_run.items()):
            lines.append(f"  • {job_name}: {last_time.strftime('%H:%M')}")

    lines.append("")
    lines.append(f"⚙️ TradeCore Health Monitor")

    message = "\n".join(lines)

    try:
        send_message(message)
        logger.info("Daily health digest sent")
    except Exception as e:
        logger.error(f"Daily health digest failed: {e}")

    _alerts_today.clear()
    _alert_cooldowns.clear()