"""
EdgeScanner paper-testing pathway.

HARD INVARIANT: this module must NEVER place a real T212 order.
It only writes to the database, its own state file, and Telegram.
Never import any broker module here. Verify with:
    grep -iE "t212|broker" execution/edge_paper.py   -> should only match this comment
"""
import json
import logging
import os
from datetime import datetime

from data.price_feed import get_latest_price
from database.queries import insert_signal, insert_trade, close_trade
from risk.stop_loss_engine import check_exit_conditions

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "portfolio_state_edge_paper.json")

STARTING_CAPITAL = 10000.0
POSITION_PCT = 8.0    # matches live edge_max_position_pct
MAX_HOLD_DAYS = 14    # matches live max_hold_days_edge


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Edge paper state load failed: {e}")
    return {"cash": STARTING_CAPITAL, "starting_capital": STARTING_CAPITAL, "positions": {}}


def save_state(state: dict):
    """Atomic write — .tmp then os.replace, so a crash can't corrupt the file."""
    state["last_updated"] = str(datetime.now())
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def record_entry(ticker: str, price: float, confidence: float, notes: str = "") -> bool:
    """Open a simulated Edge paper position. Returns True if opened."""
    state = load_state()

    # Natural dedupe — one open position per ticker, state is the gatekeeper
    if ticker in state["positions"]:
        logger.info(f"EDGE PAPER: {ticker} already open — skipping")
        return False

    # Portfolio value = cash + current value of open paper positions
    portfolio_value = state["cash"]
    for t, pos in state["positions"].items():
        p = get_latest_price(t)
        if p and p == p:  # nan check
            portfolio_value += pos["shares"] * p

    invest = round(min(portfolio_value * POSITION_PCT / 100, state["cash"] * 0.95), 2)
    if invest < 20.0:
        logger.info(f"EDGE PAPER: not enough simulated cash for {ticker}")
        return False

    shares = round(invest / price, 6)

    signal_id = insert_signal(
        ticker=ticker,
        signal_type="EDGE_PAPER",
        direction="BUY",
        confidence=confidence,
        price=price,
        regime=None,
        notes=f"[EDGE PAPER] {notes}"
    )
    trade_id = insert_trade(
        signal_id=signal_id,
        ticker=ticker,
        direction="BUY",
        quantity=shares,
        price=price,
        paper=1
    )

    state["cash"] = round(state["cash"] - invest, 2)
    state["positions"][ticker] = {
        "shares": shares,
        "entry_price": price,
        "highest_price": price,
        "trade_id": trade_id,  # always populated — DB close depends on it (LLY lesson)
        "invested": invest,
        "entry_date": str(datetime.now().date()),
        "signal_type": "EDGE_PAPER"
    }
    save_state(state)

    from notifications.telegram import send_message
    send_message(
        f"\U0001F4CB <b>EDGE PAPER BUY</b>\n\n"
        f"<b>Stock:</b> {ticker}\n"
        f"<b>Price:</b> \u00a3{price:.2f}\n"
        f"<b>Shares:</b> {shares}\n"
        f"<b>Amount:</b> \u00a3{invest:.2f}\n"
        f"<b>Confidence:</b> {confidence:.1f}%\n\n"
        f"\U0001F4CB Paper test \u2014 no real money"
    )
    logger.info(f"EDGE PAPER BUY: {ticker} | \u00a3{invest:.2f} @ \u00a3{price:.2f} | Conf={confidence:.1f}%")
    return True


def monitor_positions():
    """
    Apply Edge exit rules (tightening trail, no hard TP, max-hold-if-profit)
    to open paper positions. Called every 15 mins from job_monitor_positions,
    which already gates weekends and market hours.
    """
    state = load_state()
    if not state["positions"]:
        return

    for ticker, pos in list(state["positions"].items()):
        price = get_latest_price(ticker)  # has the Volume=0 stale-data guard
        if not price or price != price:
            continue

        if price > pos.get("highest_price", pos["entry_price"]):
            pos["highest_price"] = price
            state["positions"][ticker] = pos
            save_state(state)

        exit_check = check_exit_conditions(
            current_price=price,
            entry_price=pos["entry_price"],
            highest_price=pos["highest_price"],
            edge_tightening_trail=True
        )

        # Max hold — only exits at a profit, same as live Edge rules
        if not exit_check["should_exit"]:
            entry = datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()
            days_held = (datetime.now().date() - entry).days
            if days_held >= MAX_HOLD_DAYS and exit_check["pnl_pct"] > 0:
                exit_check = {
                    "should_exit": True,
                    "reason": f"MAX_HOLD ({days_held}d | +{exit_check['pnl_pct']:.1f}%)",
                    "pnl_pct": exit_check["pnl_pct"]
                }

        if not exit_check["should_exit"]:
            continue

        sell_value = pos["shares"] * price
        pnl = round(sell_value - pos["invested"], 2)

        close_trade(pos["trade_id"], pnl, exit_check["reason"])
        state["cash"] = round(state["cash"] + sell_value, 2)
        del state["positions"][ticker]
        save_state(state)

        from notifications.telegram import send_message
        send_message(
            f"\U0001F4CB <b>EDGE PAPER EXIT</b>\n\n"
            f"<b>Stock:</b> {ticker}\n"
            f"<b>Price:</b> \u00a3{price:.2f}\n"
            f"<b>P&L:</b> \u00a3{pnl:.2f} ({exit_check['pnl_pct']:.1f}%)\n"
            f"<b>Reason:</b> {exit_check['reason']}\n\n"
            f"\U0001F4CB Paper test \u2014 no real money"
        )
        logger.info(f"EDGE PAPER EXIT: {ticker} | {exit_check['reason']} | P&L=\u00a3{pnl:.2f}")