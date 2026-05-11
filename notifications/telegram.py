import logging
import requests
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(message: str) -> bool:
    """
    Send a plain text message to the TradeCore Telegram chat.

    Args:
        message: Text to send

    Returns:
        True if successful, False otherwise
    """
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )
        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram send failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def send_trade_alert(action: str, ticker: str, price: float,
                     shares: float, amount: float,
                     confidence: float = None, pnl: float = None,
                     reason: str = None) -> bool:
    """
    Send a trade execution alert.

    Args:
        action:     BUY or SELL
        ticker:     Stock ticker
        price:      Execution price
        shares:     Number of shares
        amount:     Total value in GBP
        confidence: Signal confidence (BUY only)
        pnl:        Profit/loss (SELL only)
        reason:     Exit reason (SELL only)
    """
    if action == "BUY":
        emoji = "🟢"
        lines = [
            f"{emoji} <b>TRADE EXECUTED — BUY</b>",
            f"",
            f"<b>Stock:</b> {ticker}",
            f"<b>Price:</b> £{price:.2f}",
            f"<b>Shares:</b> {shares:.4f}",
            f"<b>Invested:</b> £{amount:.2f}",
            f"<b>Confidence:</b> {confidence:.1f}%" if confidence else "",
            f"",
            f"⚡ TradeCore Paper Mode"
        ]
    else:
        emoji = "🔴" if (pnl or 0) < 0 else "💰"
        pnl_str = f"+£{pnl:.2f}" if pnl >= 0 else f"-£{abs(pnl):.2f}"
        lines = [
            f"{emoji} <b>TRADE EXECUTED — SELL</b>",
            f"",
            f"<b>Stock:</b> {ticker}",
            f"<b>Price:</b> £{price:.2f}",
            f"<b>Shares:</b> {shares:.4f}",
            f"<b>Value:</b> £{amount:.2f}",
            f"<b>P&L:</b> {pnl_str}" if pnl is not None else "",
            f"<b>Reason:</b> {reason}" if reason else "",
            f"",
            f"⚡ TradeCore Paper Mode"
        ]

    message = "\n".join(l for l in lines if l is not None)
    return send_message(message)

def send_daily_report(portfolio_value: float, cash: float,
                      total_pnl: float, daily_pnl: float,
                      open_positions: int, trades_today: int,
                      positions: dict = None) -> bool:
    """Send the end of day performance report."""
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    daily_emoji = "▲" if daily_pnl >= 0 else "▼"
    pnl_str = f"+£{total_pnl:.2f}" if total_pnl >= 0 else f"-£{abs(total_pnl):.2f}"
    daily_str = f"+£{daily_pnl:.2f}" if daily_pnl >= 0 else f"-£{abs(daily_pnl):.2f}"

    message = (
        f"{pnl_emoji} <b>TRADECORE DAILY REPORT</b>\n"
        f"\n"
        f"<b>Portfolio Value:</b> £{portfolio_value:,.2f}\n"
        f"<b>Total P&L:</b> {pnl_str}\n"
        f"<b>Today:</b> {daily_emoji} {daily_str}\n"
        f"<b>Cash Available:</b> £{cash:,.2f}\n"
        f"<b>Open Positions:</b> {open_positions}\n"
        f"<b>Trades Today:</b> {trades_today}\n"
    )

    # Add position breakdown if provided
    if positions:
        message += f"\n<b>Positions:</b>\n"
        for ticker, pos in positions.items():
            from data.price_feed import get_latest_price
            current_price = get_latest_price(ticker)
            if current_price:
                pnl = (current_price - pos["entry_price"]) * pos["shares"]
                pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
                arrow = "▲" if pnl >= 0 else "▼"
                message += (f"  {arrow} {ticker} "
                           f"£{pnl:+.2f} ({pnl_pct:+.1f}%)\n")

    message += f"\n⚡ TradeCore Paper Mode"
    return send_message(message)

def send_kill_switch_alert(reason: str) -> bool:
    """Send an urgent kill switch notification."""
    message = (
        f"🚨 <b>KILL SWITCH ACTIVATED</b>\n"
        f"\n"
        f"<b>Reason:</b> {reason}\n"
        f"\n"
        f"All trading has been halted.\n"
        f"Review the dashboard immediately.\n"
        f"\n"
        f"⚡ TradeCore"
    )
    return send_message(message)


def send_signal_summary(signals: list) -> bool:
    """
    Send a pre-market signal summary.

    Args:
        signals: List of dicts with ticker, direction, confidence
    """
    buy_signals = [s for s in signals if s["direction"] == "BUY"]
    sell_signals = [s for s in signals if s["direction"] == "SELL"]
    watch_signals = [s for s in signals if s["direction"] == "WATCH"]

    lines = [
        f"📡 <b>TRADECORE SIGNAL SUMMARY</b>",
        f"<i>Market scan complete</i>",
        f"",
    ]

    if buy_signals:
        lines.append("🟢 <b>BUY Signals:</b>")
        for s in sorted(buy_signals,
                       key=lambda x: x['confidence'],
                       reverse=True):
            bar = "█" * int(s['confidence'] / 10)
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%  {bar}")
        lines.append("")

    if sell_signals:
        lines.append("🔴 <b>SELL Signals:</b>")
        for s in sorted(sell_signals,
                       key=lambda x: x['confidence'],
                       reverse=True):
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%")
        lines.append("")

    if watch_signals:
        lines.append("🟡 <b>Watching:</b>")
        for s in sorted(watch_signals,
                       key=lambda x: x['confidence'],
                       reverse=True):
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%")
        lines.append("")

    lines.append(f"⚡ TradeCore Paper Mode")
    return send_message("\n".join(lines))