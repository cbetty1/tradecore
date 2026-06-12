import logging
import json
import os
from datetime import datetime, timedelta
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import requests

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Read trading mode from risk_limits.json
RISK_LIMITS_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "risk_limits.json")


def _get_mode_label() -> str:
    """Return 'Live' or 'Paper Mode' based on risk_limits.json."""
    try:
        with open(RISK_LIMITS_FILE) as f:
            limits = json.load(f)
            return "Live" if not limits.get("paper_trading_mode", True) else "Paper Mode"
    except Exception:
        return "Paper Mode"


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
    mode = _get_mode_label()

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
            f"⚡ TradeCore {mode}"
        ]
    else:
        emoji = "🔴" if (pnl or 0) < 0 else "💰"
        pnl_str = f"+£{pnl:.2f}" if (pnl is not None and pnl >= 0) else f"-£{abs(pnl):.2f}" if pnl is not None else "N/A"
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
            f"⚡ TradeCore {mode}"
        ]

    message = "\n".join(l for l in lines if l is not None)
    return send_message(message)


def send_daily_report(portfolio_value: float, cash: float,
                      total_pnl: float, daily_pnl: float,
                      open_positions: int, trades_today: int,
                      positions: dict = None,
                      buys_today: int = 0, sells_today: int = 0) -> bool:
    """Send the end of day performance report."""
    mode = _get_mode_label()
    today = datetime.now().strftime("%A %d %B %Y")

    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    daily_emoji = "▲" if daily_pnl >= 0 else "▼"
    pnl_str = f"+£{total_pnl:.2f}" if total_pnl >= 0 else f"-£{abs(total_pnl):.2f}"
    daily_str = f"+£{daily_pnl:.2f}" if daily_pnl >= 0 else f"-£{abs(daily_pnl):.2f}"

    # Calculate total P&L percentage
    starting = portfolio_value - total_pnl
    pnl_pct = (total_pnl / starting * 100) if starting > 0 else 0.0
    pnl_pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"

    # Max positions from settings — read fresh from config to avoid stale import
    try:
        with open(RISK_LIMITS_FILE) as f:
            _limits = json.load(f)
        max_pos = _limits.get("max_open_positions", 5)
    except Exception:
        from config.settings import MAX_OPEN_POSITIONS
        max_pos = MAX_OPEN_POSITIONS

    message = (
        f"{pnl_emoji} <b>TRADECORE DAILY REPORT</b>\n"
        f"\n"
        f"<i>{today}</i>\n"
        f"\n"
        f"<b>Portfolio:</b> £{portfolio_value:,.2f}\n"
        f"<b>Total P&L:</b> {pnl_str} ({pnl_pct_str})\n"
        f"<b>Today:</b> {daily_emoji} {daily_str}\n"
        f"<b>Cash:</b> £{cash:,.2f}\n"
        f"<b>Positions:</b> {open_positions}/{max_pos}\n"
    )

    # Add position breakdown if provided
    if positions:
        message += f"\n<b>Open positions:</b>\n"
        for ticker, pos in positions.items():
            from data.price_feed import get_latest_price
            current_price = get_latest_price(ticker)
            if current_price:
                pnl = (current_price - pos["entry_price"]) * pos["shares"]
                pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
                arrow = "▲" if pnl >= 0 else "▼"
                pnl_display = f"+£{pnl:.2f}" if pnl >= 0 else f"-£{abs(pnl):.2f}"
                pnl_pct_display = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
                message += f"  {arrow} {ticker}  {pnl_display} ({pnl_pct_display})\n"

    # Trade count
    if buys_today > 0 or sells_today > 0:
        message += f"\n<b>Trades today:</b> {buys_today} buys | {sells_today} sells\n"
    else:
        message += f"\n<b>Trades today:</b> {trades_today}\n"

    # Withdrawable to date — single shared calculation
    withdrawal = _calc_withdrawal(total_pnl, portfolio_value)
    if total_pnl > 0:
        message += f"\n💰 <b>Withdrawable to date:</b> £{withdrawal['withdrawable']:,.2f}\n"

    message += f"\n⚡ TradeCore {mode}"
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


def send_signal_summary(signals: list, positions: dict = None) -> bool:
    mode = _get_mode_label()

    buy_signals = [s for s in signals if s["direction"] == "BUY"]
    sell_signals = [s for s in signals if s["direction"] == "SELL"]
    watch_signals = [s for s in signals if s["direction"] == "WATCH"]

    # Only show SELL signals for stocks you actually hold
    if positions:
        sell_signals = [s for s in sell_signals if s["ticker"] in positions]
        
    lines = [
        f"📡 <b>TRADECORE SIGNAL SUMMARY</b>",
        f"<i>Market scan complete</i>",
        f"",
    ]

    if buy_signals:
        lines.append("🟢 <b>BUY Signals:</b>")
        for s in sorted(buy_signals, key=lambda x: x['confidence'], reverse=True):
            bar = "█" * int(s['confidence'] / 10)
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%  {bar}")
        lines.append("")

    if sell_signals:
        lines.append("🔴 <b>SELL Signals:</b>")
        for s in sorted(sell_signals, key=lambda x: x['confidence'], reverse=True):
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%")
        lines.append("")

    if watch_signals:
        lines.append("🟡 <b>Watching:</b>")
        for s in sorted(watch_signals, key=lambda x: x['confidence'], reverse=True):
            lines.append(f"  • {s['ticker']} — {s['confidence']:.0f}%")
        lines.append("")

    lines.append(f"⚡ TradeCore {mode}")
    return send_message("\n".join(lines))


def _calc_withdrawal(total_pnl: float, portfolio_value: float) -> dict:
    """
    Calculate reinvest/withdraw split based on portfolio tiers.
    Under £500:    80% reinvest / 20% withdraw
    £500-£2,000:   60% reinvest / 40% withdraw
    £2,000+:       50% reinvest / 50% withdraw
    First withdrawal target: £1,000 withdrawable profit

    Single source of truth — both daily report and weekly summary use this.
    """
    if total_pnl <= 0:
        return {"reinvest_pct": 80, "withdraw_pct": 20,
                "reinvest": 0.0, "withdrawable": 0.0}

    if portfolio_value >= 2000:
        reinvest_pct, withdraw_pct = 50, 50
    elif portfolio_value >= 500:
        reinvest_pct, withdraw_pct = 60, 40
    else:
        reinvest_pct, withdraw_pct = 80, 20

    reinvest = round(total_pnl * (reinvest_pct / 100), 2)
    withdrawable = round(total_pnl * (withdraw_pct / 100), 2)

    return {
        "reinvest_pct": reinvest_pct,
        "withdraw_pct": withdraw_pct,
        "reinvest": reinvest,
        "withdrawable": withdrawable,
    }


def send_weekly_summary(portfolio_value: float, cash: float,
                        starting_capital: float,
                        weekly_pnl: float, total_pnl: float,
                        positions: dict = None,
                        buys_week: int = 0, sells_week: int = 0,
                        closed_wins: int = 0, closed_losses: int = 0,
                        avg_win: float = 0.0, avg_loss: float = 0.0,
                        signals_fired: int = 0, signals_acted: int = 0,
                        week_number: int = 1,
                        signal_attribution: dict = None) -> bool:
    """
    Send the weekly live performance summary — Friday 17:30.
    """
    mode = _get_mode_label()

    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    date_range = f"{week_start.strftime('%d %B')} — {today.strftime('%d %B %Y')}"

    weekly_pnl_str = f"+£{weekly_pnl:.2f}" if weekly_pnl >= 0 else f"-£{abs(weekly_pnl):.2f}"
    total_pnl_str = f"+£{total_pnl:.2f}" if total_pnl >= 0 else f"-£{abs(total_pnl):.2f}"

    weekly_pct = (weekly_pnl / (portfolio_value - weekly_pnl) * 100) if (portfolio_value - weekly_pnl) > 0 else 0.0
    total_pct = (total_pnl / starting_capital * 100) if starting_capital > 0 else 0.0

    weekly_pct_str = f"+{weekly_pct:.2f}%" if weekly_pct >= 0 else f"{weekly_pct:.2f}%"
    total_pct_str = f"+{total_pct:.2f}%" if total_pct >= 0 else f"{total_pct:.2f}%"

    lines = [
        f"📊 <b>TRADECORE WEEKLY SUMMARY</b>",
        f"",
        f"<i>Week of {date_range}</i>",
        f"",
        f"<b>Portfolio:</b> £{portfolio_value:,.2f} ({weekly_pnl_str})",
        f"<b>Weekly P&L:</b> {weekly_pnl_str} ({weekly_pct_str})",
        f"<b>Total P&L:</b> {total_pnl_str} ({total_pct_str})",
        f"<b>Cash:</b> £{cash:,.2f}",
    ]

    # Best / worst positions
    if positions:
        best_ticker = None
        worst_ticker = None
        best_pnl = -float('inf')
        worst_pnl = float('inf')
        best_pct = 0.0
        worst_pct = 0.0

        for ticker, pos in positions.items():
            from data.price_feed import get_latest_price
            current_price = get_latest_price(ticker)
            if current_price:
                pos_pnl = (current_price - pos["entry_price"]) * pos["shares"]
                pos_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
                if pos_pnl > best_pnl:
                    best_pnl = pos_pnl
                    best_pct = pos_pct
                    best_ticker = ticker
                if pos_pnl < worst_pnl:
                    worst_pnl = pos_pnl
                    worst_pct = pos_pct
                    worst_ticker = ticker

        if best_ticker:
            best_str = f"+£{best_pnl:.2f}" if best_pnl >= 0 else f"-£{abs(best_pnl):.2f}"
            best_pct_str = f"+{best_pct:.1f}%" if best_pct >= 0 else f"{best_pct:.1f}%"
            lines.append(f"")
            lines.append(f"<b>Best:</b>  ▲ {best_ticker}  {best_str} ({best_pct_str})")

        if worst_ticker and worst_ticker != best_ticker:
            worst_str = f"+£{worst_pnl:.2f}" if worst_pnl >= 0 else f"-£{abs(worst_pnl):.2f}"
            worst_pct_str = f"+{worst_pct:.1f}%" if worst_pct >= 0 else f"{worst_pct:.1f}%"
            lines.append(f"<b>Worst:</b> ▼ {worst_ticker}  {worst_str} ({worst_pct_str})")

    # Trade stats
    lines.append(f"")
    lines.append(f"<b>Trades:</b> {buys_week} buys | {sells_week} sells")

    total_closed = closed_wins + closed_losses
    if total_closed > 0:
        win_rate = (closed_wins / total_closed) * 100
        lines.append(f"<b>Win rate:</b> {closed_wins}/{total_closed} closed trades ({win_rate:.0f}%)")
        if avg_win > 0 or avg_loss > 0:
            avg_win_str = f"+£{avg_win:.2f}" if avg_win >= 0 else f"-£{abs(avg_win):.2f}"
            avg_loss_str = f"-£{abs(avg_loss):.2f}"
            lines.append(f"<b>Avg win:</b> {avg_win_str} | <b>Avg loss:</b> {avg_loss_str}")
    
    # Signal attribution — which signal type is performing best
    if signal_attribution:
        lines.append(f"")
        lines.append(f"<b>Signal performance:</b>")
        for sig_type, stats in signal_attribution.items():
            w = stats.get("wins", 0)
            l = stats.get("losses", 0)
            total = w + l
            if total > 0:
                wr = (w / total) * 100
                avg = stats.get("avg_pnl", 0.0)
                avg_str = f"+£{avg:.2f}" if avg >= 0 else f"-£{abs(avg):.2f}"
                lines.append(f"  • {sig_type}: {w}W/{l}L ({wr:.0f}%) avg {avg_str}")

    # Signal stats
    if signals_fired > 0:
        acted_pct = (signals_acted / signals_fired * 100) if signals_fired > 0 else 0
        lines.append(f"")
        lines.append(f"<b>Signals fired:</b> {signals_fired}")
        lines.append(f"<b>Signals acted on:</b> {signals_acted} ({acted_pct:.0f}%)")

    # Withdrawal breakdown — uses shared _calc_withdrawal for consistency
    withdrawal = _calc_withdrawal(total_pnl, portfolio_value)
    if total_pnl > 0:
        target = 1000.0
        progress_pct = min((withdrawal["withdrawable"] / target) * 100, 100)
        lines.append(f"")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"<b>Profit breakdown</b>")
        lines.append(f"<b>Starting capital:</b> £{starting_capital:,.2f}")
        lines.append(f"<b>Total profit:</b> {total_pnl_str}")
        lines.append(f"<b>Reinvesting ({withdrawal['reinvest_pct']}%):</b> £{withdrawal['reinvest']:,.2f}")
        lines.append(f"<b>Withdrawable ({withdrawal['withdraw_pct']}%):</b> £{withdrawal['withdrawable']:,.2f}")
        lines.append(f"")
        lines.append(f"<b>Total withdrawable to date:</b> £{withdrawal['withdrawable']:,.2f}")
        lines.append(f"🎯 <b>Target: £1,000</b>  ({progress_pct:.1f}% there)")

    lines.append(f"")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<b>Since go-live:</b> {total_pnl_str} ({total_pct_str})")
    lines.append(f"")
    lines.append(f"⚡ TradeCore {mode} — Week {week_number}")

    return send_message("\n".join(lines))


def send_breakout_paper_alert(ticker: str, price: float,
                              confidence: float, notes: str = "") -> bool:
    """
    Send a paper-only breakout signal alert to Telegram.
    These are for data collection — breakout is being tested, not traded live.
    """
    short_notes = notes[:200] if notes else ""

    message = (
        f"📋 <b>PAPER BREAKOUT SIGNAL</b>\n"
        f"\n"
        f"<b>Stock:</b> {ticker}\n"
        f"<b>Price:</b> £{price:.2f}\n"
        f"<b>Confidence:</b> {confidence:.1f}%\n"
        f"<b>Signal:</b> {short_notes}\n"
        f"\n"
        f"<i>Paper only — not traded. Collecting data for review.</i>\n"
        f"\n"
        f"📋 TradeCore PAPER BREAKOUT"
    )
    return send_message(message)


def send_paper_scan_summary(result: dict) -> bool:
    """
    Send the 600-stock paper scanner summary.
    Fires at 14:45 (US open) and 18:00 (mid US session) Monday to Friday.

    Args:
        result: Dict returned by run_paper_scan()
    """
    if not result:
        return send_message(
            "📋 <b>PAPER SCANNER</b>\n\n"
            "Scan failed — no results returned.\n\n"
            "📋 TradeCore Paper Scanner"
        )

    portfolio_value = result.get("portfolio_value", 0)
    cash = result.get("cash", 0)
    starting_capital = result.get("starting_capital", 10000)
    total_pnl = result.get("total_pnl", 0)
    total_pnl_pct = result.get("total_pnl_pct", 0)
    open_positions = result.get("open_positions", 0)
    max_positions = result.get("max_positions", 20)
    scanned = result.get("scanned", 0)
    signals_fired = result.get("signals_fired", 0)
    buys = result.get("buys", [])
    sells = result.get("sells", [])
    top_signals = result.get("top_signals", [])
    errors = result.get("errors", 0)

    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    pnl_str = f"+£{total_pnl:.2f}" if total_pnl >= 0 else f"-£{abs(total_pnl):.2f}"
    pnl_pct_str = f"+{total_pnl_pct:.2f}%" if total_pnl_pct >= 0 else f"{total_pnl_pct:.2f}%"

    scan_time = datetime.now().strftime("%H:%M")

    lines = [
        f"📋 <b>PAPER SCANNER — {scan_time} SCAN</b>",
        f"<i>{datetime.now().strftime('%A %d %B %Y')}</i>",
        f"",
        f"<b>Paper Portfolio:</b> £{portfolio_value:,.2f}",
        f"<b>Total P&L:</b> {pnl_str} ({pnl_pct_str}) {pnl_emoji}",
        f"<b>Cash:</b> £{cash:,.2f}",
        f"<b>Positions:</b> {open_positions}/{max_positions}",
        f"",
        f"<b>Scan stats:</b> {scanned} stocks | {signals_fired} signals fired",
    ]

    # New buys
    if buys:
        lines.append(f"")
        lines.append(f"🟢 <b>New paper positions ({len(buys)}):</b>")
        for b in buys:
            lines.append(
                f"  • {b['ticker']} @ £{b['price']:.2f} | "
                f"£{b['amount']:.2f} | {b['confidence']:.0f}% | {b['signal_type']}"
            )

    # Closed positions
    if sells:
        lines.append(f"")
        lines.append(f"🔴 <b>Closed paper positions ({len(sells)}):</b>")
        for s in sells:
            pnl_sign = "+" if s["pnl"] >= 0 else ""
            lines.append(
                f"  • {s['ticker']} | {pnl_sign}£{s['pnl']:.2f} | {s['reason']}"
            )

    # Top signals
    if top_signals:
        lines.append(f"")
        lines.append(f"💡 <b>Top signals this scan:</b>")
        for s in top_signals:
            bar = "█" * int(s["confidence"] / 10)
            lines.append(
                f"  • {s['ticker']} — {s['confidence']:.0f}%  {bar}  [{s['signal_type']}]"
            )

    if errors > 0:
        lines.append(f"")
        lines.append(f"⚠️ {errors} tickers skipped due to data errors")

    lines.append(f"")
    lines.append(f"📋 TradeCore Paper Scanner — £{starting_capital:,.0f} simulated")

    return send_message("\n".join(lines))


def send_weekly_paper_summary(summary: dict) -> bool:
    """
    Send the weekly 600-stock paper scanner performance summary.
    Fires Friday 18:00 — after the 17:30 live weekly summary.

    Args:
        summary: Dict returned by get_paper_summary() in paper_scanner.py
    """
    if not summary:
        return send_message(
            "📋 <b>WEEKLY PAPER SUMMARY</b>\n\n"
            "No data available — scanner may not have run this week.\n\n"
            "📋 TradeCore Paper Scanner"
        )

    portfolio_value = summary.get("portfolio_value", 0)
    cash = summary.get("cash", 0)
    starting_capital = summary.get("starting_capital", 10000)
    total_pnl = summary.get("total_pnl", 0)
    total_pnl_pct = summary.get("total_pnl_pct", 0)
    weekly_pnl = summary.get("weekly_pnl", 0)
    weekly_pnl_pct = summary.get("weekly_pnl_pct", 0)
    open_positions = summary.get("open_positions", 0)
    max_positions = summary.get("max_positions", 20)
    total_buys = summary.get("total_buys_week", 0)
    total_sells = summary.get("total_sells_week", 0)
    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    avg_win = summary.get("avg_win", 0.0)
    avg_loss = summary.get("avg_loss", 0.0)
    top_performers = summary.get("top_performers", [])
    worst_performers = summary.get("worst_performers", [])
    total_scanned = summary.get("total_scanned", 0)
    week_number = summary.get("week_number", 1)

    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    date_range = f"{week_start.strftime('%d %B')} — {today.strftime('%d %B %Y')}"

    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    total_pnl_str = f"+£{total_pnl:.2f}" if total_pnl >= 0 else f"-£{abs(total_pnl):.2f}"
    weekly_pnl_str = f"+£{weekly_pnl:.2f}" if weekly_pnl >= 0 else f"-£{abs(weekly_pnl):.2f}"
    total_pct_str = f"+{total_pnl_pct:.2f}%" if total_pnl_pct >= 0 else f"{total_pnl_pct:.2f}%"
    weekly_pct_str = f"+{weekly_pnl_pct:.2f}%" if weekly_pnl_pct >= 0 else f"{weekly_pnl_pct:.2f}%"

    lines = [
        f"📋 <b>WEEKLY PAPER SUMMARY — 600 STOCKS</b>",
        f"",
        f"<i>Week of {date_range}</i>",
        f"",
        f"<b>Paper Portfolio:</b> £{portfolio_value:,.2f} {pnl_emoji}",
        f"<b>Weekly P&L:</b> {weekly_pnl_str} ({weekly_pct_str})",
        f"<b>Total P&L:</b> {total_pnl_str} ({total_pct_str})",
        f"<b>Cash:</b> £{cash:,.2f}",
        f"<b>Positions:</b> {open_positions}/{max_positions}",
        f"",
        f"<b>Week activity:</b> {total_buys} buys | {total_sells} sells",
        f"<b>Universe scanned:</b> {total_scanned} stocks",
    ]

    # RawCap experiment counter (12 Jun 2026)
    rawcap_count = summary.get("rawcap_count", 0)
    rawcap_tickers = summary.get("rawcap_tickers", [])
    if rawcap_count > 0:
        lines.append(f"<b>RawCap fired:</b> {rawcap_count}x ({', '.join(rawcap_tickers)})")

    # Win/loss stats
    total_closed = wins + losses
    if total_closed > 0:
        win_rate = (wins / total_closed) * 100
        lines.append(f"")
        lines.append(f"<b>Closed trades:</b> {total_closed} ({win_rate:.0f}% win rate)")
        if avg_win > 0 or avg_loss < 0:
            avg_win_str = f"+£{avg_win:.2f}"
            avg_loss_str = f"-£{abs(avg_loss):.2f}"
            lines.append(f"<b>Avg win:</b> {avg_win_str} | <b>Avg loss:</b> {avg_loss_str}")

    # Top performers this week
    if top_performers:
        lines.append(f"")
        lines.append(f"🏆 <b>Top performers:</b>")
        for p in top_performers[:3]:
            pnl_str_p = f"+£{p['pnl']:.2f}" if p['pnl'] >= 0 else f"-£{abs(p['pnl']):.2f}"
            pct_str_p = f"+{p['pct']:.1f}%" if p['pct'] >= 0 else f"{p['pct']:.1f}%"
            lines.append(f"  ▲ {p['ticker']}  {pnl_str_p} ({pct_str_p})")

    # Worst performers this week
    if worst_performers:
        lines.append(f"")
        lines.append(f"📉 <b>Worst performers:</b>")
        for p in worst_performers[:3]:
            pnl_str_p = f"+£{p['pnl']:.2f}" if p['pnl'] >= 0 else f"-£{abs(p['pnl']):.2f}"
            pct_str_p = f"+{p['pct']:.1f}%" if p['pct'] >= 0 else f"{p['pct']:.1f}%"
            lines.append(f"  ▼ {p['ticker']}  {pnl_str_p} ({pct_str_p})")

    lines.append(f"")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<i>Paper only — no real money. Data collected for strategy review.</i>")
    lines.append(f"")
    lines.append(f"📋 TradeCore Paper Scanner — Week {week_number}")

    return send_message("\n".join(lines))

# ── Appended: send_earnings_drift_alert ──────────────────────────────────────

def send_earnings_drift_alert(ticker: str, price: float,
                               confidence: float, notes: str = "") -> bool:
    """
    Paper-only earnings drift signal alert.
    Fires when a stock had earnings in the last 2 days and shows
    confirmed gap + volume continuation. Not traded — data collection only.
    """
    short_notes = notes[:200] if notes else ""

    message = (
        f"📊 <b>PAPER DRIFT SIGNAL</b>\n"
        f"\n"
        f"<b>Stock:</b> {ticker}\n"
        f"<b>Price:</b> £{price:.2f}\n"
        f"<b>Confidence:</b> {confidence:.1f}%\n"
        f"<b>Signal:</b> {short_notes}\n"
        f"\n"
        f"<i>Post-earnings drift — paper only. Collecting data for review.</i>\n"
        f"\n"
        f"📊 TradeCore PAPER DRIFT"
    )
    return send_message(message)