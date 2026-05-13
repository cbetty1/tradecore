import logging
import json
import os
from datetime import datetime
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
            "max_open_positions": 20,
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


def run_paper_scan() -> dict:
    """
    Run the daily 600-stock paper scanner.
    Completely independent from live trading — separate state,
    separate config, separate watchlist.

    Returns:
        Dict with scan results for Telegram summary
    """
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

    # ── Scan for new paper entries ─────────────────────────────────────────
    open_tickers = list(state["positions"].keys())
    scanned = 0
    signals_fired = 0

    for stock in watchlist:
        ticker = stock["ticker"]

        if ticker in open_tickers:
            continue

        if len(state["positions"]) >= max_positions:
            logger.info(f"Paper max positions ({max_positions}) reached")
            break

        if cash < cash_floor:
            logger.info("Paper cash floor reached")
            break

        try:
            df = get_historical_data(ticker, period="1y")
            if df is None or df.empty:
                continue

            current_price = get_latest_price(ticker)
            if not current_price:
                continue

            scanned += 1

            # Evaluate all three signals
            raw_momentum = momentum_engine.evaluate(ticker, df)
            raw_reversion = reversion_engine.evaluate(ticker, df)
            raw_breakout = breakout_engine.evaluate(ticker, df)

            # Pick highest confidence signal
            best_raw = max(
                [raw_momentum, raw_reversion, raw_breakout],
                key=lambda s: s.confidence
            )

            # Track all actionable signals for daily summary
            if best_raw.confidence >= min_confidence and best_raw.direction == "BUY":
                signals_fired += 1
                top_signals.append({
                    "ticker": ticker,
                    "signal_type": best_raw.signal_type,
                    "confidence": best_raw.confidence,
                    "price": current_price,
                    "direction": best_raw.direction
                })

            # Apply confidence scorer
            final_signal = score_signal(best_raw, df)

            if not final_signal.is_actionable(min_confidence):
                continue
            if final_signal.direction != "BUY":
                continue

            # Correlation check
            corr_check = is_too_correlated(
                ticker, open_tickers,
                correlation_limit=correlation_limit
            )
            if corr_check["blocked"]:
                cash_pct = (cash / portfolio_value) * 100
                if not (cash_pct >= limits["cash_deployment_threshold_pct"] and
                        final_signal.confidence >= limits["cash_deployment_min_confidence"]):
                    continue

            # Position sizing
            size = calculate_position_size(
                portfolio_value=portfolio_value,
                cash_available=cash,
                current_price=current_price,
                confidence=final_signal.confidence,
                max_position_pct=limits["max_position_pct"] / 100
            )

            if not size["approved"]:
                continue

            # Log to database as paper trade
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

            # Update paper state
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

        except Exception as e:
            errors += 1
            logger.warning(f"Paper scan error for {ticker}: {e}")
            continue

    # ── Save state and snapshot ────────────────────────────────────────────
    portfolio_value = get_paper_portfolio_value(state)
    save_paper_state(state)

    insert_snapshot(
        snapshot_date=str(datetime.now().date()),
        total_value=portfolio_value,
        cash_balance=cash,
        invested_value=portfolio_value - cash
    )

    total_pnl = portfolio_value - starting_capital
    total_pnl_pct = (total_pnl / starting_capital) * 100

    logger.info(f"=== PAPER SCAN COMPLETE ===")
    logger.info(f"Scanned: {scanned} | Signals: {signals_fired} | "
               f"Buys: {len(buys)} | Sells: {len(sells)} | Errors: {errors}")
    logger.info(f"Paper Portfolio: £{portfolio_value:.2f} | P&L: £{total_pnl:.2f} ({total_pnl_pct:.2f}%)")

    # Sort top signals by confidence for summary
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