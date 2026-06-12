import logging
import json
import os
from datetime import datetime, timedelta
from data.price_feed import get_latest_price, get_historical_data
from signals.momentum import MomentumSignal
from signals.mean_reversion import MeanReversionSignal
from signals.breakout import BreakoutSignal
from signals.confidence_scorer import score_signal
from risk.stop_loss_engine import check_exit_conditions
from risk.correlation_checker import is_too_correlated
from risk.position_sizer import calculate_position_size
from database.queries import insert_signal, insert_trade, close_trade, insert_snapshot

logger = logging.getLogger(__name__)

# ── Paper scanner state and config — completely separate from live ─────────────
PAPER_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "portfolio_state_paper.json"
)
PAPER_RISK_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "risk_limits_paper.json"
)
PAPER_WATCHLIST_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "watchlist_paper.json"
)


def load_paper_limits() -> dict:
    """Load paper risk limits."""
    try:
        with open(PAPER_RISK_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load paper risk limits: {e}")
        return {
            "max_drawdown_pct": 8.0,
            "max_position_pct": 15.0,
            "max_open_positions": 30,
            "min_confidence_threshold": 65.0,
            "cash_floor_gbp": 10.0,
            "daily_loss_limit_pct": 3.0,
            "correlation_limit": 0.85,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 15.0,
            "starting_capital": 10000.0,
            "cash_deployment_threshold_pct": 40.0,
            "cash_deployment_min_confidence": 80.0,
        }


def load_paper_watchlist() -> list:
    """Load 600-stock paper watchlist."""
    try:
        with open(PAPER_WATCHLIST_FILE) as f:
            return json.load(f)["watchlist"]
    except Exception as e:
        logger.error(f"Failed to load paper watchlist: {e}")
        return []


def load_paper_state() -> dict:
    """Load paper portfolio state from disk."""
    if os.path.exists(PAPER_STATE_FILE):
        try:
            with open(PAPER_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load paper state: {e}")

    limits = load_paper_limits()
    starting = limits.get("starting_capital", 10000.0)
    return {
        "cash": starting,
        "starting_capital": starting,
        "positions": {},
        "last_updated": str(datetime.now()),
        "mode": "PAPER_SCANNER"
    }


def save_paper_state(state: dict):
    """Save paper portfolio state to disk."""
    try:
        state["last_updated"] = str(datetime.now())
        with open(PAPER_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save paper state: {e}")


def get_paper_portfolio_value(state: dict) -> float:
    """Calculate paper portfolio value."""
    total = state["cash"]
    for ticker, pos in state["positions"].items():
        price = get_latest_price(ticker)
        if price:
            total += pos["shares"] * price
    return round(total, 2)


def get_paper_summary() -> dict:
    """
    Build a weekly summary of paper scanner performance.
    Called by job_weekly_paper_summary() in scheduler.py every Friday 21:45.

    Returns:
        Dict consumed by send_weekly_paper_summary() in telegram.py
    """
    state = load_paper_state()
    limits = load_paper_limits()

    portfolio_value = get_paper_portfolio_value(state)
    cash = state["cash"]
    starting_capital = state["starting_capital"]
    total_pnl = portfolio_value - starting_capital
    total_pnl_pct = (total_pnl / starting_capital * 100) if starting_capital > 0 else 0.0

    # Week date range
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())

    try:
        from database.db import get_connection
        with get_connection() as conn:
            buys_week = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(opened_at) >= ? AND direction = 'BUY' AND paper = 1""",
                (str(week_start),)
            ).fetchone()["count"]

            sells_week = conn.execute(
                """SELECT COUNT(*) as count FROM trades
                   WHERE date(closed_at) >= ? AND status = 'CLOSED' AND paper = 1""",
                (str(week_start),)
            ).fetchone()["count"]

            closed = conn.execute(
                """SELECT ticker, pnl FROM trades
                   WHERE date(closed_at) >= ? AND status = 'CLOSED'
                   AND paper = 1 AND pnl IS NOT NULL""",
                (str(week_start),)
            ).fetchall()

            wins = [r["pnl"] for r in closed if r["pnl"] > 0]
            losses = [r["pnl"] for r in closed if r["pnl"] <= 0]
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0

    except Exception as e:
        logger.error(f"Paper summary DB query failed: {e}")
        buys_week = 0
        sells_week = 0
        wins = []
        losses = []
        avg_win = 0.0
        avg_loss = 0.0

    # ── RawCap experiment counter (added 12 Jun 2026) ──────────────────────
    # Counts paper signals this week where the MR raw cap fired.
    # Passive monitoring of the confidence scorer experiment via Telegram.
    rawcap_count = 0
    rawcap_tickers = []
    try:
        from database.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT ticker, COUNT(*) as n FROM signals
                   WHERE notes LIKE '%RawCap%'
                   AND date(created_at) >= ?
                   GROUP BY ticker""",
                (str(week_start),)
            ).fetchall()
            rawcap_tickers = [r["ticker"] for r in rows]
            rawcap_count = sum(r["n"] for r in rows)
    except Exception as e:
        logger.warning(f"RawCap counter query failed: {e}")

    # Actual watchlist size — read from file, not DB
    # Must be outside the DB block to always reflect true universe size
    try:
        total_scanned = len(load_paper_watchlist())
    except Exception:
        total_scanned = 530  # fallback

    top_performers = []
    worst_performers = []

    for ticker, pos in state["positions"].items():
        current_price = get_latest_price(ticker)
        if current_price:
            pnl = (current_price - pos["entry_price"]) * pos["shares"]
            pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
            top_performers.append({"ticker": ticker, "pnl": pnl, "pct": pct})
            worst_performers.append({"ticker": ticker, "pnl": pnl, "pct": pct})

    top_performers = sorted(top_performers, key=lambda x: x["pnl"], reverse=True)[:3]
    worst_performers = sorted(worst_performers, key=lambda x: x["pnl"])[:3]

    try:
        import datetime as dt
        paper_launch = dt.date(2026, 5, 18)
        week_number = max(1, ((today - paper_launch).days // 7) + 1)
    except Exception:
        week_number = 1

    try:
        with get_connection() as conn:
            week_snap = conn.execute(
                """SELECT total_value FROM portfolio_snapshots
                WHERE snapshot_date >= ? AND paper = 1
                ORDER BY snapshot_date ASC LIMIT 1""",
                (str(week_start),)
            ).fetchone()
            if not week_snap:
                week_snap = conn.execute(
                    """SELECT total_value FROM portfolio_snapshots
                    WHERE snapshot_date < ? AND paper = 1
                    ORDER BY snapshot_date DESC LIMIT 1""",
                    (str(week_start),)
                ).fetchone()
            week_start_value = week_snap["total_value"] if week_snap else starting_capital
            weekly_pnl = portfolio_value - week_start_value
            weekly_pnl_pct = ((weekly_pnl / week_start_value) * 100) if week_start_value > 0 else 0.0
    except Exception:
        weekly_pnl = total_pnl
        weekly_pnl_pct = total_pnl_pct

    return {
        "portfolio_value": portfolio_value,
        "cash": cash,
        "starting_capital": starting_capital,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "weekly_pnl": weekly_pnl,
        "weekly_pnl_pct": weekly_pnl_pct,
        "open_positions": len(state["positions"]),
        "max_positions": limits.get("max_open_positions", 30),
        "total_buys_week": buys_week,
        "total_sells_week": sells_week,
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "top_performers": top_performers,
        "worst_performers": worst_performers,
        "total_scanned": total_scanned,
        "week_number": week_number,
        "rawcap_count": rawcap_count,
        "rawcap_tickers": rawcap_tickers,
    }


def run_paper_scan() -> dict:
    """
    Run the 600-stock paper scanner.
    Fires at 14:45 (US open), 20:30 (late US session) Monday to Friday.
    Completely independent from live trading — separate state,
    separate config, separate watchlist.

    Signal queue approach:
        Pass 1 — scan ALL stocks, collect every actionable signal
        Pass 2 — sort by confidence (highest first), fill available slots

    This ensures the best signals always get priority regardless of
    their position in the watchlist.

    Returns:
        Dict with scan results for Telegram summary
    """
    # Weekend gate — no point scanning with stale prices
    from execution.order_manager import is_trading_day
    if not is_trading_day():
        logger.info("Weekend — paper scan skipped (markets closed)")
        return {}

    limits = load_paper_limits()
    state = load_paper_state()
    watchlist = load_paper_watchlist()

    if not watchlist:
        logger.error("Paper watchlist empty — aborting paper scan")
        return {}

    portfolio_value = get_paper_portfolio_value(state)
    cash = state["cash"]
    starting_capital = state["starting_capital"]

    max_positions = limits["max_open_positions"]
    min_confidence = limits["min_confidence_threshold"]
    stop_loss_pct = limits["stop_loss_pct"]
    take_profit_pct = limits["take_profit_pct"]
    correlation_limit = limits["correlation_limit"]
    cash_floor = limits["cash_floor_gbp"]

    logger.info(f"=== PAPER SCAN STARTING ===")
    logger.info(f"Watchlist: {len(watchlist)} stocks | Portfolio: £{portfolio_value:.2f} | Cash: £{cash:.2f}")

    # Initialise signal engines
    momentum_engine = MomentumSignal()
    reversion_engine = MeanReversionSignal()
    breakout_engine = BreakoutSignal()

    buys = []
    sells = []
    top_signals = []
    errors = 0

    # ── Monitor existing paper positions for exits ─────────────────────────
    for ticker, pos in list(state["positions"].items()):
        current_price = get_latest_price(ticker)
        if not current_price:
            continue

        highest_price = pos.get("highest_price", pos["entry_price"])
        if current_price > highest_price:
            highest_price = current_price
            state["positions"][ticker]["highest_price"] = highest_price

        exit_check = check_exit_conditions(
            current_price=current_price,
            entry_price=pos["entry_price"],
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            highest_price=highest_price
        )

        if exit_check["should_exit"]:
            shares = pos["shares"]
            sell_value = shares * current_price
            pnl = sell_value - (shares * pos["entry_price"])

            cash += sell_value
            state["cash"] = cash
            del state["positions"][ticker]

            close_trade(pos["trade_id"], pnl)

            sells.append({
                "ticker": ticker,
                "price": current_price,
                "pnl": round(pnl, 2),
                "reason": exit_check["reason"]
            })
            logger.info(f"PAPER SELL: {ticker} | {exit_check['reason']} | P&L=£{pnl:.2f}")

    # ── Pass 1: Scan ALL stocks, build ranked signal queue ─────────────────
    open_tickers = list(state["positions"].keys())
    scanned = 0
    signals_fired = 0
    signal_queue = []

    for stock in watchlist:
        ticker = stock["ticker"]
        scanned += 1

        # Skip already held positions
        if ticker in open_tickers:
            continue

        try:
            df = get_historical_data(ticker, period="1y")
            if df is None or df.empty:
                continue

            # Earnings calendar check — skip if earnings in next 3 days
            from data.earnings_calendar import is_earnings_safe
            if not is_earnings_safe(ticker):
                logger.debug(f"[PAPER] Earnings approaching for {ticker} — skipping")
                continue

            current_price = get_latest_price(ticker)
            if not current_price:
                continue

            # Evaluate all three signals
            raw_momentum = momentum_engine.evaluate(ticker, df)
            raw_reversion = reversion_engine.evaluate(ticker, df)
            raw_breakout = breakout_engine.evaluate(ticker, df)

            # Pick highest confidence raw signal
            best_raw = max(
                [raw_momentum, raw_reversion, raw_breakout],
                key=lambda s: s.confidence
            )

            # Apply confidence scorer
            final_signal = score_signal(best_raw, df, paper=True)
            
            if not final_signal.is_actionable(min_confidence):
                continue
            if final_signal.direction != "BUY":
                continue

            signals_fired += 1

            signal_queue.append({
                "ticker": ticker,
                "signal": final_signal,
                "df": df,
                "current_price": current_price,
                "confidence": final_signal.confidence,
                "signal_type": final_signal.signal_type
            })

            top_signals.append({
                "ticker": ticker,
                "signal_type": final_signal.signal_type,
                "confidence": final_signal.confidence,
                "price": current_price,
                "direction": final_signal.direction
            })

        except Exception as e:
            errors += 1
            logger.warning(f"Paper scan error for {ticker}: {e}")
            continue

    # ── Pass 2: Sort by confidence, fill available slots ──────────────────
    signal_queue_sorted = sorted(signal_queue, key=lambda x: x["confidence"], reverse=True)
    slots_available = max_positions - len(state["positions"])

    logger.info(f"Pass 1 complete — Scanned: {scanned} | Signals: {signals_fired} | "
                f"Slots available: {slots_available}")

    for item in signal_queue_sorted:
        ticker = item["ticker"]
        final_signal = item["signal"]
        current_price = item["current_price"]

        if len(state["positions"]) >= max_positions:
            break
        if cash < cash_floor:
            break

        if ticker in open_tickers:
            continue

        corr_check = is_too_correlated(
            ticker, open_tickers,
            correlation_limit=correlation_limit
        )
        if corr_check["blocked"]:
            cash_pct = (cash / portfolio_value) * 100
            if not (cash_pct >= limits["cash_deployment_threshold_pct"] and
                    final_signal.confidence >= limits["cash_deployment_min_confidence"]):
                continue

        size = calculate_position_size(
            portfolio_value=portfolio_value,
            cash_available=cash,
            current_price=current_price,
            confidence=final_signal.confidence,
            max_position_pct=limits["max_position_pct"] / 100
        )

        if not size["approved"]:
            continue

        signal_id = insert_signal(
            ticker=ticker,
            signal_type=f"PAPER_{final_signal.signal_type}",
            direction="BUY",
            confidence=final_signal.confidence,
            price=current_price,
            regime=final_signal.regime,
            notes=f"[PAPER SCANNER] {final_signal.notes}"
        )

        trade_id = insert_trade(
            signal_id=signal_id,
            ticker=ticker,
            direction="BUY",
            quantity=size["shares"],
            price=current_price,
            paper=1
        )

        cash -= size["invest_amount"]
        state["cash"] = cash
        state["positions"][ticker] = {
            "shares": size["shares"],
            "entry_price": current_price,
            "highest_price": current_price,
            "trade_id": trade_id,
            "invested": size["invest_amount"]
        }
        open_tickers.append(ticker)

        buys.append({
            "ticker": ticker,
            "price": current_price,
            "amount": size["invest_amount"],
            "confidence": final_signal.confidence,
            "signal_type": final_signal.signal_type
        })

        logger.info(f"PAPER BUY: {ticker} | £{size['invest_amount']:.2f} | "
                    f"Conf={final_signal.confidence:.1f}% | {final_signal.signal_type}")

    # ── Save state and snapshot ────────────────────────────────────────────
    portfolio_value = get_paper_portfolio_value(state)
    save_paper_state(state)

    insert_snapshot(
        snapshot_date=str(datetime.now().date()),
        total_value=portfolio_value,
        cash_balance=cash,
        invested_value=portfolio_value - cash,
        paper=1
    )

    total_pnl = portfolio_value - starting_capital
    total_pnl_pct = (total_pnl / starting_capital) * 100

    logger.info(f"=== PAPER SCAN COMPLETE ===")
    logger.info(f"Scanned: {scanned} | Signals: {signals_fired} | "
                f"Buys: {len(buys)} | Sells: {len(sells)} | Errors: {errors}")
    logger.info(f"Paper Portfolio: £{portfolio_value:.2f} | P&L: £{total_pnl:.2f} ({total_pnl_pct:.2f}%)")

    top_signals_sorted = sorted(top_signals, key=lambda x: x["confidence"], reverse=True)[:5]

    return {
        "portfolio_value": portfolio_value,
        "cash": cash,
        "starting_capital": starting_capital,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "open_positions": len(state["positions"]),
        "max_positions": max_positions,
        "scanned": scanned,
        "signals_fired": signals_fired,
        "buys": buys,
        "sells": sells,
        "top_signals": top_signals_sorted,
        "errors": errors
    }