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
"""

import logging
import os
import time
import sqlite3
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config.settings import DB_PATH, T212_API_KEY, T212_BASE_URL

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
STALE_PRICE_MINUTES = 30        # Alert if price data older than this during market hours
DB_MAX_SIZE_MB = 500            # Alert if database exceeds this size
MEMORY_WARN_PCT = 85            # Alert if memory usage above this %
MISSED_JOB_MINUTES = 10         # Alert if a scheduled job is more than this late

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


# ── Individual Health Checks ────────────────────────────────────────────────

def check_data_freshness() -> Dict:
    """Check if yfinance is returning fresh price data."""
    result = {"status": "OK", "details": ""}

    if not _in_market_hours():
        result["details"] = "Outside market hours — skipped"
        return result

    try:
        from data.price_feed import get_latest_price
        import yfinance as yf

        # Test with a liquid stock
        ticker = yf.Ticker("AAPL")
        hist = ticker.history(period="1d", interval="1m")

        if hist.empty:
            result["status"] = "FAIL"
            result["details"] = "yfinance returned empty data for AAPL"
            if _should_alert("stale_data"):
                _send_health_alert(
                    "Stale Price Data",
                    "yfinance is returning empty data.\n"
                    "Trades will NOT execute on stale prices.",
                    severity="CRITICAL"
                )
        else:
            last_timestamp = hist.index[-1]
            # Make both timezone-naive for comparison
            if hasattr(last_timestamp, 'tz') and last_timestamp.tz is not None:
                last_timestamp = last_timestamp.tz_localize(None)
            age_minutes = (datetime.now() - last_timestamp).total_seconds() / 60

            if age_minutes > STALE_PRICE_MINUTES:
                result["status"] = "WARN"
                result["details"] = f"Latest price is {age_minutes:.0f} mins old"
                if _should_alert("stale_data"):
                    _send_health_alert(
                        "Stale Price Data",
                        f"Latest AAPL price is {age_minutes:.0f} minutes old.\n"
                        f"Threshold: {STALE_PRICE_MINUTES} minutes.",
                        severity="WARNING"
                    )
            else:
                result["details"] = f"Fresh ({age_minutes:.0f} mins old)"

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
        import requests
        response = requests.get(
            f"{T212_BASE_URL}/api/v0/equity/account/cash",
            headers={"Authorization": T212_API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            result["details"] = "Connected"
        elif response.status_code == 401:
            result["status"] = "FAIL"
            result["details"] = "Authentication failed"
            if _should_alert("t212_auth"):
                _send_health_alert(
                    "T212 API Auth Failed",
                    "API key may be invalid or expired.",
                    severity="CRITICAL"
                )
        else:
            result["status"] = "WARN"
            result["details"] = f"HTTP {response.status_code}"
            if _should_alert("t212_api"):
                _send_health_alert(
                    "T212 API Issue",
                    f"Returned HTTP {response.status_code}",
                    severity="WARNING"
                )

    except requests.exceptions.Timeout:
        result["status"] = "FAIL"
        result["details"] = "Connection timeout"
        if _should_alert("t212_api"):
            _send_health_alert(
                "T212 API Timeout",
                "Could not reach Trading 212 within 10 seconds.",
                severity="WARNING"
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


def check_database() -> Dict:
    """Check SQLite database health — can we read/write, and how big is it?"""
    result = {"status": "OK", "details": ""}

    try:
        db_path = os.path.abspath(DB_PATH)

        # Check file exists
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

        # Check file size
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

        # Test read/write
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
        # Clean up old health checks (keep last 100)
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
                    f"RAM: {memory.percent:.0f}% used ({memory.used // (1024*1024)} MB / {memory.total // (1024*1024)} MB)\n"
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

    # Expected schedules (job_name -> max minutes between runs)
    expected = {
        "position_monitor": 20,     # Every 15 mins + buffer
        "heartbeat": 65,            # Every 60 mins + buffer
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

    # Count issues
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


# ── Daily Digest ────────────────────────────────────────────────────────────

def send_daily_digest():
    """
    21:00 — Send daily health summary to Telegram.
    One message: green if clean day, amber/red if issues occurred.
    """
    from notifications.telegram import send_message

    logger.info("=== DAILY HEALTH DIGEST ===")

    # Run a final check
    results = run_health_check()

    # Build digest
    alert_count = len(_alerts_today)

    if alert_count == 0:
        emoji = "✅"
        headline = "Clean day — no issues detected"
    else:
        emoji = "⚠️"
        headline = f"{alert_count} alert{'s' if alert_count != 1 else ''} today"

    # System stats
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

    # List today's alerts if any
    if _alerts_today:
        lines.append("")
        lines.append("<b>Alerts fired today:</b>")
        for alert in _alerts_today:
            severity_icon = "🔴" if alert["severity"] == "CRITICAL" else "🟡"
            lines.append(f"  {severity_icon} {alert['time']} — {alert['title']}")

    # Job run summary
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

    # Reset daily counters
    _alerts_today.clear()
    _alert_cooldowns.clear()