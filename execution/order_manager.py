import logging
import json
import os
from datetime import datetime, timedelta
from data.price_feed import get_latest_price, get_historical_data
from signals.momentum import MomentumSignal
from signals.confidence_scorer import score_signal, get_market_regime
from risk.position_sizer import calculate_position_size
from risk.drawdown_guard import is_kill_switch_active
from risk.stop_loss_engine import check_exit_conditions
from risk.correlation_checker import is_too_correlated
from database.queries import (insert_signal, insert_trade,
                               close_trade, get_open_trades,
                               insert_snapshot)
from config.settings import (DEFAULT_CONFIDENCE_THRESHOLD,
                              MAX_POSITION_SIZE, CASH_FLOOR,
                              CASH_DEPLOYMENT_THRESHOLD_PCT,
                              CASH_DEPLOYMENT_MIN_CONFIDENCE)

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "portfolio_state.json")
RISK_LIMITS_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "risk_limits.json")

BREAKOUT_PAPER_ONLY = True
EARNINGS_DRIFT_PAPER_ONLY = True
EARNINGS_DRIFT_MIN_CONFIDENCE = 70.0


def is_trading_day() -> bool:
    return datetime.now().weekday() < 5


def _is_paper_mode() -> bool:
    try:
        with open(RISK_LIMITS_FILE) as f:
            limits = json.load(f)
            return limits.get("paper_trading_mode", True)
    except Exception as e:
        logger.error(f"Failed to read risk_limits.json — defaulting to PAPER mode: {e}")
        return True


def _get_risk_limits() -> dict:
    try:
        with open(RISK_LIMITS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_max_positions() -> int:
    limits = _get_risk_limits()
    return limits.get("max_open_positions", 5)


def _get_tc_max_positions() -> int:
    limits = _get_risk_limits()
    return limits.get("max_tc_positions", 7)


def _get_edge_max_positions() -> int:
    limits = _get_risk_limits()
    return limits.get("max_edge_positions", 1)


def _get_broker():
    from execution.t212_broker import T212Broker
    return T212Broker()


def _is_edge_ticker(ticker: str, watchlist: list) -> bool:
    """Return True if this ticker was promoted from EdgeScanner."""
    for stock in watchlist:
        if stock["ticker"] == ticker:
            return stock.get("source") == "EdgeScanner"
    return False


def _count_positions_by_source(positions: dict, watchlist: list) -> tuple:
    """Return (tc_count, edge_count) of open positions."""
    tc_count = 0
    edge_count = 0
    for ticker, pos in positions.items():
        if pos.get("source") == "EdgeScanner":
            edge_count += 1
        else:
            tc_count += 1
    return tc_count, edge_count


def _check_max_hold(pos: dict, is_edge: bool, limits: dict) -> dict:
    """
    Check if a position has exceeded its max hold period.
    Only exits if P&L is positive — never forces a loss.
    """
    entry_date_str = pos.get("entry_date")
    if not entry_date_str:
        return {"should_exit": False}

    max_days = limits.get("max_hold_days_edge", 14) if is_edge else limits.get("max_hold_days_tc", 30)
    entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
    days_held = (datetime.now().date() - entry_date).days

    if days_held >= max_days:
        current_price = get_latest_price(pos.get("ticker", ""))
        if current_price:
            pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
            if pnl_pct > 0:
                return {
                    "should_exit": True,
                    "reason": f"MAX_HOLD ({days_held} days | +{pnl_pct:.1f}%)"
                }
            else:
                logger.info(f"Max hold reached but P&L negative ({pnl_pct:.1f}%) — letting stop loss handle it")

    return {"should_exit": False}


def load_portfolio_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load portfolio state: {e}")
    return {
        "cash": 300.0,
        "starting_capital": 300.0,
        "positions": {},
        "last_updated": str(datetime.now())
    }


def save_portfolio_state(state: dict):
    try:
        state["last_updated"] = str(datetime.now())
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)  # atomic on POSIX — no partial-write risk
    except Exception as e:
        logger.error(f"Failed to save portfolio state: {e}")


def get_portfolio_value(state: dict) -> float:
    total = state["cash"]
    for ticker, pos in state["positions"].items():
        price = get_latest_price(ticker)
        if price and price == price:  # nan check
            total += pos["shares"] * price
    return round(total, 2)


def get_recently_sold_tickers(hours: int = 4) -> set:
    """Return tickers sold in the last X hours — prevents immediate re-entry after stop-loss."""
    from database.db import get_connection
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT ticker FROM trades
                   WHERE status = 'CLOSED' AND paper = 0
                   AND closed_at >= ?""",
                (cutoff,)
            ).fetchall()
        return {r["ticker"] for r in rows}
    except Exception as e:
        logger.warning(f"Could not fetch recently sold tickers: {e}")
        return set()


def run_scan(watchlist: list) -> list:
    if not is_trading_day():
        logger.info("Weekend — run_scan skipped (markets closed)")
        return []

    paper = _is_paper_mode()
    mode_label = "PAPER" if paper else "LIVE"
    limits = _get_risk_limits()

    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    cash = state["cash"]
    actions = []

    _now = datetime.now()
    _hour = _now.hour
    _in_market_hours = (8 <= _hour < 21)

    logger.info(f"Starting scan [{mode_label}] | Portfolio=£{portfolio_value:.2f} | Cash=£{cash:.2f}")

    portfolio_value = get_portfolio_value(state)
    if portfolio_value <= state["cash"]:
        logger.warning("Portfolio value equals cash — prices likely unavailable, skipping kill switch check")
        kill = {"active": False, "reason": "Prices unavailable — kill switch skipped"}
    else:
        kill = is_kill_switch_active(
            max_drawdown_pct=8.0,
            daily_loss_pct=3.0,
            starting_capital=state["starting_capital"]
        )

    if kill["active"]:
        logger.critical(f"KILL SWITCH ACTIVE — {kill['reason']} — No trades will be placed.")
        return [{"action": "KILL_SWITCH", "reason": kill["reason"]}]

    # ── CHOPPY regime gate — block new entries, exits still fire ─────────────
    current_regime = get_market_regime()
    choppy_mode = (current_regime == "CHOPPY")
    if choppy_mode:
        logger.info("Market regime CHOPPY — new entries blocked, exits still active")

    # ── Monitor Existing Positions ────────────────────────────────────────────
    for ticker, pos in list(state["positions"].items()):
        current_price = get_latest_price(ticker)
        if not current_price or current_price != current_price:  # nan check
            continue

        if not _in_market_hours:
            logger.info(f"Skipping exit check for {ticker} — outside market hours")
            continue

        highest_price = pos.get("highest_price", pos["entry_price"])
        if current_price > highest_price:
            highest_price = current_price
            state["positions"][ticker]["highest_price"] = highest_price
            logger.debug(f"New high for {ticker}: £{highest_price:.2f}")

        # ── Apply correct risk rules based on source ───────────────────────
        is_edge = pos.get("source") == "EdgeScanner"
        stop_loss_pct = limits.get("edge_stop_loss_pct", 8.0) if is_edge else limits.get("stop_loss_pct", 5.0)
        take_profit_pct = limits.get("edge_take_profit_pct", 40.0) if is_edge else limits.get("take_profit_pct", 15.0)

        logger.info(f"Checking {ticker} | Price=£{current_price:.2f} | Entry=£{pos['entry_price']:.2f} | High=£{highest_price:.2f} | {'EDGE' if is_edge else 'TC'}")

        # ── Max hold check (runs before TP/SL) ────────────────────────────
        pos["ticker"] = ticker
        max_hold = _check_max_hold(pos, is_edge, limits)
        if max_hold["should_exit"]:
            exit_check = {
                "should_exit": True,
                "reason": max_hold["reason"],
                "pnl_pct": round(((current_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2)
            }
        else:
            min_hold = limits.get("min_hold_days_momentum", 3) if pos.get("signal_type") == "MOMENTUM" else 0
            exit_check = check_exit_conditions(
                        current_price=current_price,
                        entry_price=pos["entry_price"],
                        stop_loss_pct=stop_loss_pct,
                        take_profit_pct=take_profit_pct,
                        highest_price=highest_price,
                        edge_tightening_trail=is_edge,
                        min_hold_days=min_hold,
                        entry_date=pos.get("entry_date")
            )

        if exit_check["should_exit"]:
            shares = pos["shares"]
            sell_value = shares * current_price
            pnl = sell_value - (shares * pos["entry_price"])

            # ── LIVE: Place real sell order ────────────────────────────────
            if not paper:
                logger.info(f"LIVE SELL: {ticker} | {shares:.6f} shares | Reason={exit_check['reason']}")
                broker = _get_broker()
                order_result = broker.place_sell_order(ticker, shares)

                if "error" in order_result:
                    error_msg = str(order_result['error'])
                    logger.error(f"LIVE SELL FAILED for {ticker}: {error_msg}")

                    silent_errors = [
                        "whole shares but position size too small",
                        "insufficient-free-for-stocks-buy",
                        "Insufficient funds",
                    ]
                    is_silent = any(e in error_msg for e in silent_errors)

                    if not is_silent:
                        from notifications.telegram import send_message
                        send_message(
                            f"🚨 <b>LIVE SELL FAILED</b>\n\n"
                            f"<b>Stock:</b> {ticker}\n"
                            f"<b>Shares:</b> {shares:.6f}\n"
                            f"<b>Error:</b> {error_msg}\n\n"
                            f"⚡ TradeCore LIVE"
                        )
                    continue
                else:
                    logger.info(f"LIVE SELL CONFIRMED: {ticker} | Order ID={order_result.get('id', 'unknown')}")
                    trade_id = pos.get("trade_id")
                    if trade_id:
                        close_trade(trade_id, pnl, exit_check["reason"])
                    else:
                        logger.warning(f"No trade_id for {ticker} — skipping DB close")
                    from monitoring.health_monitor import reconcile_state_from_t212
                    reconcile_state_from_t212()
                    state = load_portfolio_state()
                    cash = state["cash"]
                    actions.append({
                        "action": "SELL",
                        "ticker": ticker,
                        "price": current_price,
                        "shares": shares,
                        "sell_value": round(sell_value, 2),
                        "pnl": round(pnl, 2),
                        "reason": exit_check["reason"]
                    })
                    continue

            # ── PAPER: Update state manually ───────────────────────────────
            cash += sell_value
            state["cash"] = cash
            del state["positions"][ticker]

            trade_id = pos.get("trade_id")
            if trade_id:
                close_trade(trade_id, pnl, exit_check["reason"])
            else:
                logger.warning(f"No trade_id for {ticker} — skipping DB close, position removed from state")

            actions.append({
                "action": "SELL",
                "ticker": ticker,
                "price": current_price,
                "shares": shares,
                "sell_value": round(sell_value, 2),
                "pnl": round(pnl, 2),
                "reason": exit_check["reason"]
            })
            logger.info(f"SELL {ticker} [{mode_label}] | {exit_check['reason']} | P&L=£{pnl:.2f} ({exit_check['pnl_pct']:.1f}%)")

    # ── Scan For New Signals ──────────────────────────────────────────────────
    open_tickers = list(state["positions"].keys())
    recently_sold = get_recently_sold_tickers(hours=4)

    from signals.mean_reversion import MeanReversionSignal
    from signals.breakout import BreakoutSignal
    from signals.earnings_drift import EarningsDriftSignal
    from data.earnings_calendar import is_earnings_safe, had_recent_earnings

    signal_engine = MomentumSignal()
    reversion_engine = MeanReversionSignal()
    breakout_engine = BreakoutSignal()
    drift_engine = EarningsDriftSignal()

    tc_max = _get_tc_max_positions()
    edge_max = _get_edge_max_positions()

    for stock in watchlist:
        ticker = stock["ticker"]
        is_edge = stock.get("source") == "EdgeScanner"

        if ticker in open_tickers:
                    continue
        open_db_trades = get_open_trades(paper=0)
        if any(row["ticker"] == ticker for row in open_db_trades):
                    logger.info(f"Skipping {ticker} — open trade already exists in DB")
                    continue

        if ticker in recently_sold:
            logger.info(f"Skipping {ticker} — sold within last 4 hours (cooldown)")
            continue
        if choppy_mode:
            logger.info(f"Skipping {ticker} — CHOPPY regime, no new entries")
            continue

        # ── Slot check — TC and EdgeScanner slots tracked separately ──────
        # Use open_tickers for accurate in-loop slot counting
        current_positions = {t: state["positions"].get(t, {}) for t in open_tickers}
        tc_count, edge_count = _count_positions_by_source(current_positions, watchlist)

        if is_edge:
            if edge_count >= edge_max:
                logger.info(f"EdgeScanner slots full ({edge_count}/{edge_max}) — skipping {ticker}")
                continue
        else:
            if tc_count >= tc_max:
                logger.info(f"TradeCore slots full ({tc_count}/{tc_max}) — skipping {ticker}")
                continue

        if cash < CASH_FLOOR:
            logger.info("Insufficient cash for new positions.")
            break

        df = get_historical_data(ticker, period="1y")
        if df is None or df.empty:
            continue

        current_price = get_latest_price(ticker)
        if not current_price or current_price != current_price:
            continue

        # ── Earnings Drift — paper only, evaluated independently ──────────
        if had_recent_earnings(ticker, days=2):
            raw_drift = drift_engine.evaluate(ticker, df)
            if raw_drift.direction == "BUY" and raw_drift.confidence >= EARNINGS_DRIFT_MIN_CONFIDENCE:
                logger.info(f"📊 PAPER DRIFT: {ticker} | Conf={raw_drift.confidence:.1f}% | {raw_drift.notes}")
                insert_signal(
                    ticker=ticker,
                    signal_type="EARNINGS_DRIFT_PAPER",
                    direction=raw_drift.direction,
                    confidence=raw_drift.confidence,
                    price=current_price,
                    regime=None,
                    notes=f"[PAPER] {raw_drift.notes}"
                )
                from notifications.telegram import send_earnings_drift_alert
                send_earnings_drift_alert(
                    ticker=ticker,
                    price=current_price,
                    confidence=raw_drift.confidence,
                    notes=raw_drift.notes
                )

        # ── Standard signal pipeline ──────────────────────────────────────
        raw_momentum = signal_engine.evaluate(ticker, df)
        raw_reversion = reversion_engine.evaluate(ticker, df)
        raw_breakout = breakout_engine.evaluate(ticker, df)

        if BREAKOUT_PAPER_ONLY and raw_breakout.direction == "BUY" and raw_breakout.confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
            logger.info(f"📋 PAPER BREAKOUT: {ticker} | {raw_breakout.direction} | Conf={raw_breakout.confidence:.1f}%")
            insert_signal(
                ticker=ticker,
                signal_type="BREAKOUT_PAPER",
                direction=raw_breakout.direction,
                confidence=raw_breakout.confidence,
                price=current_price,
                regime=None,
                notes=f"[PAPER] {raw_breakout.notes}"
            )
            from notifications.telegram import send_breakout_paper_alert
            send_breakout_paper_alert(
                ticker=ticker,
                price=current_price,
                confidence=raw_breakout.confidence,
                notes=raw_breakout.notes
            )

        if raw_reversion.confidence > raw_momentum.confidence:
            raw_signal = raw_reversion
        else:
            raw_signal = raw_momentum

        if not BREAKOUT_PAPER_ONLY and raw_breakout.confidence > raw_signal.confidence:
            raw_signal = raw_breakout

        final_signal = score_signal(raw_signal, df, paper=paper)
        logger.info(f"{ticker} | {final_signal.direction} | Conf={final_signal.confidence:.1f}%")

        if not final_signal.is_actionable(DEFAULT_CONFIDENCE_THRESHOLD):
            continue
        if final_signal.direction != "BUY":
            continue

        if not is_earnings_safe(ticker):
            logger.info(f"Earnings approaching for {ticker} — skipping entry")
            continue

        # ── Correlation check — skip for EdgeScanner stocks ───────────────
        if not is_edge:
            corr_check = is_too_correlated(ticker, open_tickers)
            if corr_check["blocked"]:
                cash_pct_of_portfolio = (cash / portfolio_value) * 100
                high_confidence = final_signal.confidence >= CASH_DEPLOYMENT_MIN_CONFIDENCE
                cash_idle = cash_pct_of_portfolio >= CASH_DEPLOYMENT_THRESHOLD_PCT

                if cash_idle and high_confidence:
                    logger.info(f"Cash deployment override — Cash={cash_pct_of_portfolio:.1f}% | Conf={final_signal.confidence:.1f}% — Overriding correlation block for {ticker}")
                else:
                    logger.info(f"Correlation block: {corr_check['reason']}")
                    continue

        # ── Position sizing — EdgeScanner uses separate pct ───────────────
        if is_edge:
            edge_max_pct = limits.get("edge_max_position_pct", 8.0) / 100
            invest_amount = min(portfolio_value * edge_max_pct, cash * 0.95)
            if invest_amount < CASH_FLOOR:
                logger.info(f"EdgeScanner position too small for {ticker} — skipping")
                continue
            shares = round(invest_amount / current_price, 6)
            size = {
                "approved": True,
                "invest_amount": round(invest_amount, 2),
                "shares": shares,
                "reason": f"EdgeScanner sizing ({edge_max_pct*100:.0f}% of portfolio)"
            }
        else:
            size = calculate_position_size(
                portfolio_value=portfolio_value,
                cash_available=cash,
                current_price=current_price,
                confidence=final_signal.confidence
            )

        if not size["approved"]:
            logger.info(f"Position rejected: {size['reason']}")
            continue

        if not paper:
            logger.info(f"LIVE BUY: {ticker} | {size['shares']:.6f} shares | £{size['invest_amount']:.2f} | {'EDGE' if is_edge else 'TC'}")
            broker = _get_broker()
            order_result = broker.place_buy_order(ticker, size["shares"])

            if "error" in order_result:
                logger.error(f"LIVE BUY FAILED for {ticker}: {order_result['error']}")
                from notifications.telegram import send_message
                send_message(
                    f"🚨 <b>LIVE BUY FAILED</b>\n\n"
                    f"<b>Stock:</b> {ticker}\n"
                    f"<b>Shares:</b> {size['shares']:.6f}\n"
                    f"<b>Amount:</b> £{size['invest_amount']:.2f}\n"
                    f"<b>Error:</b> {order_result['error']}\n\n"
                    f"⚡ TradeCore LIVE"
                )
                continue
            else:
                logger.info(f"LIVE BUY CONFIRMED: {ticker} | Order ID={order_result.get('id', 'unknown')}")
                from monitoring.health_monitor import reconcile_state_from_t212
                reconcile_state_from_t212()
                # ── FIX: Mark slot as filled IMMEDIATELY to prevent duplicate buys ──
                state["positions"][ticker] = {
                    "shares": size["shares"],
                    "entry_price": current_price,
                    "highest_price": current_price,
                    "trade_id": None,
                    "invested": size["invest_amount"],
                    "source": "EdgeScanner" if is_edge else "TradeCore",
                    "entry_date": str(datetime.now().date()),
            "signal_type": final_signal.signal_type
                }
                open_tickers.append(ticker)
                save_portfolio_state(state)

        signal_id = insert_signal(
            ticker=ticker,
            signal_type=final_signal.signal_type,
            direction="BUY",
            confidence=final_signal.confidence,
            price=current_price,
            regime=final_signal.regime,
            notes=final_signal.notes
        )

        trade_id = insert_trade(
            signal_id=signal_id,
            ticker=ticker,
            direction="BUY",
            quantity=size["shares"],
            price=current_price,
            paper=1 if paper else 0
        )

        cash -= size["invest_amount"]
        state["cash"] = cash
        state["positions"][ticker] = {
            "shares": size["shares"],
            "entry_price": current_price,
            "highest_price": current_price,
            "trade_id": trade_id,
            "invested": size["invest_amount"],
            "source": "EdgeScanner" if is_edge else "TradeCore",
            "entry_date": str(datetime.now().date())
        }
        open_tickers.append(ticker)

        actions.append({
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence
        })
        logger.info(f"BUY {ticker} [{mode_label}] | £{size['invest_amount']:.2f} | {size['shares']} shares @ £{current_price:.2f} | {'EDGE' if is_edge else 'TC'}")

    # ── Save State + Snapshot ─────────────────────────────────────────────────
    portfolio_value = get_portfolio_value(state)
    save_portfolio_state(state)

    insert_snapshot(
        snapshot_date=str(datetime.now().date()),
        total_value=portfolio_value,
        cash_balance=cash,
        invested_value=portfolio_value - cash,
        paper=0
    )

    logger.info(f"Scan complete [{mode_label}] | {len(actions)} actions | Portfolio=£{portfolio_value:.2f}")
    return actions