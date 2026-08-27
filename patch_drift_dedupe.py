import sys

path = "execution/order_manager.py"
with open(path, "r") as f:
    content = f.read()

old = '''        if had_recent_earnings(ticker, days=2):
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
                )'''

new = '''        if had_recent_earnings(ticker, days=2):
            raw_drift = drift_engine.evaluate(ticker, df)
            if raw_drift.direction == "BUY" and raw_drift.confidence >= EARNINGS_DRIFT_MIN_CONFIDENCE:
                from datetime import date as _date2
                from database.db import get_connection as _get_connection2
                today_str2 = str(_date2.today())
                with _get_connection2() as _conn2:
                    already_alerted_drift_today = _conn2.execute(
                        """SELECT COUNT(*) as count FROM signals
                           WHERE ticker = ? AND signal_type = 'EARNINGS_DRIFT_PAPER'
                           AND date(created_at) = ?""",
                        (ticker, today_str2)
                    ).fetchone()["count"] > 0
                if not already_alerted_drift_today:
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
                    )'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
    sys.exit(1)

content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
print("Patched successfully")
