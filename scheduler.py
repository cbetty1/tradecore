import logging
import json
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="Europe/London")


def load_watchlist() -> list:
    """Load watchlist from config."""
    with open("config/watchlist.json") as f:
        return json.load(f)["watchlist"]


def job_pre_market_scan():
    """07:00 — Pre-market signal summary to Telegram."""
    from monitoring.health_monitor import record_job_run
    record_job_run("pre_market_scan")

    logger.info("=== PRE-MARKET SCAN STARTING ===")
    try:
        from data.price_feed import get_historical_data, get_latest_price
        from signals.momentum import MomentumSignal
        from signals.confidence_scorer import score_signal
        from notifications.telegram import send_signal_summary

        watchlist = load_watchlist()
        signal_engine = MomentumSignal()
        signals = []

        for stock in watchlist:
            ticker = stock["ticker"]
            df = get_historical_data(ticker, period="1y")
            if df is None or df.empty:
                continue
            price = get_latest_price(ticker)
            if not price:
                continue
            raw = signal_engine.evaluate(ticker, df)
            final = score_signal(raw, df)
            signals.append({
                "ticker": ticker,
                "direction": final.direction,
                "confidence": final.confidence,
                "price": price
            })

        send_signal_summary(signals)
        logger.info(f"Pre-market scan complete — {len(signals)} signals evaluated")

    except Exception as e:
        logger.error(f"Pre-market scan failed: {e}")


def job_monitor_positions():
    """Every 15 mins — monitor live positions and scan for new entries."""
    from monitoring.health_monitor import record_job_run
    record_job_run("position_monitor")

    # Weekend gate — markets are closed, skip entirely
    from execution.order_manager import is_trading_day
    if not is_trading_day():
        logger.info("Weekend — position monitor skipped (markets closed)")
        return

    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # Only run during market hours 08:00 - 21:00 (covers full US session)
    if not (8 <= hour < 21):
        logger.info(f"Outside market hours ({hour:02d}:{minute:02d}) — skipping position monitor")
        return

    logger.info("=== POSITION MONITOR RUNNING ===")
    try:
        from execution.order_manager import run_scan
        from notifications.telegram import send_trade_alert

        watchlist = load_watchlist()
        actions = run_scan(watchlist)

        for action in actions:
            if action["action"] == "BUY":
                send_trade_alert(
                    action="BUY",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["invest_amount"],
                    confidence=action["confidence"]
                )
            elif action["action"] == "SELL":
                send_trade_alert(
                    action="SELL",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["sell_value"],
                    pnl=action["pnl"],
                    reason=action["reason"]
                )
            elif action["action"] == "KILL_SWITCH":
                from notifications.telegram import send_kill_switch_alert
                send_kill_switch_alert(action["reason"])

    except Exception as e:
        logger.error(f"Position monitor failed: {e}")


def job_midday_scan():
    """12:00 — Midday trade scan (no Telegram summary — execution only)."""
    from monitoring.health_monitor import record_job_run
    record_job_run("midday_scan")

    logger.info("=== MIDDAY SCAN STARTING ===")
    try:
        from execution.order_manager import run_scan
        from notifications.telegram import send_trade_alert

        watchlist = load_watchlist()
        actions = run_scan(watchlist)

        for action in actions:
            if action["action"] == "BUY":
                send_trade_alert(
                    action="BUY",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["invest_amount"],
                    confidence=action["confidence"]
                )
            elif action["action"] == "SELL":
                send_trade_alert(
                    action="SELL",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["sell_value"],
                    pnl=action["pnl"],
                    reason=action["reason"]
                )
            elif action["action"] == "KILL_SWITCH":
                from notifications.telegram import send_kill_switch_alert
                send_kill_switch_alert(action["reason"])

        logger.info(f"Midday scan complete — {len(actions)} actions")

    except Exception as e:
        logger.error(f"Midday scan failed: {e}")


def job_afternoon_scan():
    """16:00 — Afternoon trade scan (no Telegram summary — execution only)."""
    from monitoring.health_monitor import record_job_run
    record_job_run("afternoon_scan")

    logger.info("=== AFTERNOON SCAN STARTING ===")
    try:
        from execution.order_manager import run_scan
        from notifications.telegram import send_trade_alert

        watchlist = load_watchlist()
        actions = run_scan(watchlist)

        for action in actions:
            if action["action"] == "BUY":
                send_trade_alert(
                    action="BUY",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["invest_amount"],
                    confidence=action["confidence"]
                )
            elif action["action"] == "SELL":
                send_trade_alert(
                    action="SELL",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["sell_value"],
                    pnl=action["pnl"],
                    reason=action["reason"]
                )
            elif action["action"] == "KILL_SWITCH":
                from notifications.telegram import send_kill_switch_alert
                send_kill_switch_alert(action["reason"])

        logger.info("Afternoon scan complete")

    except Exception as e:
        logger.error(f"Afternoon scan failed: {e}")


def job_paper_scan():
    """14:45 + 18:00 — 600-stock paper scanner. Batched Telegram summary only."""
    from monitoring.health_monitor import record_job_run
    record_job_run("paper_scan")

    logger.info("=== PAPER SCAN STARTING ===")
    try:
        from execution.paper_scanner import run_paper_scan
        from notifications.telegram import send_paper_scan_summary

        result = run_paper_scan()
        send_paper_scan_summary(result)

        logger.info(f"Paper scan complete — {result.get('scanned', 0)} stocks scanned | "
                    f"{result.get('signals_fired', 0)} signals | "
                    f"{len(result.get('buys', []))} buys | "
                    f"{len(result.get('sells', []))} sells")

    except Exception as e:
        logger.error(f"Paper scan failed: {e}")
        from notifications.telegram import send_message
        send_message(f"⚠️ <b>PAPER SCAN FAILED</b>\n\nError: {str(e)}\n\n📋 TradeCore Paper Scanner")


def job_late_us_scan():
    """20:30 — Late US session scan (no Telegram summary — execution only)."""
    from monitoring.health_monitor import record_job_run
    record_job_run("late_us_scan")

    logger.info("=== LATE US SCAN STARTING ===")
    try:
        from execution.order_manager import run_scan
        from notifications.telegram import send_trade_alert

        watchlist = load_watchlist()
        actions = run_scan(watchlist)

        for action in actions:
            if action["action"] == "BUY":
                send_trade_alert(
                    action="BUY",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["invest_amount"],
                    confidence=action["confidence"]
                )
            elif action["action"] == "SELL":
                send_trade_alert(
                    action="SELL",
                    ticker=action["ticker"],
                    price=action["price"],
                    shares=action["shares"],
                    amount=action["sell_value"],
                    pnl=action["pnl"],
                    reason=action["reason"]
                )
            elif action["action"] == "KILL_SWITCH":
                from notifications.telegram import send_kill_switch_alert
                send_kill_switch_alert(action["reason"])

        logger.info("Late US scan complete")

    except Exception as e:
        logger.error(f"Late US scan failed: {e}")


def job_daily_report():
    """21:15 — End of day performance report after US market close."""
    from monitoring.health_monitor import record_job_run
    record_job_run("daily_report")

    try:
        from database.db import get_connection
        today = str(datetime.now().date())
        with get_connection() as conn:
            already_sent = conn.execute(
                """SELECT COUNT(*) as count FROM portfolio_snapshots
                   WHERE snapshot_date = ?
                   AND recorded_at > datetime('now', '-1 hour')""",
                (today,)
            ).fetchone()["count"]
        if already_sent > 1:
            logger.info("Daily report already sent today — skipping duplicate")
            return
    except Exception as e:
        logger.warning(f"Duplicate check failed: {e}")

    logger.info("=== DAILY REPORT GENERATING ===")
    try:
        from execution.order_manager import load_portfolio_state, get_portfolio_value
        from database.queries import get_snapshots
        from notifications.telegram import send_daily_report
        from data.price_feed import get_latest_price

        state = load_portfolio_state()
        for ticker in state["positions"]:
            get_latest_price(ticker)
        portfolio_value = get_portfolio_value(state)
        cash = state["cash"]
        starting_capital = state["starting_capital"]
        total_pnl = portfolio_value - starting_capital
        open_positions = len(state["positions"])

        snapshots = get_snapshots(2)
        if len(snapshots) >= 2:
            daily_pnl = snapshots[0]["total_value"] - snapshots[1]["total_value"]
            if abs(daily_pnl) > (portfolio_value * 0.5):
                logger.warning(f"Daily P&L sanity check failed: {daily_pnl:.2f} — capping at 0")
                daily_pnl = 0.0
        else:
            daily_pnl = 0.0

        from database.db import get_connection
        today = str(datetime.now().date())
        with get_connection() as conn:
            trades_today = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(opened_at) = ?
                   OR date(closed_at) = ?""",
                (today, today)
            ).fetchone()["count"]

            buys_today = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(opened_at) = ? AND direction = 'BUY'""",
                (today,)
            ).fetchone()["count"]

            sells_today = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(closed_at) = ? AND direction = 'BUY' AND status = 'CLOSED'""",
                (today,)
            ).fetchone()["count"]

        send_daily_report(
            portfolio_value=portfolio_value,
            cash=cash,
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            open_positions=open_positions,
            trades_today=trades_today,
            positions=state["positions"],
            buys_today=buys_today,
            sells_today=sells_today
        )

        logger.info("Daily report sent")

    except Exception as e:
        logger.error(f"Daily report failed: {e}")


def job_heartbeat():
    """Every hour — confirm system is alive."""
    from monitoring.health_monitor import record_job_run
    record_job_run("heartbeat")
    logger.info(f"Heartbeat | {datetime.now().strftime('%H:%M:%S')} | System running")


def job_health_check():
    """Every 15 mins — silent health check, alerts only on failure."""
    from monitoring.health_monitor import run_health_check
    run_health_check()


def job_daily_health_digest():
    """21:00 — Daily health summary to Telegram."""
    from monitoring.health_monitor import send_daily_digest
    send_daily_digest()


def job_weekly_summary():
    """Friday 17:30 — Weekly live performance and withdrawal summary."""
    from monitoring.health_monitor import record_job_run
    record_job_run("weekly_summary")

    logger.info("=== WEEKLY SUMMARY GENERATING ===")
    try:
        from execution.order_manager import load_portfolio_state, get_portfolio_value
        from database.db import get_connection
        from notifications.telegram import send_weekly_summary
        from data.price_feed import get_latest_price

        state = load_portfolio_state()
        for ticker in state["positions"]:
            get_latest_price(ticker)
        portfolio_value = get_portfolio_value(state)
        cash = state["cash"]
        starting_capital = state["starting_capital"]
        total_pnl = portfolio_value - starting_capital

        today = datetime.now().date()
        week_start = today - __import__('datetime').timedelta(days=today.weekday())

        with get_connection() as conn:
            week_snapshots = conn.execute(
                """SELECT total_value FROM portfolio_snapshots
                   WHERE snapshot_date >= ?
                   ORDER BY snapshot_date ASC LIMIT 1""",
                (str(week_start),)
            ).fetchone()
            week_start_value = week_snapshots["total_value"] if week_snapshots else starting_capital
            weekly_pnl = portfolio_value - week_start_value

            buys_week = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(opened_at) >= ? AND direction = 'BUY'""",
                (str(week_start),)
            ).fetchone()["count"]

            sells_week = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(closed_at) >= ? AND status = 'CLOSED'""",
                (str(week_start),)
            ).fetchone()["count"]

            closed = conn.execute(
                """SELECT pnl FROM trades
                   WHERE date(closed_at) >= ? AND status = 'CLOSED' AND pnl IS NOT NULL""",
                (str(week_start),)
            ).fetchall()

            wins = [r["pnl"] for r in closed if r["pnl"] > 0]
            losses = [r["pnl"] for r in closed if r["pnl"] <= 0]
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0

            # ── Performance attribution — wins/losses/avg P&L per signal type ──
            attribution_rows = conn.execute(
                """SELECT s.signal_type, t.pnl FROM trades t
                   LEFT JOIN signals s ON t.signal_id = s.id
                   WHERE date(t.closed_at) >= ? AND t.status = 'CLOSED' AND t.pnl IS NOT NULL""",
                (str(week_start),)
            ).fetchall()

            signal_attribution = {}
            for row in attribution_rows:
                sig = row["signal_type"] or "UNKNOWN"
                if sig not in signal_attribution:
                    signal_attribution[sig] = {"wins": 0, "losses": 0, "pnls": []}
                signal_attribution[sig]["pnls"].append(row["pnl"])
                if row["pnl"] > 0:
                    signal_attribution[sig]["wins"] += 1
                else:
                    signal_attribution[sig]["losses"] += 1

            for sig in signal_attribution:
                pnls = signal_attribution[sig].pop("pnls")
                signal_attribution[sig]["avg_pnl"] = sum(pnls) / len(pnls) if pnls else 0.0

            signals_fired = conn.execute(
                """SELECT COUNT(*) as count FROM signals
                   WHERE date(created_at) >= ?""",
                (str(week_start),)
            ).fetchone()["count"]

            signals_acted = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(opened_at) >= ?""",
                (str(week_start),)
            ).fetchone()["count"]

        go_live = __import__('datetime').date(2026, 5, 12)
        week_number = max(1, ((today - go_live).days // 7) + 1)

        send_weekly_summary(
            portfolio_value=portfolio_value,
            cash=cash,
            starting_capital=starting_capital,
            weekly_pnl=weekly_pnl,
            total_pnl=total_pnl,
            positions=state["positions"],
            buys_week=buys_week,
            sells_week=sells_week,
            closed_wins=len(wins),
            closed_losses=len(losses),
            avg_win=avg_win,
            avg_loss=avg_loss,
            signals_fired=signals_fired,
            signals_acted=signals_acted,
            week_number=week_number,
            signal_attribution=signal_attribution
        )

        logger.info("Weekly summary sent")

    except Exception as e:
        logger.error(f"Weekly summary failed: {e}")


def job_weekly_paper_analysis():
    """Friday 17:45 — Generate and send weekly paper scanner analysis PDF."""
    from monitoring.health_monitor import record_job_run
    record_job_run("weekly_paper_analysis")

    logger.info("=== WEEKLY PAPER ANALYSIS STARTING ===")
    try:
        from analysis.paper_analyser import run_weekly_paper_analysis
        run_weekly_paper_analysis()
    except Exception as e:
        logger.error(f"Weekly paper analysis failed: {e}")


def job_weekly_paper_summary():
    """Friday 18:00 — Weekly paper scanner performance summary."""
    from monitoring.health_monitor import record_job_run
    record_job_run("weekly_paper_summary")

    logger.info("=== WEEKLY PAPER SUMMARY GENERATING ===")
    try:
        from execution.paper_scanner import get_paper_summary
        from notifications.telegram import send_weekly_paper_summary

        summary = get_paper_summary()
        send_weekly_paper_summary(summary)

        logger.info("Weekly paper summary sent")

    except Exception as e:
        logger.error(f"Weekly paper summary failed: {e}")
        from notifications.telegram import send_message
        send_message(f"⚠️ <b>WEEKLY PAPER SUMMARY FAILED</b>\n\nError: {str(e)}\n\n📋 TradeCore Paper Scanner")


def job_sync_check():
    """06:55 — Daily T212 position sync check before pre-market scan."""
    from monitoring.health_monitor import run_sync_check
    run_sync_check()


def start():
    """Register all jobs and start the scheduler."""

    scheduler.add_job(
        job_sync_check,
        CronTrigger(day_of_week="mon-fri", hour=6, minute=55),
        id="sync_check",
        name="T212 Sync Check"
    )

    # ── Live Trading Jobs ───────────────────────────────────────────────────

    scheduler.add_job(
        job_pre_market_scan,
        CronTrigger(day_of_week="mon-fri", hour=7, minute=0),
        id="pre_market_scan",
        name="Pre-Market Scan"
    )

    scheduler.add_job(
        job_monitor_positions,
        IntervalTrigger(minutes=15),
        id="position_monitor",
        name="Position Monitor"
    )

    scheduler.add_job(
        job_midday_scan,
        CronTrigger(day_of_week="mon-fri", hour=12, minute=0),
        id="midday_scan",
        name="Midday Scan"
    )

    scheduler.add_job(
        job_afternoon_scan,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="afternoon_scan",
        name="Afternoon Scan"
    )

    scheduler.add_job(
        job_late_us_scan,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=30),
        id="late_us_scan",
        name="Late US Scan"
    )

    # ── Paper Scanner Jobs ──────────────────────────────────────────────────

    scheduler.add_job(
        job_paper_scan,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=45),
        id="paper_scan_us_open",
        name="Paper Scanner US Open (600 stocks)"
    )

    scheduler.add_job(
        job_paper_scan,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=30),
        id="paper_scan_late",
        name="Paper Scanner Late Session (600 stocks)"
    )

    # ── Reporting Jobs ──────────────────────────────────────────────────────

    scheduler.add_job(
        job_daily_report,
        CronTrigger(day_of_week="mon-fri", hour=21, minute=15),
        id="daily_report",
        name="Daily Report"
    )

    scheduler.add_job(
        job_weekly_summary,
        CronTrigger(day_of_week="fri", hour=17, minute=30),
        id="weekly_summary",
        name="Weekly Summary"
    )

    scheduler.add_job(
        job_weekly_paper_analysis,
        CronTrigger(day_of_week="fri", hour=21, minute=30),
        id="weekly_paper_analysis",
        name="Weekly Paper Analysis"
    )

    scheduler.add_job(
        job_weekly_paper_summary,
        CronTrigger(day_of_week="fri", hour=20, minute=30),
        id="weekly_paper_summary",
        name="Weekly Paper Summary"
    )

    # ── System Jobs ─────────────────────────────────────────────────────────

    scheduler.add_job(
        job_heartbeat,
        IntervalTrigger(hours=1),
        id="heartbeat",
        name="Heartbeat"
    )

    scheduler.add_job(
        job_health_check,
        IntervalTrigger(minutes=15, start_date="2026-01-01 00:05:00"),
        id="health_check",
        name="Health Check"
    )

    scheduler.add_job(
        job_daily_health_digest,
        CronTrigger(day_of_week="mon-fri", hour=21, minute=0),
        id="daily_health_digest",
        name="Daily Health Digest"
    )

    logger.info("=" * 50)
    logger.info("  TradeCore Scheduler Starting")
    logger.info("  ── Live Trading ──────────────────────")
    logger.info("  06:55        T212 sync check")
    logger.info("  07:00        Pre-market scan + signal summary")
    logger.info("  08:00-21:00  Position monitor (every 15 mins)")
    logger.info("  12:00        Midday scan (execution only)")
    logger.info("  16:00        Afternoon scan (execution only)")
    logger.info("  20:30        Late US scan (execution only)")
    logger.info("  ── Paper Scanner ─────────────────────")
    logger.info("  14:45        Paper scan — US open (600 stocks)")
    logger.info("  20:30        Paper scan — late session (600 stocks)")
    logger.info("  ── Reports ───────────────────────────")
    logger.info("  21:00        Daily health digest")
    logger.info("  21:15        Daily report")
    logger.info("  Fri 17:30    Weekly live summary")
    logger.info("  Fri 20:30    Weekly paper summary")
    logger.info("  Fri 21:30    Weekly paper analysis PDF")
    logger.info("=" * 50)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
        scheduler.shutdown()


if __name__ == "__main__":
    start()