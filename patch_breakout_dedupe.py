import sys

path = "execution/order_manager.py"
with open(path, "r") as f:
    content = f.read()

old = '''        if BREAKOUT_PAPER_ONLY and raw_breakout.direction == "BUY" and raw_breakout.confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
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
            )'''

new = '''        if BREAKOUT_PAPER_ONLY and raw_breakout.direction == "BUY" and raw_breakout.confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
            # FIX: only alert once per ticker per day — this scan runs every 15 min
            # and a breakout condition can hold for hours, spamming duplicate alerts.
            from datetime import date as _date
            today_str = str(_date.today())
            with get_connection() as _conn:
                already_alerted_today = _conn.execute(
                    """SELECT COUNT(*) as count FROM signals
                       WHERE ticker = ? AND signal_type = 'BREAKOUT_PAPER'
                       AND date(created_at) = ?""",
                    (ticker, today_str)
                ).fetchone()["count"] > 0
            if not already_alerted_today:
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
                )'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
    sys.exit(1)

content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
print("Patched successfully")
