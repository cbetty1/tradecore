import logging
import json
import os
from datetime import datetime
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
EARNINGS_DRIFT_PAPER_ONLY = True  # Paper only until signal proves itself
EARNINGS_DRIFT_MIN_CONFIDENCE = 70.0  # Higher bar — catalyst-driven, we want conviction


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

def _get_max_positions() -> int:
    try:
        with open(RISK_LIMITS_FILE) as f:
            return json.load(f).get("max_open_positions", 5)
    except Exception:
        return 5

def _get_broker():
    from execution.t212_broker import T212Broker
    return T212Broker()


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
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save portfolio state: {e}")


def get_portfolio_value(state: dict) -> float:
    total = state["cash"]
    for ticker, pos in state["positions"].items():
        price = get_latest_price(ticker)
        if price and price == price:  # nan check
            total += pos["shares"] * price
    return round(total, 2)


def run_scan(watchlist: list) -> list:
    if not is_trading_day():
        logger.info("Weekend — run_scan skipped (markets closed)")
        return []

    paper = _is_paper_mode()
    mode_label = "PAPER" if paper else "LIVE"

    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    cash = state["cash"]
    actions = []

    _now = datetime.now()
    _hour = _now.hour
    _minute = _now.minute
    _in_market_hours = ((8 <= _hour < 21))

    logger.info(f"Starting scan [{mode_label}] | Portfolio=£{portfolio_value:.2f} | Cash=£{cash:.2f}")

    kill = is_kill_switch_active(
        max_drawdown_pct=8.0,
        daily_loss_pct=3.0,
        starting_capital=state["starting_capital"]
    )
    if kill["active"]:
        logger.critical(f"KILL SWITCH ACTIVE — {kill['reason']} — No trades will be placed.")
        return [{"action": "KILL_SWITCH", "reason": kill["reason"]}]

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

        logger.info(f"Checking {ticker} | Price=£{current_price:.2f} | Entry=£{pos['entry_price']:.2f} | High=£{highest_price:.2f}")
        exit_check = check_exit_conditions(
            current_price=current_price,
            entry_price=pos["entry_price"],
            stop_loss_pct=5.0,
            take_profit_pct=15.0,
            highest_price=highest_price
        )

        if exit_check["should_exit"]:
            shares = pos["shares"]
            sell_value = shares * current_price
            pnl = sell_value - (shares * pos["entry_price"])

            # ── LIVE: Place real sell order ────────────────────────────────
            if not paper:
                logger.info(f"LIVE SELL: {ticker} | {shares:.6f} shares")
                broker = _get_broker()
                order_result = broker.place_sell_order(ticker, shares)

                if "error" in order_result:
                    error_msg = str(order_result['error'])
                    logger.error(f"LIVE BUY FAILED for {ticker}: {error_msg}")

                    silent_errors = [
                        "whole shares but position size too small",
                        "insufficient-free-for-stocks-buy",
                        "Insufficient funds",
                    ]
                    is_silent = any(e in error_msg for e in silent_errors)

                    if not is_silent:
                        from notifications.telegram import send_message
                        send_message(
                            f"🚨 <b>LIVE BUY FAILED</b>\n\n"
                            f"<b>Stock:</b> {ticker}\n"
                            f"<b>Shares:</b> {size['shares']:.6f}\n"
                            f"<b>Amount:</b> £{size['invest_amount']:.2f}\n"
                            f"<b>Error:</b> {error_msg}\n\n"
                            f"⚡ TradeCore LIVE"
                        )
                    continue
                else:
                    logger.info(f"LIVE SELL CONFIRMED: {ticker} | Order ID={order_result.get('id', 'unknown')}")
                    from notifications.telegram import send_trade_alert
                    send_trade_alert(
                        action="SELL",
                        ticker=ticker,
                        price=current_price,
                        shares=shares,
                        amount=round(sell_value, 2),
                        confidence=0,
                        pnl=round(pnl, 2)
                    )
                    from monitoring.health_monitor import reconcile_state_from_t212
                    reconcile_state_from_t212()
                    state = load_portfolio_state()
                    cash = state["cash"]
                    continue

            # ── PAPER: Update state manually ───────────────────────────────
            cash += sell_value
            state["cash"] = cash
            del state["positions"][ticker]

            trade_id = pos.get("trade_id")
            if trade_id:
                close_trade(trade_id, pnl)
            else:
                logger.warning(f"No trade_id for {ticker} — skipping DB close, position removed from state")

            action = {
                "action": "SELL",
                "ticker": ticker,
                "price": current_price,
                "shares": shares,
                "sell_value": round(sell_value, 2),
                "pnl": round(pnl, 2),
                "reason": exit_check["reason"]
            }
            actions.append(action)
            logger.info(f"SELL {ticker} [{mode_label}] | {exit_check['reason']} | P&L=£{pnl:.2f} ({exit_check['pnl_pct']:.1f}%)")

    # ── Scan For New Signals ──────────────────────────────────────────────────
    open_tickers = list(state["positions"].keys())
    from signals.mean_reversion import MeanReversionSignal
    from signals.breakout import BreakoutSignal
    from signals.earnings_drift import EarningsDriftSignal
    from data.earnings_calendar import is_earnings_safe, had_recent_earnings

    signal_engine = MomentumSignal()
    reversion_engine = MeanReversionSignal()
    breakout_engine = BreakoutSignal()
    drift_engine = EarningsDriftSignal()

    for stock in watchlist:
        ticker = stock["ticker"]

        if ticker in open_tickers:
            continue

        max_positions = _get_max_positions()
        if len(state["positions"]) >= max_positions:
            logger.info(f"Max positions ({max_positions}) reached — skipping new entries.")
            break

        if cash < CASH_FLOOR:
            logger.info("Insufficient cash for new positions.")
            break

        df = get_historical_data(ticker, period="1y")
        if df is None or df.empty:
            continue

        current_price = get_latest_price(ticker)
        if not current_price:
            continue

        # ── Earnings Drift — paper only, evaluated independently ──────────
        # Looks for stocks that had earnings in the last 1-2 days with a
        # confirmed gap + volume. Runs BEFORE the earnings safety skip below.
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

        # ── Standard signal pipeline (skips earnings window as before) ────
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

        final_signal = score_signal(raw_signal, df)
        logger.info(f"{ticker} | {final_signal.direction} | Conf={final_signal.confidence:.1f}%")

        if not final_signal.is_actionable(DEFAULT_CONFIDENCE_THRESHOLD):
            continue
        if final_signal.direction != "BUY":
            continue

        # Standard earnings safety check — still skips momentum entries near earnings
        if not is_earnings_safe(ticker):
            logger.info(f"Earnings approaching for {ticker} — skipping entry")
            continue

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
            logger.info(f"LIVE BUY: {ticker} | {size['shares']:.6f} shares | £{size['invest_amount']:.2f}")
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
            "invested": size["invest_amount"]
        }
        open_tickers.append(ticker)

        action = {
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence
        }
        actions.append(action)
        logger.info(f"BUY {ticker} [{mode_label}] | £{size['invest_amount']:.2f} | {size['shares']} shares @ £{current_price:.2f}")

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