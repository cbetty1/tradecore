import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

from execution.order_manager import run_scan
from notifications.telegram import send_trade_alert, send_daily_report, send_signal_summary
from data.price_feed import get_historical_data, get_latest_price
from signals.momentum import MomentumSignal
from signals.confidence_scorer import score_signal
from execution.order_manager import load_portfolio_state, get_portfolio_value
from database.queries import get_snapshots
from database.db import get_connection
from datetime import datetime

# Load watchlist
with open("config/watchlist.json") as f:
    watchlist = json.load(f)["watchlist"]

print("\n" + "="*50)
print("  ⚡ TradeCore Daily Run")
print("="*50 + "\n")

# ── Signal Summary ────────────────────────────────────────────────────────────
print("📡 Scanning signals...")
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
print(f"✅ Signal summary sent — {len(signals)} stocks scanned")

# ── Run Scan + Execute Trades ─────────────────────────────────────────────────
print("\n💼 Running trade scan...")
actions = run_scan(watchlist, paper=True)

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
        print(f"  🟢 BUY {action['ticker']} | £{action['invest_amount']:.2f} | {action['confidence']:.0f}%")

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
        print(f"  🔴 SELL {action['ticker']} | P&L £{action['pnl']:.2f} | {action['reason']}")

if not actions:
    print("  ℹ️ No actions taken today")

# ── Daily Report ──────────────────────────────────────────────────────────────
print("\n📊 Generating daily report...")
state = load_portfolio_state()
portfolio_value = get_portfolio_value(state)
cash = state["cash"]
starting_capital = state["starting_capital"]
total_pnl = portfolio_value - starting_capital
open_positions = len(state["positions"])

snapshots = get_snapshots(2)
if len(snapshots) >= 2:
    daily_pnl = snapshots[0]["total_value"] - snapshots[1]["total_value"]
else:
    daily_pnl = 0.0

today = str(datetime.now().date())
with get_connection() as conn:
    trades_today = conn.execute(
        "SELECT COUNT(*) as count FROM trades WHERE date(opened_at) = ?",
        (today,)
    ).fetchone()["count"]

send_daily_report(
    portfolio_value=portfolio_value,
    cash=cash,
    total_pnl=total_pnl,
    daily_pnl=daily_pnl,
    open_positions=open_positions,
    trades_today=trades_today
)

print(f"✅ Daily report sent")
print(f"\n{'='*50}")
print(f"  Portfolio: £{portfolio_value:,.2f}")
print(f"  Total P&L: £{total_pnl:+,.2f}")
print(f"  Open Positions: {open_positions}")
print(f"  Cash Available: £{cash:,.2f}")
print(f"{'='*50}\n")